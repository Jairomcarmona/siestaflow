"""Stage-wise F03 numerical convergence built from canonical F02 campaigns."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from ..campaign_spec import CampaignSpec, InheritanceSource, ParameterMode, ParameterSpec
from ..contracts import ContractEnvelope, SCIENTIFIC_ARTIFACT
from ..contracts.scientific import NumericalProfileReference, ScientificAuthority
from .convergence import ConvergenceProtocol


_SELECTION_TYPE = "siestaflow.numerical-selection"
_PROFILE_TYPE = "siestaflow.numerical-profile"
_STAGE_PARAMETERS = {
    "basis": ("basis_size", "basis_energy_shift"),
    "mesh": ("mesh_cutoff",),
    "kpoints": ("kpoints",),
}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(encoded, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


class ChainedConvergenceProtocol:
    """Compose basis, mesh and k-point F02 stages through immutable handoffs."""

    def __init__(self, convergence: ConvergenceProtocol | None = None) -> None:
        self.convergence = convergence or ConvergenceProtocol()

    def run(
        self,
        basis_campaign: CampaignSpec,
        mesh_campaign: CampaignSpec,
        kpoint_campaign: CampaignSpec,
        *,
        profile: Mapping[str, Any] | None = None,
        project_config: Path | None = None,
        recipe: Path | None = None,
        overrides: Mapping[str, Any] | None = None,
        runs_root: Path = Path(".qraft-runs"),
        force_new_attempt: bool = False,
    ) -> dict[str, Any]:
        self._validate_templates(basis_campaign, mesh_campaign, kpoint_campaign)
        root = runs_root.resolve()
        handoff = root / "handoff"
        basis_result = self._run_stage(
            "basis", basis_campaign, root, profile, project_config, recipe,
            overrides, force_new_attempt,
        )
        if not self._converged(basis_result):
            return self._blocked(root, "basis", basis_result)
        basis_artifact = self._selection_artifact(
            handoff / "basis-selection.json", "basis", basis_campaign, basis_result
        )
        basis_parameter = str(basis_artifact["payload"]["parameter"])
        mesh_effective = self._with_inheritance(
            mesh_campaign, basis_parameter, basis_artifact
        )
        mesh_result = self._run_stage(
            "mesh", mesh_effective, root, profile, project_config, recipe,
            overrides, force_new_attempt,
        )
        if not self._converged(mesh_result):
            return self._blocked(root, "mesh", basis_result, mesh_result, basis_artifact)
        mesh_artifact = self._selection_artifact(
            handoff / "mesh-selection.json", "mesh", mesh_effective, mesh_result
        )
        kpoint_effective = self._with_inheritance(
            self._with_inheritance(kpoint_campaign, basis_parameter, basis_artifact),
            "mesh_cutoff", mesh_artifact,
        )
        kpoint_result = self._run_stage(
            "kpoints", kpoint_effective, root, profile, project_config, recipe,
            overrides, force_new_attempt,
        )
        if not self._converged(kpoint_result):
            return self._blocked(
                root, "kpoints", basis_result, mesh_result, basis_artifact,
                mesh_artifact, kpoint_result,
            )
        kpoint_artifact = self._selection_artifact(
            handoff / "kpoints-selection.json", "kpoints", kpoint_effective, kpoint_result
        )
        profile_artifact = self._profile_artifact(
            root / "numerical-profile.json",
            (basis_artifact, mesh_artifact, kpoint_artifact),
        )
        profile_reference = NumericalProfileReference(
            "f03-numerical-profile",
            str(profile_artifact["content_sha256"]),
            ScientificAuthority.PROVISIONAL,
        )
        result = {
            "schema_version": "1.0",
            "status": "COMPLETED",
            "stages": {"basis": basis_result, "mesh": mesh_result, "kpoints": kpoint_result},
            "handoff": self._handoff_summary(
                (basis_artifact, mesh_artifact, kpoint_artifact),
                ((basis_parameter, "mesh"), (basis_parameter, "kpoints"), ("mesh_cutoff", "kpoints")),
            ),
            "numerical_profile": str(root / "numerical-profile.json"),
            "numerical_profile_sha256": _sha_file(root / "numerical-profile.json"),
            "profile_reference": profile_reference,
        }
        _atomic_json(root / "chain-result.json", self._json_result(result))
        result["chain_result"] = str(root / "chain-result.json")
        return result

    def _run_stage(
        self, stage: str, campaign: CampaignSpec, root: Path,
        profile: Mapping[str, Any] | None, project_config: Path | None,
        recipe: Path | None, overrides: Mapping[str, Any] | None,
        force_new_attempt: bool,
    ) -> dict[str, Any]:
        return self.convergence.run(
            campaign, profile=profile, project_config=project_config, recipe=recipe,
            overrides=overrides, runs_root=root / "stages" / stage,
            force_new_attempt=force_new_attempt,
            invocation=f"qraft F03 {stage}",
        )

    @staticmethod
    def _converged(result: Mapping[str, Any]) -> bool:
        return (
            result.get("scientific_decision") == "CONVERGED"
            and result.get("selected_point") is not None
        )

    def _validate_templates(self, *campaigns: CampaignSpec) -> None:
        for stage, campaign in zip(("basis", "mesh", "kpoints"), campaigns):
            parameter, _ = campaign.scanned_parameter
            if parameter not in _STAGE_PARAMETERS[stage]:
                expected = " or ".join(_STAGE_PARAMETERS[stage])
                raise ValueError(f"{stage} stage must scan {expected}")
        first = campaigns[0]
        for campaign in campaigns[1:]:
            if campaign.engine != first.engine:
                raise ValueError("chained stages must use the same engine")
            for name in ("fdf", "pseudo_manifest", "structure"):
                left = getattr(first.system, name)
                right = getattr(campaign.system, name)
                if (left is None) != (right is None):
                    raise ValueError("chained stages must share the same scientific system")
                if left is not None and _sha_file(left) != _sha_file(right):
                    raise ValueError("chained stages must share the same scientific system")

    def _selection_artifact(
        self, path: Path, stage: str, campaign: CampaignSpec, result: Mapping[str, Any]
    ) -> dict[str, Any]:
        parameter, parameter_spec = campaign.scanned_parameter
        projection = {
            "campaign_fingerprint": campaign.fingerprint,
            "criterion": self._json_result(campaign.to_dict(include_source=False)["criterion"]),
            "scientific_decision": result["scientific_decision"],
            "selected_point": result["selected_point"],
            "points": [{
                key: point.get(key)
                for key in ("index", "value", "technical_status", "energy_ev", "energy_per_atom_ev", "delta")
            } for point in result["points"]],
        }
        payload = {
            "schema_version": "1.0",
            "artifact_id": f"{stage}-selection",
            "artifact_type": _SELECTION_TYPE,
            "authority": "PROVISIONAL",
            "stage": stage,
            "parameter": parameter,
            "selection": {"value": result["selected_point"], "unit": parameter_spec.unit},
            "campaign_id": campaign.campaign_id,
            "campaign_fingerprint": campaign.fingerprint,
            "scientific_evidence_sha256": _sha_bytes(_canonical(projection).encode("utf-8")),
        }
        envelope = ContractEnvelope.create(
            SCIENTIFIC_ARTIFACT, producer="qraft.chained-convergence", payload=payload
        ).to_dict()
        self._write_immutable(path, envelope)
        return {**envelope, "_path": str(path.resolve())}

    def _with_inheritance(
        self, campaign: CampaignSpec, parameter: str, artifact: Mapping[str, Any]
    ) -> CampaignSpec:
        expected_stage = "basis" if parameter in _STAGE_PARAMETERS["basis"] else "mesh"
        verified = self._verify_selection(
            artifact, expected_stage=expected_stage, expected_parameter=parameter
        )
        payload = verified["payload"]
        path = Path(str(artifact["_path"])).resolve()
        existing = campaign.parameters.get(parameter)
        unit = existing.unit if existing is not None else payload["selection"].get("unit")
        parameters = dict(campaign.parameters)
        parameters[parameter] = ParameterSpec(
            mode=ParameterMode.INHERIT,
            unit=unit,
            inheritance=InheritanceSource(
                evidence=str(path),
                value=self._scientific_value(payload["selection"]["value"]),
                evidence_sha256=_sha_file(path),
            ),
        )
        return replace(campaign, parameters=parameters)

    def _verify_selection(
        self, artifact: Mapping[str, Any], *, expected_stage: str,
        expected_parameter: str,
    ) -> dict[str, Any]:
        path = Path(str(artifact["_path"])).resolve()
        raw = json.loads(path.read_text(encoding="utf-8"))
        envelope = ContractEnvelope.from_dict(raw, required_contract=SCIENTIFIC_ARTIFACT)
        payload = dict(envelope.payload)
        required = {
            "schema_version", "artifact_id", "artifact_type", "authority", "stage",
            "parameter", "selection", "campaign_id", "campaign_fingerprint",
            "scientific_evidence_sha256",
        }
        if set(payload) != required:
            raise ValueError("selection artifact payload fields are invalid")
        if (
            payload["artifact_type"] != _SELECTION_TYPE
            or payload["authority"] != "PROVISIONAL"
            or payload["stage"] != expected_stage
            or payload["parameter"] != expected_parameter
            or not isinstance(payload["selection"], Mapping)
            or set(payload["selection"]) != {"value", "unit"}
        ):
            raise ValueError("selection artifact does not match inherited parameter")
        return {**raw, "payload": payload, "_path": str(path)}

    def _profile_artifact(
        self, path: Path, artifacts: tuple[Mapping[str, Any], ...]
    ) -> dict[str, Any]:
        selections: dict[str, Any] = {}
        for artifact in artifacts:
            path_value = Path(str(artifact["_path"])).resolve()
            verified = self._verify_selection(
                artifact,
                expected_stage=str(artifact["payload"]["stage"]),
                expected_parameter=str(artifact["payload"]["parameter"]),
            )
            payload = verified["payload"]
            selections[str(payload["parameter"])] = {
                "value": payload["selection"]["value"],
                "unit": payload["selection"]["unit"],
                "selection_artifact_sha256": _sha_file(path_value),
                "selection_contract_sha256": verified["content_sha256"],
            }
        envelope = ContractEnvelope.create(
            SCIENTIFIC_ARTIFACT,
            producer="qraft.chained-convergence",
            payload={
                "schema_version": "1.0",
                "artifact_id": "f03-numerical-profile",
                "artifact_type": _PROFILE_TYPE,
                "authority": "PROVISIONAL",
                "selections": selections,
            },
        ).to_dict()
        self._write_immutable(path, envelope)
        return envelope

    def _handoff_summary(
        self, artifacts: tuple[Mapping[str, Any], ...], links: tuple[tuple[str, str], ...]
    ) -> list[dict[str, Any]]:
        by_parameter = {str(item["payload"]["parameter"]): item for item in artifacts}
        return [{
            "parameter": parameter,
            "downstream_stage": downstream,
            "selection_artifact": str(by_parameter[parameter]["_path"]),
            "selection_artifact_sha256": _sha_file(Path(str(by_parameter[parameter]["_path"]))),
            "selected_value": by_parameter[parameter]["payload"]["selection"]["value"],
        } for parameter, downstream in links]

    def _blocked(
        self, root: Path, stage: str, *items: object
    ) -> dict[str, Any]:
        stages = {
            name: item for name, item in zip(("basis", "mesh", "kpoints"), items)
            if isinstance(item, Mapping) and "status" in item
        }
        result = {
            "schema_version": "1.0", "status": "BLOCKED",
            "blocking_stage": stage, "stages": stages,
        }
        _atomic_json(root / "chain-result.json", self._json_result(result))
        result["chain_result"] = str(root / "chain-result.json")
        return result

    @staticmethod
    def _json_result(value: object) -> Any:
        if isinstance(value, NumericalProfileReference):
            return {
                "profile_id": value.profile_id, "sha256": value.sha256,
                "authority": value.authority.value,
            }
        if isinstance(value, Mapping):
            return {str(key): ChainedConvergenceProtocol._json_result(item) for key, item in value.items() if key != "_path"}
        if isinstance(value, tuple):
            return [ChainedConvergenceProtocol._json_result(item) for item in value]
        if isinstance(value, list):
            return [ChainedConvergenceProtocol._json_result(item) for item in value]
        return value

    @staticmethod
    def _write_immutable(path: Path, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        if path.exists():
            if path.read_text(encoding="utf-8") != encoded:
                raise ValueError(f"immutable artifact content mismatch: {path}")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(encoded, encoding="utf-8", newline="\n")
        os.replace(temporary, path)

    @staticmethod
    def _scientific_value(value: object) -> Any:
        return tuple(value) if isinstance(value, list) else value
