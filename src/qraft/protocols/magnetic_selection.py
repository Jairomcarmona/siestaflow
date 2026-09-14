"""M8-D deterministic comparison of already verified magnetic M6 states.

This protocol has no execution authority.  It consumes immutable electronic
states and engine-produced final-SCF energy evidence, then records either a
unique selected state or a conservative review requirement.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from ..engines.siesta.effective_fdf import resolve_effective_fdf
from ..engines.siesta.relaxation import geometry_from_fdf
from .electronic_properties import ElectronicStateSource
from .single_fdf import build_scientific_identity


_ARTIFACT_TYPE = "qraft.magnetic-selection"
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _hex(value: object, field: str) -> str:
    text = str(value).strip().casefold()
    if not _SHA.fullmatch(text):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return text


def _fdf_value(source: ElectronicStateSource, label: str) -> str | None:
    occurrence = resolve_effective_fdf(source.final_fdf).occurrence(label)
    return occurrence.raw if occurrence is not None else None


def _comparison_context(source: ElectronicStateSource) -> dict[str, object]:
    identity = build_scientific_identity(source.final_fdf, pseudo_manifest=source.pseudo_manifest)
    atoms = geometry_from_fdf(source.final_fdf)["atoms"]
    numerical = {
        label: _fdf_value(source, label)
        for label in (
            "PAO.BasisSize", "PAO.Basis", "PAO.EnergyShift", "PAO.SplitNorm",
            "Mesh.Cutoff", "kgrid.MonkhorstPack", "ElectronicTemperature",
            "DM.MixingWeight", "DM.NumberPulay", "DM.Tolerance", "MaxSCFIterations",
        )
    }
    return {
        "composition_species_mapping_sha256": identity.species_mapping_sha256,
        "geometry_sha256": identity.geometry_sha256,
        "geometry_semantics": "final-scf effective geometry (fixed identity, not path provenance)",
        "atom_count": len(atoms),
        "xc_sha256": identity.components["xc"],
        "pseudopotentials": dict(identity.pseudopotentials),
        "final_scf_numerical_settings": numerical,
        "energy_definition": "siesta.final_total_energy",
        "energy_unit": "eV",
    }


@dataclass(frozen=True)
class MagneticCandidate:
    candidate_id: str
    state_path: Path
    final_fdf: Path
    density_matrix: Path
    pseudo_manifest: Path | None
    state_file_sha256: str
    state_content_sha256: str
    magnetic_state_file_sha256: str
    magnetic_state_content_sha256: str
    scientific_identity_sha256: str
    final_energy_artifact_path: Path | None = None
    final_energy_artifact_file_sha256: str | None = None
    final_energy_artifact_content_sha256: str | None = None

    @classmethod
    def from_source(
        cls,
        candidate_id: str,
        source: ElectronicStateSource,
        *,
        final_energy_artifact_path: Path | None = None,
    ) -> "MagneticCandidate":
        if source.magnetic_state_file_sha256 is None or source.magnetic_state_content_sha256 is None:
            raise ValueError("M8-D candidate requires verified qraft.magnetic-state evidence")
        return cls(
            candidate_id=candidate_id,
            state_path=source.state_path,
            final_fdf=source.final_fdf,
            density_matrix=source.density_matrix,
            pseudo_manifest=source.pseudo_manifest,
            state_file_sha256=source.state_file_sha256,
            state_content_sha256=source.state_content_sha256,
            magnetic_state_file_sha256=source.magnetic_state_file_sha256,
            magnetic_state_content_sha256=source.magnetic_state_content_sha256,
            scientific_identity_sha256=source.parent_scientific_identity_sha256,
            final_energy_artifact_path=(final_energy_artifact_path.resolve() if final_energy_artifact_path else None),
            final_energy_artifact_file_sha256=(
                hashlib.sha256(final_energy_artifact_path.read_bytes()).hexdigest()
                if final_energy_artifact_path else None
            ),
            final_energy_artifact_content_sha256=(
                ContractEnvelope.from_dict(
                    json.loads(final_energy_artifact_path.read_text(encoding="utf-8")),
                    required_contract=SCIENTIFIC_ARTIFACT,
                ).content_sha256 if final_energy_artifact_path else None
            ),
        )


class MagneticSelectionProtocol:
    """Conservatively select only a unique, comparable lowest-energy state."""

    def compare(
        self,
        candidates: Sequence[MagneticCandidate],
        *,
        energy_tolerance_ev_per_atom: float,
    ) -> dict[str, object]:
        if not candidates:
            raise ValueError("M8-D requires at least one candidate")
        if not isinstance(energy_tolerance_ev_per_atom, (int, float)) or isinstance(energy_tolerance_ev_per_atom, bool) or not math.isfinite(float(energy_tolerance_ev_per_atom)) or float(energy_tolerance_ev_per_atom) < 0:
            raise ValueError("energy_tolerance_ev_per_atom must be a finite non-negative number")
        ids = [candidate.candidate_id for candidate in candidates]
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", item) for item in ids) or len(set(ids)) != len(ids):
            raise ValueError("M8-D candidate IDs must be unique portable identifiers")

        checked: list[dict[str, object]] = []
        for candidate in sorted(candidates, key=lambda item: item.candidate_id):
            try:
                checked.append(self._verify_candidate(candidate))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                checked.append({"candidate_id": candidate.candidate_id, "selection_status": "INCOMPLETE", "reason": str(exc)})
        if any(item["selection_status"] != "ELIGIBLE" for item in checked):
            return self._result("REVIEW_REQUIRED", checked, energy_tolerance_ev_per_atom, reason="all required candidates need verified state, magnetic, and final-energy evidence")

        contexts = {str(item["comparison_context_sha256"]) for item in checked}
        if len(contexts) != 1:
            for item in checked:
                item["selection_status"] = "INCOMPATIBLE"
                item["reason"] = "candidate comparison context differs"
            return self._result("REVIEW_REQUIRED", checked, energy_tolerance_ev_per_atom, reason="candidate scientific contexts are not comparable")

        ordered = sorted(checked, key=lambda item: (float(item["energy_ev_per_atom"]), str(item["candidate_id"])))
        minimum = float(ordered[0]["energy_ev_per_atom"])
        tied = [item for item in ordered if float(item["energy_ev_per_atom"]) - minimum <= float(energy_tolerance_ev_per_atom)]
        for rank, item in enumerate(ordered, start=1):
            item["rank"] = rank
            item["delta_energy_ev"] = float(item["energy_ev"]) - float(ordered[0]["energy_ev"])
            item["delta_ev_per_atom_from_min"] = float(item["energy_ev_per_atom"]) - minimum
        if len(tied) != 1:
            for item in checked:
                item["selection_status"] = "DEGENERATE" if item in tied else "ELIGIBLE"
            return self._result("REVIEW_REQUIRED", checked, energy_tolerance_ev_per_atom, reason="lowest candidates are degenerate within explicit tolerance")
        selected = tied[0]
        selected["selection_status"] = "SELECTED"
        return self._result("SELECTED", checked, energy_tolerance_ev_per_atom, selected=selected)

    def _verify_candidate(self, candidate: MagneticCandidate) -> dict[str, object]:
        source = ElectronicStateSource.load(
            candidate.state_path, final_fdf=candidate.final_fdf,
            density_matrix=candidate.density_matrix, pseudo_manifest=candidate.pseudo_manifest,
        )
        expected = {
            "state_file_sha256": _hex(candidate.state_file_sha256, "candidate state file hash"),
            "state_content_sha256": _hex(candidate.state_content_sha256, "candidate state content hash"),
            "magnetic_state_file_sha256": _hex(candidate.magnetic_state_file_sha256, "candidate magnetic state file hash"),
            "magnetic_state_content_sha256": _hex(candidate.magnetic_state_content_sha256, "candidate magnetic state content hash"),
            "scientific_identity_sha256": _hex(candidate.scientific_identity_sha256, "candidate scientific identity"),
        }
        actual = {
            "state_file_sha256": source.state_file_sha256,
            "state_content_sha256": source.state_content_sha256,
            "magnetic_state_file_sha256": source.magnetic_state_file_sha256,
            "magnetic_state_content_sha256": source.magnetic_state_content_sha256,
            "scientific_identity_sha256": source.parent_scientific_identity_sha256,
        }
        if expected != actual:
            raise ValueError("candidate state, magnetic artifact, or scientific identity hash changed")
        state_raw = json.loads(source.state_path.read_text(encoding="utf-8"))
        final = state_raw["payload"].get("final_scf")
        if not isinstance(final, Mapping) or final.get("scf_converged") is not True:
            raise ValueError("candidate electronic-state lacks converged final-SCF evidence")
        evidence = final.get("final_energy") if isinstance(final.get("final_energy"), Mapping) else self._external_energy_evidence(candidate, source)
        if not isinstance(evidence, Mapping):
            raise ValueError("candidate lacks final-energy evidence")
        energy = self._energy_evidence(evidence, source)
        context = _comparison_context(source)
        return {
            "candidate_id": candidate.candidate_id,
            "spin_mode": source.spin_mode,
            "selection_status": "ELIGIBLE",
            "scientific_identity_sha256": source.parent_scientific_identity_sha256,
            "state_reference": {"file_sha256": source.state_file_sha256, "content_sha256": source.state_content_sha256},
            "magnetic_state_reference": {"file_sha256": source.magnetic_state_file_sha256, "content_sha256": source.magnetic_state_content_sha256},
            "final_energy": dict(evidence),
            "energy_ev": energy,
            "energy_ev_per_atom": energy / int(context["atom_count"]),
            "comparison_context": context,
            "comparison_context_sha256": _sha(context),
        }

    @staticmethod
    def _external_energy_evidence(candidate: MagneticCandidate, source: ElectronicStateSource) -> Mapping[str, object] | None:
        path = candidate.final_energy_artifact_path
        if path is None or candidate.final_energy_artifact_file_sha256 is None or candidate.final_energy_artifact_content_sha256 is None:
            return None
        if not path.is_file():
            raise ValueError("historic final-energy artifact is missing")
        if hashlib.sha256(path.read_bytes()).hexdigest() != _hex(candidate.final_energy_artifact_file_sha256, "historic final-energy artifact file hash"):
            raise ValueError("historic final-energy artifact file SHA-256 mismatch")
        raw = json.loads(path.read_text(encoding="utf-8"))
        envelope = ContractEnvelope.from_dict(raw, required_contract=SCIENTIFIC_ARTIFACT)
        if envelope.content_sha256 != _hex(candidate.final_energy_artifact_content_sha256, "historic final-energy artifact content hash"):
            raise ValueError("historic final-energy artifact content SHA-256 mismatch")
        payload = envelope.payload
        if payload.get("artifact_type") != "qraft.final-scf-energy":
            raise ValueError("historic final-energy artifact type is invalid")
        parent = payload.get("parent_electronic_state")
        if not isinstance(parent, Mapping):
            raise ValueError("historic final-energy artifact parent is invalid")
        expected = {
            "file_sha256": source.state_file_sha256,
            "content_sha256": source.state_content_sha256,
            "scientific_identity_sha256": source.parent_scientific_identity_sha256,
            "magnetic_state_file_sha256": source.magnetic_state_file_sha256,
            "magnetic_state_content_sha256": source.magnetic_state_content_sha256,
        }
        if dict(parent) != expected:
            raise ValueError("historic final-energy artifact parent hash binding is invalid")
        evidence = payload.get("energy")
        return evidence if isinstance(evidence, Mapping) else None

    @staticmethod
    def _energy_evidence(evidence: Mapping[str, object], source: ElectronicStateSource) -> float:
        required = {"schema_version", "quantity", "value_ev", "unit", "parser", "source_stdout_sha256", "source_final_fdf_sha256", "scf_converged"}
        if set(evidence) != required:
            raise ValueError("final-energy evidence schema is invalid")
        if evidence["schema_version"] != "1.0" or evidence["quantity"] != "siesta.final_total_energy" or evidence["unit"] != "eV" or evidence["parser"] != "qraft.siesta.final-total-energy.v1" or evidence["scf_converged"] is not True:
            raise ValueError("final-energy evidence semantics are invalid")
        if source.magnetic_stdout_sha256 is None:
            raise ValueError("magnetic candidate lacks stdout hash binding")
        if _hex(evidence["source_stdout_sha256"], "final-energy stdout hash") != source.magnetic_stdout_sha256:
            raise ValueError("final-energy stdout hash does not match magnetic evidence")
        if _hex(evidence["source_final_fdf_sha256"], "final-energy FDF hash") != source.final_fdf_sha256:
            raise ValueError("final-energy FDF hash does not match electronic-state evidence")
        value = evidence["value_ev"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError("final energy must be finite numeric eV evidence")
        return float(value)

    @staticmethod
    def _result(status: str, candidates: Sequence[Mapping[str, object]], tolerance: float, *, selected: Mapping[str, object] | None = None, reason: str | None = None) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": "1.0", "artifact_type": _ARTIFACT_TYPE,
            "selection_status": status,
            "energy_tolerance_ev_per_atom": float(tolerance),
            "comparison_policy": {
                "metric": "siesta.final_total_energy",
                "unit": "eV",
                "normalization": "eV_per_atom",
                "tie_handling": "REVIEW_REQUIRED_DEGENERATE",
                "partial_candidates": "FORBIDDEN",
                "required_comparison_context": (
                    "composition_species_mapping", "geometry", "xc", "pseudopotentials",
                    "final_scf_numerical_settings", "energy_definition", "energy_unit",
                ),
            },
            "candidates": [dict(item) for item in sorted(candidates, key=lambda item: str(item["candidate_id"]))],
        }
        if selected is not None:
            selected_state = {
                "candidate_id": selected["candidate_id"],
                "scientific_identity_sha256": selected["scientific_identity_sha256"],
                "state": selected["state_reference"],
                "magnetic_state": selected["magnetic_state_reference"],
            }
            result["selected_state"] = selected_state
            result["selected_state_reference"] = selected_state
        if reason is not None:
            result["reason"] = reason
        result["selection_sha256"] = _sha(result)
        return result

    @staticmethod
    def write(path: Path, result: Mapping[str, object]) -> dict[str, object]:
        if result.get("artifact_type") != _ARTIFACT_TYPE:
            raise ValueError("M8-D selection result has invalid artifact type")
        document = ContractEnvelope.create(
            SCIENTIFIC_ARTIFACT, producer="qraft.magnetic-selection",
            payload={"schema_version": "1.0", "artifact_id": "magnetic-selection", "artifact_type": _ARTIFACT_TYPE, "authority": "PROVISIONAL", "selection": dict(result)},
        ).to_dict()
        encoded = json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") != encoded:
            raise ValueError("immutable M8-D selection collision")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(encoded, encoding="utf-8", newline="\n")
        return document
