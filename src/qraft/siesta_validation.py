"""Explainable SIESTA 5.4.2 input validation beyond structural parsing."""

from __future__ import annotations

import math
from typing import Iterable

from .contract_adapters import validation_report_from_siesta
from .contracts import (
    CORE_CONTRACT_VERSION,
    VALIDATION_REPORT,
    CapabilityDescriptor,
    CapabilityKind,
    DecisionStatus,
    EvidenceClass,
    FindingScope,
    PluginDescriptor,
    ValidationFinding,
    ValidationReport,
    ValidationSubject,
    contract_sha256,
)
from .engines.siesta.fdf_registry import FDFRegistry
from .engines.siesta.input_validator import SiestaInputValidator
from .engines.siesta.models import FDFBlock, FDFDocument, FDFScalar
from .engines.siesta.pseudopotentials import (
    PseudopotentialVerificationResult,
)
from .engines.siesta.validation_catalog import SiestaValidationCatalog
from .engines.siesta.validation_profile import SiestaValidationProfile


_TRUE = {"t", "true", "yes", "y", "1", ".true."}
_FALSE = {"f", "false", "no", "n", "0", ".false."}
_UNIT_REQUIRED = {
    "energy_required",
    "length_required",
    "force_required",
}
_SPIN_VALUES = {
    "non-polarized",
    "polarized",
    "non-colinear",
    "spin-orbit",
    "spin-orbit+onsite",
}


class SiestaValidationRuleProvider:
    """Expose built-in rules through the Core Contracts plugin boundary."""

    def __init__(
        self,
        catalog: SiestaValidationCatalog | None = None,
    ) -> None:
        self.catalog = catalog or SiestaValidationCatalog.load_default()

    def rules(self):
        return tuple(entry.descriptor for entry in self.catalog.rules)


def siesta_validation_plugin(
    catalog: SiestaValidationCatalog | None = None,
) -> tuple[PluginDescriptor, SiestaValidationRuleProvider]:
    provider = SiestaValidationRuleProvider(catalog)
    capability = CapabilityDescriptor(
        capability_id="siestaflow.validation.siesta-input",
        kind=CapabilityKind.RULE_PROVIDER,
        implementation_version="0.1.0",
        input_contracts=(),
        output_contracts=(VALIDATION_REPORT,),
        engine="siesta",
        metadata={
            "engine_versions": [provider.catalog.engine_version],
            "ruleset_sha256": provider.catalog.sha256,
            "execution_authorized": False,
        },
    )
    descriptor = PluginDescriptor(
        plugin_id="siestaflow.plugin.siesta-validation",
        plugin_version="0.1.0",
        core_contract_version=CORE_CONTRACT_VERSION,
        capabilities=(capability,),
        provider="QRAFT",
        metadata={"bundled": True},
    )
    return descriptor, provider


class SiestaContextualValidator:
    """Combine legacy structural checks with versioned contextual rules."""

    def __init__(
        self,
        *,
        registry: FDFRegistry | None = None,
        catalog: SiestaValidationCatalog | None = None,
    ) -> None:
        self.registry = registry or FDFRegistry.load_default()
        self.catalog = catalog or SiestaValidationCatalog.load_default()
        self.structural = SiestaInputValidator(self.registry)

    def validate(
        self,
        document: FDFDocument,
        *,
        pseudo_result: PseudopotentialVerificationResult | None = None,
        require_pseudos: bool = False,
        profile: SiestaValidationProfile | None = None,
        subject_id: str | None = None,
    ) -> ValidationReport:
        legacy = self.structural.validate(
            document,
            pseudo_result=pseudo_result,
            require_pseudos=require_pseudos,
        )
        identifier = subject_id or legacy.system_id or "siesta-input"
        base = validation_report_from_siesta(
            legacy,
            subject_id=identifier,
            source=document.source,
            producer="siestaflow.siesta-contextual-validator",
        )
        findings = list(base.findings)
        findings.extend(self._keyword_findings(document, identifier))
        lattice, lattice_findings = self._lattice_findings(
            document, identifier
        )
        findings.extend(lattice_findings)
        kpoints, kgrid_findings = self._kgrid_findings(
            document, identifier
        )
        findings.extend(kgrid_findings)
        findings.extend(
            self._electrostatic_findings(document, identifier, profile)
        )
        findings.extend(
            self._d3_findings(document, identifier, profile, lattice)
        )
        findings.extend(self._dftu_findings(document, identifier, legacy.species))
        findings.extend(
            self._requested_output_findings(
                document, identifier, profile
            )
        )
        findings.extend(
            self._cost_findings(
                identifier,
                profile,
                legacy.atoms,
                kpoints,
            )
        )
        ruleset = contract_sha256(
            {
                "contextual_catalog": self.catalog.sha256,
                "structural_ruleset": base.ruleset_sha256,
            }
        )
        subject = ValidationSubject(
            subject_id=identifier,
            subject_type="siesta.fdf",
            engine="siesta",
            engine_version=self.catalog.engine_version,
            source=document.source,
            attributes={
                "atoms": legacy.atoms,
                "species": legacy.species,
                "profile_id": profile.profile_id if profile else None,
                "profile_sha256": profile.sha256 if profile else None,
                "kpoint_count": kpoints,
            },
        )
        return ValidationReport.build(
            report_id=f"{identifier}:siesta-contextual-validation",
            subject=subject,
            findings=tuple(_deduplicate(findings)),
            ruleset_sha256=ruleset,
            produced_by="siestaflow.siesta-contextual-validator",
            metadata={
                "catalog_sha256": self.catalog.sha256,
                "catalog_source": self.catalog.source_url,
                "catalog_source_accessed": self.catalog.source_accessed,
                "profile_applied": profile is not None,
                "execution_authorized": False,
                "heuristics_can_fail": False,
            },
        )

    def _keyword_findings(
        self,
        document: FDFDocument,
        subject_id: str,
    ) -> list[ValidationFinding]:
        result: list[ValidationFinding] = []
        for node in document.nodes:
            if isinstance(node, FDFScalar):
                name = node.label
                observed_kind = "scalar"
            elif isinstance(node, FDFBlock):
                name = node.name
                observed_kind = "block"
            else:
                continue
            entry = self.registry.get(name)
            if entry is None:
                continue
            location = f"line:{node.span.start_line}"
            if entry.kind != observed_kind:
                result.append(
                    self._finding(
                        "siestaflow.siesta.keyword-schema",
                        "KEYWORD_KIND_MISMATCH",
                        DecisionStatus.FAIL,
                        (
                            f"{entry.canonical_name} requires {entry.kind}, "
                            f"but the input uses {observed_kind}."
                        ),
                        FindingScope.SYNTAX,
                        subject_id,
                        location,
                        "Use the scalar or %block form documented by SIESTA.",
                    )
                )
                continue
            if not isinstance(node, FDFScalar):
                continue
            result.extend(
                self._scalar_findings(
                    node,
                    entry.canonical_name,
                    entry.value_type,
                    entry.unit_policy,
                    subject_id,
                )
            )
        return result

    def _scalar_findings(
        self,
        node: FDFScalar,
        canonical_name: str,
        value_type: str,
        unit_policy: str,
        subject_id: str,
    ) -> list[ValidationFinding]:
        result: list[ValidationFinding] = []
        location = f"line:{node.span.start_line}"
        invalid = False
        if value_type == "integer":
            invalid = _integer(node.value) is None
        elif value_type == "real":
            invalid = _real(node.value) is None
        elif value_type == "boolean":
            invalid = _boolean(node.value) is None
        elif value_type == "integer_list":
            values = _integer_list(node.value)
            invalid = values is None
            if values is not None and canonical_name == "DFTD3.Periodic":
                if not values or len(set(values)) != len(values) or any(
                    value not in {1, 2, 3} for value in values
                ):
                    invalid = True
        if canonical_name == "Spin" and node.value.casefold() not in _SPIN_VALUES:
            invalid = True
        if invalid:
            result.append(
                self._finding(
                    "siestaflow.siesta.keyword-schema",
                    "KEYWORD_VALUE_INVALID",
                    DecisionStatus.FAIL,
                    (
                        f"{canonical_name} has a value incompatible with "
                        f"registered type {value_type}: {node.value!r}."
                    ),
                    FindingScope.SYNTAX,
                    subject_id,
                    location,
                    "Use a value documented for this SIESTA 5.4.2 keyword.",
                )
            )
        if unit_policy in _UNIT_REQUIRED and node.unit is None:
            result.append(
                self._finding(
                    "siestaflow.siesta.keyword-schema",
                    "KEYWORD_UNIT_IMPLICIT",
                    DecisionStatus.REVIEW,
                    f"{canonical_name} does not declare its physical unit.",
                    FindingScope.NUMERICAL,
                    subject_id,
                    location,
                    "Declare an explicit SIESTA-supported unit to remove ambiguity.",
                )
            )
        if canonical_name == "Mesh.Cutoff":
            value = _real(node.value)
            if value is not None and value <= 0:
                result.append(
                    self._finding(
                        "siestaflow.siesta.keyword-schema",
                        "MESH_CUTOFF_NONPOSITIVE",
                        DecisionStatus.FAIL,
                        "Mesh.Cutoff must be positive.",
                        FindingScope.NUMERICAL,
                        subject_id,
                        location,
                        "Provide a positive cutoff and establish it by convergence.",
                    )
                )
        if canonical_name == "DFTU.ProjectorGenerationMethod":
            value = _integer(node.value)
            if value is not None and value not in {1, 2}:
                result.append(
                    self._finding(
                        "siestaflow.siesta.dftu-context",
                        "DFTU_PROJECTOR_METHOD_INVALID",
                        DecisionStatus.FAIL,
                        "SIESTA 5.4.2 documents DFTU projector methods 1 and 2.",
                        FindingScope.NUMERICAL,
                        subject_id,
                        location,
                        "Select method 1 or 2 and justify its projector policy.",
                    )
                )
        if canonical_name == "DFTU.CutoffNorm":
            value = _real(node.value)
            if value is not None and not 0 < value <= 1:
                result.append(
                    self._finding(
                        "siestaflow.siesta.dftu-context",
                        "DFTU_CUTOFF_NORM_INVALID",
                        DecisionStatus.FAIL,
                        "DFTU.CutoffNorm must represent a norm in (0, 1].",
                        FindingScope.NUMERICAL,
                        subject_id,
                        location,
                        "Use a physically valid enclosed norm and document it.",
                    )
                )
        if canonical_name in {"DFTU.ThresholdTol", "DFTU.PopTol"}:
            value = _real(node.value)
            if value is not None and value <= 0:
                result.append(
                    self._finding(
                        "siestaflow.siesta.dftu-context",
                        "DFTU_TOLERANCE_NONPOSITIVE",
                        DecisionStatus.FAIL,
                        f"{canonical_name} must be positive.",
                        FindingScope.NUMERICAL,
                        subject_id,
                        location,
                        "Use a positive tolerance justified by convergence behavior.",
                    )
                )
        return result

    def _lattice_findings(
        self,
        document: FDFDocument,
        subject_id: str,
    ) -> tuple[list[list[float]] | None, list[ValidationFinding]]:
        blocks = document.blocks("LatticeVectors")
        if not blocks:
            return None, []
        block = blocks[0]
        matrix = _numeric_matrix(block, rows=3, columns=3)
        if matrix is None:
            return None, [
                self._finding(
                    "siestaflow.siesta.lattice-consistency",
                    "LATTICE_MATRIX_INVALID",
                    DecisionStatus.FAIL,
                    "LatticeVectors must contain three rows of three finite numbers.",
                    FindingScope.STRUCTURE,
                    subject_id,
                    f"line:{block.span.start_line}",
                    "Correct the 3 by 3 lattice matrix before execution.",
                )
            ]
        determinant = _determinant(matrix)
        if abs(determinant) <= 1e-12:
            return matrix, [
                self._finding(
                    "siestaflow.siesta.lattice-consistency",
                    "LATTICE_MATRIX_SINGULAR",
                    DecisionStatus.FAIL,
                    "LatticeVectors has zero volume.",
                    FindingScope.STRUCTURE,
                    subject_id,
                    f"line:{block.span.start_line}",
                    "Provide three linearly independent lattice vectors.",
                    data={"determinant": determinant},
                )
            ]
        return matrix, []

    def _kgrid_findings(
        self,
        document: FDFDocument,
        subject_id: str,
    ) -> tuple[int | None, list[ValidationFinding]]:
        blocks = document.blocks("kgrid.MonkhorstPack")
        if not blocks:
            return 1, []
        block = blocks[0]
        rows = _data_lines(block)
        if len(rows) != 3:
            return None, [
                self._finding(
                    "siestaflow.siesta.kgrid-consistency",
                    "KGRID_MATRIX_INVALID",
                    DecisionStatus.FAIL,
                    "kgrid.MonkhorstPack requires exactly three rows.",
                    FindingScope.NUMERICAL,
                    subject_id,
                    f"line:{block.span.start_line}",
                    "Use three integer-matrix rows with one displacement each.",
                )
            ]
        matrix: list[list[float]] = []
        shifts: list[float] = []
        for row in rows:
            tokens = row.split()
            if len(tokens) != 4:
                return None, [
                    self._finding(
                        "siestaflow.siesta.kgrid-consistency",
                        "KGRID_MATRIX_INVALID",
                        DecisionStatus.FAIL,
                        "Each kgrid.MonkhorstPack row requires four values.",
                        FindingScope.NUMERICAL,
                        subject_id,
                        f"line:{block.span.start_line}",
                        "Use three integer coefficients and one real displacement.",
                    )
                ]
            integers = [_integer(item) for item in tokens[:3]]
            shift = _real(tokens[3])
            if any(item is None for item in integers) or shift is None:
                return None, [
                    self._finding(
                        "siestaflow.siesta.kgrid-consistency",
                        "KGRID_MATRIX_INVALID",
                        DecisionStatus.FAIL,
                        "The k-grid matrix must be integer and shifts must be real.",
                        FindingScope.NUMERICAL,
                        subject_id,
                        f"line:{block.span.start_line}",
                        "Correct the Monkhorst-Pack matrix and displacement vector.",
                    )
                ]
            matrix.append([float(item) for item in integers if item is not None])
            shifts.append(shift)
        determinant = _determinant(matrix)
        if abs(determinant) <= 1e-12:
            return None, [
                self._finding(
                    "siestaflow.siesta.kgrid-consistency",
                    "KGRID_MATRIX_SINGULAR",
                    DecisionStatus.FAIL,
                    "The Monkhorst-Pack integer matrix has zero determinant.",
                    FindingScope.NUMERICAL,
                    subject_id,
                    f"line:{block.span.start_line}",
                    "Provide a nonsingular k-grid supercell matrix.",
                )
            ]
        findings: list[ValidationFinding] = []
        unusual = [
            value
            for value in shifts
            if not any(abs(value - expected) < 1e-12 for expected in (0.0, 0.5))
        ]
        if unusual:
            findings.append(
                self._finding(
                    "siestaflow.siesta.kgrid-consistency",
                    "KGRID_SHIFT_REVIEW",
                    DecisionStatus.REVIEW,
                    (
                        "SIESTA documents 0.0 or 0.5 as usual k-grid "
                        f"displacements; observed {unusual}."
                    ),
                    FindingScope.NUMERICAL,
                    subject_id,
                    f"line:{block.span.start_line}",
                    "Confirm that the unusual displacement is intentional.",
                )
            )
        return int(round(abs(determinant))), findings

    def _electrostatic_findings(
        self,
        document: FDFDocument,
        subject_id: str,
        profile: SiestaValidationProfile | None,
    ) -> list[ValidationFinding]:
        charge_node = _first_scalar(document, "NetCharge")
        charge = _real(charge_node.value) if charge_node else None
        if charge is None or abs(charge) <= 1e-12:
            return []
        location = f"line:{charge_node.span.start_line}"
        findings: list[ValidationFinding] = []
        periodicity = profile.periodicity if profile else "unknown"
        if periodicity == "unknown":
            findings.append(
                self._finding(
                    "siestaflow.siesta.electrostatic-context",
                    "NET_CHARGE_PERIODICITY_UNDECLARED",
                    DecisionStatus.REVIEW,
                    (
                        f"NetCharge={charge:g}, but molecular or periodic "
                        "context was not declared."
                    ),
                    FindingScope.PHYSICAL,
                    subject_id,
                    location,
                    "Provide a validation profile declaring periodicity.",
                    data={"net_charge": charge},
                )
            )
        elif periodicity in {"chain", "slab", "bulk"}:
            findings.append(
                self._finding(
                    "siestaflow.siesta.electrostatic-context",
                    "PERIODIC_NET_CHARGE_REVIEW",
                    DecisionStatus.REVIEW,
                    (
                        f"NetCharge={charge:g} is used in a declared "
                        f"{periodicity} model."
                    ),
                    FindingScope.PHYSICAL,
                    subject_id,
                    location,
                    (
                        "Document the compensating-background convention, "
                        "finite-size limitations, and allowed comparisons."
                    ),
                    data={
                        "net_charge": charge,
                        "periodicity": periodicity,
                    },
                )
            )
        dipole = _scalar_boolean(document, "Slab.DipoleCorrection")
        if dipole is True:
            findings.append(
                self._finding(
                    "siestaflow.siesta.electrostatic-context",
                    "CHARGED_DIPOLE_CORRECTION_DISCOURAGED",
                    DecisionStatus.REVIEW,
                    (
                        "SIESTA 5.4.2 discourages combining non-neutral "
                        "charge with Slab.DipoleCorrection."
                    ),
                    FindingScope.PHYSICAL,
                    subject_id,
                    location,
                    "Reassess the electrostatic model before spending HPC time.",
                )
            )
        return findings

    def _d3_findings(
        self,
        document: FDFDocument,
        subject_id: str,
        profile: SiestaValidationProfile | None,
        lattice: list[list[float]] | None,
    ) -> list[ValidationFinding]:
        if _scalar_boolean(document, "DFTD3") is not True:
            return []
        if _first_scalar(document, "DFTD3.Periodic") is not None:
            return []
        ambiguous = lattice is not None and not _orthogonal(lattice)
        low_dimensional = (
            profile is not None
            and profile.periodicity in {"chain", "slab"}
        )
        if not ambiguous and not low_dimensional:
            return []
        node = _first_scalar(document, "DFTD3")
        return [
            self._finding(
                "siestaflow.siesta.d3-periodicity",
                "D3_PERIODICITY_REVIEW",
                DecisionStatus.REVIEW,
                (
                    "D3 is enabled without DFTD3.Periodic in a context where "
                    "automatic periodicity inference may be ambiguous."
                ),
                FindingScope.PHYSICAL,
                subject_id,
                f"line:{node.span.start_line}" if node else None,
                "Declare the intended D3 periodic lattice-vector axes.",
            )
        ]

    def _dftu_findings(
        self,
        document: FDFDocument,
        subject_id: str,
        species: tuple[str, ...],
    ) -> list[ValidationFinding]:
        block = next(iter(document.blocks("DFTU.Proj")), None)
        method = _first_scalar(document, "DFTU.ProjectorGenerationMethod")
        potential_shift = _first_scalar(document, "DFTU.PotentialShift")
        findings: list[ValidationFinding] = []
        if block is not None:
            rows = _data_lines(block)
            valid_header = False
            if rows:
                tokens = rows[0].split()
                shells = _integer(tokens[1]) if len(tokens) >= 2 else None
                valid_header = (
                    len(tokens) >= 2
                    and tokens[0].casefold()
                    in {item.casefold() for item in species}
                    and shells is not None
                    and shells > 0
                )
            if not valid_header:
                findings.append(
                    self._finding(
                        "siestaflow.siesta.dftu-context",
                        "DFTU_PROJECTOR_HEADER_INVALID",
                        DecisionStatus.FAIL,
                        (
                            "DFTU.Proj must begin with a declared species "
                            "label and a positive correlated-shell count."
                        ),
                        FindingScope.STRUCTURE,
                        subject_id,
                        f"line:{block.span.start_line}",
                        "Correct the documented DFTU.Proj species header.",
                    )
                )
            if method is None:
                findings.append(
                    self._finding(
                        "siestaflow.siesta.dftu-context",
                        "DFTU_PROJECTOR_METHOD_IMPLICIT",
                        DecisionStatus.REVIEW,
                        "DFTU.Proj is active but its generation method is implicit.",
                        FindingScope.PHYSICAL,
                        subject_id,
                        f"line:{block.span.start_line}",
                        "Declare and justify DFTU.ProjectorGenerationMethod.",
                    )
                )
        if potential_shift is not None and _boolean(potential_shift.value) is True:
            if block is None:
                findings.append(
                    self._finding(
                        "siestaflow.siesta.dftu-context",
                        "DFTU_POTENTIAL_SHIFT_WITHOUT_PROJECTOR",
                        DecisionStatus.BLOCKED,
                        "DFTU.PotentialShift is active without DFTU.Proj.",
                        FindingScope.STRUCTURE,
                        subject_id,
                        f"line:{potential_shift.span.start_line}",
                        "Provide the authorized DFTU projector definition.",
                    )
                )
            else:
                findings.append(
                    self._finding(
                        "siestaflow.siesta.dftu-context",
                        "DFTU_LINEAR_RESPONSE_MODE_ACTIVE",
                        DecisionStatus.REVIEW,
                        (
                            "DFTU.PotentialShift is true: U entries are local "
                            "potential shifts, not a productive Hubbard U."
                        ),
                        FindingScope.PHYSICAL,
                        subject_id,
                        f"line:{potential_shift.span.start_line}",
                        "Classify this task explicitly as linear-response U.",
                    )
                )
        return findings

    def _requested_output_findings(
        self,
        document: FDFDocument,
        subject_id: str,
        profile: SiestaValidationProfile | None,
    ) -> list[ValidationFinding]:
        required = set(profile.required_outputs if profile else ())
        bader = _scalar_boolean(document, "SaveBaderCharge")
        findings: list[ValidationFinding] = []
        if "bader" in required and bader is not True:
            findings.append(
                self._finding(
                    "siestaflow.siesta.requested-output",
                    "BADER_OUTPUT_NOT_ENABLED",
                    DecisionStatus.BLOCKED,
                    (
                        "The validation profile requires Bader data, but "
                        "SaveBaderCharge is not true."
                    ),
                    FindingScope.POLICY,
                    subject_id,
                    None,
                    "Enable SaveBaderCharge in the designated final SCF task.",
                )
            )
        if bader is True:
            cutoff = _mesh_cutoff_ry(document)
            if cutoff is None or cutoff < 300:
                node = _first_scalar(document, "SaveBaderCharge")
                findings.append(
                    self._finding(
                        "siestaflow.siesta.requested-output",
                        "BADER_MESH_CUTOFF_REVIEW",
                        DecisionStatus.REVIEW,
                        (
                            "SIESTA advises a moderately high Mesh.Cutoff "
                            "(300-500 Ry) for the localized model core charge."
                        ),
                        FindingScope.NUMERICAL,
                        subject_id,
                        f"line:{node.span.start_line}" if node else None,
                        (
                            "Converge the Bader density grid and monitor the "
                            "atomic basin around each model core."
                        ),
                        data={"mesh_cutoff_ry": cutoff},
                    )
                )
        return findings

    def _cost_findings(
        self,
        subject_id: str,
        profile: SiestaValidationProfile | None,
        atoms: int | None,
        kpoints: int | None,
    ) -> list[ValidationFinding]:
        if profile is None or kpoints is None:
            return []
        findings: list[ValidationFinding] = []
        maximum = profile.review_limits.get("max_kpoints")
        if maximum is not None and kpoints > maximum:
            findings.append(
                self._finding(
                    "siestaflow.siesta.cost-review",
                    "KPOINT_COUNT_EXCEEDS_PROJECT_REVIEW_LIMIT",
                    DecisionStatus.REVIEW,
                    (
                        f"Derived k-point count {kpoints} exceeds the "
                        f"project review limit {maximum}."
                    ),
                    FindingScope.POLICY,
                    subject_id,
                    None,
                    "Confirm convergence need and expected computational cost.",
                    data={"observed": kpoints, "limit": maximum},
                )
            )
        combined_limit = profile.review_limits.get(
            "max_atoms_times_kpoints"
        )
        if (
            combined_limit is not None
            and atoms is not None
            and atoms * kpoints > combined_limit
        ):
            findings.append(
                self._finding(
                    "siestaflow.siesta.cost-review",
                    "ATOM_KPOINT_PROXY_EXCEEDS_PROJECT_REVIEW_LIMIT",
                    DecisionStatus.REVIEW,
                    (
                        f"Atom-k-point proxy {atoms * kpoints} exceeds the "
                        f"project review limit {combined_limit}."
                    ),
                    FindingScope.POLICY,
                    subject_id,
                    None,
                    (
                        "Review the chosen cell and k-grid; this proxy is an "
                        "alert, not a runtime prediction."
                    ),
                    data={
                        "atoms": atoms,
                        "kpoints": kpoints,
                        "observed": atoms * kpoints,
                        "limit": combined_limit,
                    },
                )
            )
        return findings

    def _finding(
        self,
        rule_id: str,
        code: str,
        status: DecisionStatus,
        message: str,
        scope: FindingScope,
        subject_id: str,
        location: str | None,
        hint: str,
        *,
        data: dict[str, object] | None = None,
    ) -> ValidationFinding:
        rule = self.catalog.require(rule_id)
        return ValidationFinding(
            rule_id=rule_id,
            code=code,
            status=status,
            message=message,
            evidence_class=rule.descriptor.evidence_class,
            scope=scope,
            subject_id=subject_id,
            location=location,
            hint=hint,
            evidence=(rule.reference, self.catalog.source_url),
            data=dict(data or {}),
        )


def _deduplicate(
    findings: Iterable[ValidationFinding],
) -> tuple[ValidationFinding, ...]:
    result: list[ValidationFinding] = []
    seen: set[tuple[str, str, str | None, str]] = set()
    for finding in findings:
        key = (
            finding.rule_id,
            finding.code,
            finding.location,
            finding.message,
        )
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return tuple(result)


def _first_scalar(
    document: FDFDocument,
    name: str,
) -> FDFScalar | None:
    return next(iter(document.scalars(name)), None)


def _scalar_boolean(
    document: FDFDocument,
    name: str,
) -> bool | None:
    node = _first_scalar(document, name)
    return _boolean(node.value) if node else None


def _boolean(value: str) -> bool | None:
    normalized = value.strip().casefold()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    return None


def _integer(value: str) -> int | None:
    try:
        return int(value.strip())
    except ValueError:
        return None


def _integer_list(value: str) -> tuple[int, ...] | None:
    values: list[int] = []
    for token in value.replace("[", " ").replace("]", " ").split():
        item = _integer(token)
        if item is None:
            return None
        values.append(item)
    return tuple(values)


def _real(value: str) -> float | None:
    try:
        number = float(value.strip().replace("D", "E").replace("d", "e"))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _data_lines(block: FDFBlock) -> list[str]:
    result: list[str] = []
    for line in block.body_lines:
        content = line
        for marker in ("#", "!", ";"):
            content = content.split(marker, 1)[0]
        stripped = content.strip()
        if stripped:
            result.append(stripped)
    return result


def _numeric_matrix(
    block: FDFBlock,
    *,
    rows: int,
    columns: int,
) -> list[list[float]] | None:
    lines = _data_lines(block)
    if len(lines) != rows:
        return None
    matrix: list[list[float]] = []
    for line in lines:
        tokens = line.split()
        if len(tokens) != columns:
            return None
        parsed = [_real(token) for token in tokens]
        if any(item is None for item in parsed):
            return None
        matrix.append([float(item) for item in parsed if item is not None])
    return matrix


def _determinant(matrix: list[list[float]]) -> float:
    return (
        matrix[0][0]
        * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1]
        * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2]
        * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )


def _orthogonal(matrix: list[list[float]]) -> bool:
    for first, second in ((0, 1), (0, 2), (1, 2)):
        dot = sum(
            matrix[first][axis] * matrix[second][axis]
            for axis in range(3)
        )
        norm = math.sqrt(
            sum(value * value for value in matrix[first])
            * sum(value * value for value in matrix[second])
        )
        if norm <= 1e-12 or abs(dot) / norm > 1e-8:
            return False
    return True


def _mesh_cutoff_ry(document: FDFDocument) -> float | None:
    node = _first_scalar(document, "Mesh.Cutoff")
    if node is None:
        return None
    value = _real(node.value)
    if value is None:
        return None
    unit = (node.unit or "").casefold()
    if unit == "ry":
        return value
    if unit in {"ha", "hartree"}:
        return value * 2
    if unit == "ev":
        return value / 13.605693122994
    return None
