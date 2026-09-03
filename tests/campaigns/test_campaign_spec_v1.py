from __future__ import annotations

import json
import inspect
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from qraft.application import ApplicationConfiguration, QraftApplication
from qraft.cli import main
from qraft.campaign_spec import CampaignSpec, ParameterMode, ParameterSpec
from qraft.protocols.convergence import (
    ConvergencePoint, ConvergenceProtocol, evaluate_convergence,
    extract_total_energy,
)
from qraft.protocols.single_fdf import build_scientific_identity
from qraft.protocols.single_fdf import validate_technical_result
from qraft.execution.capability_runtime import WorkflowRuntimeResult


FDF = """SystemName QRAFT convergence test
SystemLabel qraft_convergence
NumberOfAtoms 1
NumberOfSpecies 1
Mesh.Cutoff 200 Ry
PAO.BasisSize DZP
%block ChemicalSpeciesLabel
1 6 C
%endblock ChemicalSpeciesLabel
%block LatticeVectors
10.0 0.0 0.0
0.0 10.0 0.0
0.0 0.0 10.0
%endblock LatticeVectors
AtomicCoordinatesFormat Ang
%block AtomicCoordinatesAndAtomicSpecies
0.0 0.0 0.0 1
%endblock AtomicCoordinatesAndAtomicSpecies
%block kgrid.MonkhorstPack
1 0 0 0.0
0 1 0 0.0
0 0 1 0.0
%endblock kgrid.MonkhorstPack
"""


def campaign_file(root: Path, *, parameter: dict | None = None) -> Path:
    (root / "calc.fdf").write_text(FDF, encoding="utf-8")
    (root / "C.psf").write_text("test pseudo\n", encoding="utf-8")
    path = root / "campaign.yaml"
    path.write_text(yaml.safe_dump({
        "schema_version": "1.0",
        "campaign_id": "mesh-smoke",
        "engine": "siesta",
        "protocol": "convergence",
        "system": {"fdf": "calc.fdf"},
        "parameters": {
            "mesh_cutoff": parameter or {
                "mode": "scan", "values": [200, 250, 300], "unit": "Ry",
            },
            "basis_size": {"mode": "fixed", "value": "DZP"},
        },
        "criterion": {
            "metric": "energy_per_atom", "delta": 0.001,
            "unit": "eV", "consecutive": 2,
        },
    }, sort_keys=False), encoding="utf-8")
    return path


def relaxation_campaign_file(root: Path) -> Path:
    path = campaign_file(root)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["relaxation"] = {
        "enabled": True,
        "type": "CG",
        "steps": 4,
        "max_force": 0.05,
        "unit": "eV/Ang",
    }
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_parameter_modes_and_invalid_combinations(tmp_path: Path) -> None:
    assert ParameterSpec.from_mapping({"mode": "fixed", "value": 450, "unit": "Ry"}).resolved_values() == (450,)
    assert ParameterSpec.from_mapping({"mode": "scan", "values": [1, 2]}).resolved_values() == (1, 2)
    assert ParameterSpec.from_mapping({"mode": "scan", "start": 1, "stop": 2, "step": 0.5}).resolved_values() == (1.0, 1.5, 2.0)
    evidence = tmp_path / "prior.json"; evidence.write_text("{}", encoding="utf-8")
    inherited = ParameterSpec.from_mapping({"mode": "inherit", "inherit": {"evidence": str(evidence), "value": 300}})
    assert inherited.mode is ParameterMode.INHERIT and inherited.resolved_values() == (300,)
    assert ParameterSpec.from_mapping({"mode": "disabled"}).resolved_values() == ()
    assert ParameterSpec.from_mapping({"mode": "auto-suggest", "suggestion": "try 400 Ry"}).resolved_values() == ()
    with pytest.raises(ValueError):
        ParameterSpec.from_mapping({"mode": "fixed", "value": 1, "values": [1, 2]})
    with pytest.raises(ValueError):
        ParameterSpec.from_mapping({"mode": "scan", "start": 1, "stop": 2, "step": 0})


def test_campaign_contract_rejects_hpc_and_supports_engine_extension(tmp_path: Path) -> None:
    path = campaign_file(tmp_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["engine_options"] = {"siesta": {"SCF.DM.Tolerance": {"value": 1e-5}}}
    spec = CampaignSpec.from_mapping(raw, source=path.resolve())
    assert spec.engine_options[0].name == "SCF.DM.Tolerance"
    raw["partition"] = "cluster"
    with pytest.raises(ValueError, match="HPC placement"):
        CampaignSpec.from_mapping(raw, source=path.resolve())


def test_preflight_blocks_unregistered_or_conflicting_engine_option(tmp_path: Path) -> None:
    path = campaign_file(tmp_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["engine_options"] = {"siesta": {"Made.Up.Keyword": 1}}
    invalid = CampaignSpec.from_mapping(raw, source=path.resolve())
    report = ConvergenceProtocol().preflight(invalid)
    assert report["status"] == "BLOCKED"
    assert any(item["code"] == "VARIANT_MATERIALIZATION_FAILED" for item in report["findings"])


def test_preflight_severity_and_missing_inputs(tmp_path: Path) -> None:
    spec = CampaignSpec.load(campaign_file(tmp_path))
    assert ConvergenceProtocol().preflight(spec)["status"] == "PASS"
    (tmp_path / "C.psf").unlink()
    report = ConvergenceProtocol().preflight(spec)
    assert report["status"] == "BLOCKED"
    assert any(item["severity"] == "ERROR" for item in report["findings"])


def test_inherit_provenance_checks_relative_identity_compatibility(tmp_path: Path) -> None:
    evidence = tmp_path / "prior.json"
    evidence.write_text(json.dumps({"scientific_identity_sha256": "a" * 64}), encoding="utf-8")
    path = campaign_file(tmp_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["parameters"]["basis_size"] = {
        "mode": "inherit",
        "inherit": {"evidence": "prior.json", "value": "DZP", "compatible_identity": "b" * 64},
    }
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    report = ConvergenceProtocol().preflight(CampaignSpec.load(path))
    assert report["status"] == "BLOCKED"
    assert any(item["code"] == "INHERIT_IDENTITY_INCOMPATIBLE" for item in report["findings"])


def test_render_is_deterministic_inspectable_and_never_executes(tmp_path: Path) -> None:
    spec = CampaignSpec.load(campaign_file(tmp_path))
    protocol = ConvergenceProtocol()
    rendered = protocol.render(spec, tmp_path / "rendered")
    before = [(Path(item["fdf"]).read_bytes(), item["sha256"]) for item in rendered["points"]]
    repeated = protocol.render(spec, tmp_path / "rendered")
    after = [(Path(item["fdf"]).read_bytes(), item["sha256"]) for item in repeated["points"]]
    assert before == after and rendered["executed"] is False and rendered["submitted"] is False
    assert b"Mesh.Cutoff 250 Ry" in before[1][0]
    assert b"PAO.BasisSize DZP" in before[1][0]
    assert not list((tmp_path / "rendered").rglob("stdout.txt"))


def test_campaign_fingerprint_binds_content_not_absolute_location(tmp_path: Path) -> None:
    first_root = tmp_path / "first"; first_root.mkdir()
    second_root = tmp_path / "second"; second_root.mkdir()
    first = CampaignSpec.load(campaign_file(first_root))
    second = CampaignSpec.load(campaign_file(second_root))
    assert first.fingerprint == second.fingerprint
    (second_root / "calc.fdf").write_text(FDF.replace("200 Ry", "201 Ry"), encoding="utf-8")
    assert CampaignSpec.load(second_root / "campaign.yaml").fingerprint != first.fingerprint


def test_renderer_replaces_punctuation_equivalent_siesta_label(tmp_path: Path) -> None:
    path = campaign_file(tmp_path)
    base = tmp_path / "calc.fdf"
    base.write_text(FDF.replace("Mesh.Cutoff", "MeshCutoff"), encoding="utf-8")
    point = ConvergenceProtocol().render(CampaignSpec.load(path), tmp_path / "alias")["points"][1]
    text = Path(point["fdf"]).read_text(encoding="utf-8")
    assert "Mesh.Cutoff 250 Ry" in text
    assert "MeshCutoff 200 Ry" not in text


def test_kpoint_and_basis_materialization_change_identity(tmp_path: Path) -> None:
    path = campaign_file(tmp_path, parameter={"mode": "scan", "grids": [[1, 1, 1], [2, 2, 2]]})
    raw = yaml.safe_load(path.read_text(encoding="utf-8")); raw["parameters"].pop("mesh_cutoff"); raw["parameters"]["kpoints"] = {"mode": "scan", "grids": [[1, 1, 1], [2, 2, 2]]}
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    spec = CampaignSpec.load(path)
    points = ConvergenceProtocol().render(spec, tmp_path / "kpoints")["points"]
    first = build_scientific_identity(Path(points[0]["fdf"]))
    second = build_scientific_identity(Path(points[1]["fdf"]))
    assert first.fingerprint != second.fingerprint


def test_manifest_declared_custom_pseudo_is_staged_for_each_point(tmp_path: Path) -> None:
    path = campaign_file(tmp_path)
    (tmp_path / "C.psf").rename(tmp_path / "carbon-custom.psf")
    manifest = tmp_path / "pseudos.json"
    manifest.write_text(json.dumps({"entries": [{"species": "C", "filename": "carbon-custom.psf"}]}), encoding="utf-8")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["system"]["pseudo_manifest"] = "pseudos.json"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    rendered = ConvergenceProtocol().render(CampaignSpec.load(path), tmp_path / "manifest-render")
    for point in rendered["points"]:
        pseudo_manifest = Path(point["pseudo_manifest"])
        assert pseudo_manifest.is_file() and (pseudo_manifest.parent / "carbon-custom.psf").is_file()
        build_scientific_identity(Path(point["fdf"]), pseudo_manifest=pseudo_manifest)


def test_metric_delta_consecutive_and_failed_point_exclusion(tmp_path: Path) -> None:
    stdout = tmp_path / "stdout"; stdout.write_text("siesta: E_KS(eV) = -10.25\n", encoding="utf-8")
    assert extract_total_energy(stdout) == -10.25
    points = (
        ConvergencePoint(1, 200, "PASS", -10.0, -10.0, None, "a", "a", None, None),
        ConvergencePoint(2, 250, "FAIL", None, None, None, "b", "b", None, None),
        ConvergencePoint(3, 300, "PASS", -10.0005, -10.0005, None, "c", "c", None, None),
        ConvergencePoint(4, 350, "PASS", -10.0009, -10.0009, None, "d", "d", None, None),
    )
    evaluated, decision, selected = evaluate_convergence(points, "energy_per_atom", 0.001, 2)
    assert evaluated[1].delta is None
    assert decision == "CONVERGED" and selected == 350
    _, decision, selected = evaluate_convergence(points[:3], "energy", 1e-6, 1)
    assert decision == "SCIENTIFIC_NOT_CONVERGED" and selected is None


def test_real_siesta_standard_warning_headers_are_technically_benign(tmp_path: Path) -> None:
    stdout = tmp_path / "stdout.txt"
    stderr = tmp_path / "stderr.txt"
    stdout.write_text(
        "Siesta started\nSCF cycle 1\nSCF converged\n"
        "# WARNING: This information might be incomplete!\n"
        "******** Begin: TS CHECKS AND WARNINGS ********\n"
        "******** End: TS CHECKS AND WARNINGS ********\n"
        "WARNING: BASIS_ENTHALPY and BASIS_HARRIS_ENTHALPY files are deprecated.\n"
        ">> End of run\nJob completed\n",
        encoding="utf-8",
    )
    stderr.write_text("Job completed\n", encoding="utf-8")
    assert validate_technical_result(exit_code=0, stdout=stdout, stderr=stderr).status == "PASS"


def test_campaign_run_qraft_out_csv_and_recovery(tmp_path: Path) -> None:
    campaign = campaign_file(tmp_path)
    fake = tmp_path / "fake.py"
    fake.write_text(
        "import re,sys\ntext=open(sys.argv[1], encoding='utf-8').read()\n"
        "v=float(re.search(r'Mesh\\.Cutoff\\s+([0-9.]+)',text,re.I).group(1))\n"
        "energy={200.0:-10.0,250.0:-10.0005,300.0:-10.0009}[v]\n"
        "print('Siesta started')\nprint('SCF cycle 1')\nprint('SCF converged')\n"
        "print(f'siesta: E_KS(eV) = {energy}')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / ("fake-siesta.cmd" if os.name == "nt" else "fake-siesta")
    if os.name == "nt":
        wrapper.write_text(
            f'@echo off\r\n"{sys.executable}" "{fake}" %1\r\n',
            encoding="utf-8",
        )
    else:
        wrapper.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$1"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
    overrides = {"partition": "local", "launcher": "direct", "executable": str(wrapper)}
    root = tmp_path / "runs"
    app = QraftApplication(ApplicationConfiguration(fdf=campaign, runs_root=root, overrides=overrides))
    first = app.run()
    assert first["technical_validation"] == "PASS"
    assert first["scientific_decision"] == "CONVERGED"
    assert [point["energy_ev"] for point in first["points"]] == [-10.0, -10.0005, -10.0009]
    assert [point["energy_per_atom_ev"] for point in first["points"]] == [-10.0, -10.0005, -10.0009]
    assert first["points"][0]["delta"] is None
    assert [point["delta"] for point in first["points"][1:]] == pytest.approx([0.0005, 0.0004])
    assert first["selected_point"] == 300
    assert (root / "qraft.out").is_file()
    assert (root / "results" / "convergence.csv").is_file()
    workflow = json.loads((root / "rendered" / "convergence-workflow.json").read_text(encoding="utf-8"))
    assert [task["task_id"] for task in workflow["tasks"]] == ["point_001", "point_002", "point_003"]
    assert all(task["capability"] == "siestaflow.engine.siesta" for task in workflow["tasks"])
    assert all(task.get("depends_on", []) == [] and task["outputs"] == [] for task in workflow["tasks"])
    assert all({item["destination"] for item in task["inputs"]} >= {"input.fdf", "C.psf"} for task in workflow["tasks"])
    manifests = sorted((root / "work").rglob("attempt.json"))
    originals = [path.read_bytes() for path in manifests]
    assert len(manifests) == 3
    for item, manifest in zip(first["points"], manifests):
        attempt = json.loads(manifest.read_text(encoding="utf-8"))["payload"]["attempt"]
        expected = build_scientific_identity(Path(item["fdf"]))
        assert attempt["scientific_identity_sha256"] == expected.fingerprint
        assert item["technical_status"] == "PASS" and Path(item["stdout"]).is_file()
    second = app.run()
    assert all(point["reused"] for point in second["points"])
    assert [path.read_bytes() for path in manifests] == originals
    refreshed = ConvergenceProtocol().run(
        CampaignSpec.load(campaign), overrides=overrides, runs_root=root,
        force_new_attempt=True,
    )
    assert not any(point["reused"] for point in refreshed["points"])
    assert {point["attempt_id"] for point in refreshed["points"]} == {"attempt-0002"}
    assert [path.read_bytes() for path in manifests] == originals
    result = json.loads((root / "campaign-result.json").read_text(encoding="utf-8"))
    assert result["algorithm"] == "qraft.convergence.v1"


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="SIGUSR1 unavailable")
def test_interrupted_campaign_preserves_runtime_state_without_final_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    import qraft.protocols.convergence as convergence_module

    campaign = campaign_file(tmp_path)
    root = tmp_path / "runs"

    class InterruptedRuntime:
        def __init__(self, *, root: Path, shutdown, **_kwargs) -> None:
            self.root = root
            self.shutdown = shutdown

        def run(self) -> WorkflowRuntimeResult:
            payload = {
                "schema_version": "1.0", "runtime_fingerprint": "test",
                "workflow_id": "test", "status": "INTERRUPTED", "revision": 0,
                "allocation_history": [], "tasks": {},
            }
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            state = {
                "schema_version": "1.0", "payload": payload,
                "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            }
            path = self.root / "state" / "workflow_runtime.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state), encoding="utf-8")
            os.kill(os.getpid(), signal.SIGUSR1)
            assert self.shutdown.requested
            return WorkflowRuntimeResult("INTERRUPTED", {}, {}, ())

    monkeypatch.setattr(convergence_module, "CompiledWorkflowRuntime", InterruptedRuntime)
    monkeypatch.setattr(
        convergence_module, "compose_runtime",
        lambda *_args, **_kwargs: SimpleNamespace(launcher=object(), allocation=object()),
    )
    app = QraftApplication(ApplicationConfiguration(
        fdf=campaign, runs_root=root,
        overrides={"partition": "local", "launcher": "direct", "executable": sys.executable},
    ))
    result = app.run()
    assert result["status"] == "INTERRUPTED"
    assert result["points"] == []
    assert result["result_manifest"] is None
    assert not (root / "campaign-result.json").exists()
    assert "SESSION RESULT : INTERRUPTED" in (root / "qraft.out").read_text(encoding="utf-8")
    status = app.status()
    assert status["campaign"] is None
    assert status["runtime"]["status"] == "INTERRUPTED"


def test_convergence_execution_authority_is_canonical_runtime() -> None:
    source = Path(inspect.getsourcefile(ConvergenceProtocol) or "")
    assert "execute_fdf_plan(" not in source.read_text(encoding="utf-8")


def test_public_relaxation_selection_renders_exact_value_and_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qraft.protocols.convergence as convergence_module

    campaign = CampaignSpec.load(relaxation_campaign_file(tmp_path))
    observed: list[Path] = []

    class FakeRelaxation:
        def run(self, fdf: Path, **_kwargs):
            observed.append(fdf)
            return {
                "status": "COMPLETED", "technical_validation": "PASS",
                "scientific_decision": "CONVERGED",
                "attempt": {"attempt_id": "attempt-0001", "stdout": "stdout.txt", "stderr": "stderr.txt"},
                "reused": False,
            }

    monkeypatch.setattr(convergence_module, "RelaxationProtocol", FakeRelaxation)
    downstream = ConvergenceProtocol()._run_downstream_relaxation(
        campaign,
        selected=100,
        decision="CONVERGED",
        convergence_result={"selected_point": 100, "scientific_decision": "CONVERGED"},
        root=tmp_path / "runs",
        profile=None,
        project_config=None,
        recipe=None,
        overrides={"partition": "local", "launcher": "direct", "executable": sys.executable},
        force_new_attempt=False,
    )

    assert downstream is not None and downstream["status"] == "COMPLETED"
    assert observed == [Path(downstream["rendered_fdf"])]
    text = Path(downstream["rendered_fdf"]).read_text(encoding="utf-8")
    assert "Mesh.Cutoff 100 Ry" in text
    assert "MD.TypeOfRun CG" in text
    assert "MD.Steps 4" in text
    assert "MD.MaxForceTol 0.05 eV/Ang" in text
    provenance = json.loads(Path(downstream["provenance"]).read_text(encoding="utf-8"))
    assert provenance["upstream"]["value"] == 100
    selection = json.loads(Path(downstream["selection"]).read_text(encoding="utf-8"))
    assert selection["scientific_decision"] == "CONVERGED"
    assert selection["selected_parameter"] == {"name": "mesh_cutoff", "value": 100, "unit": "Ry"}
    assert provenance["upstream"]["selection"] == downstream["selection"]
    assert provenance["upstream"]["selection_sha256"] == __import__("hashlib").sha256(
        Path(downstream["selection"]).read_bytes()
    ).hexdigest()
    assert provenance["downstream"]["rendered_fdf_sha256"]


def test_relaxation_is_fail_closed_without_converged_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qraft.protocols.convergence as convergence_module

    campaign = CampaignSpec.load(relaxation_campaign_file(tmp_path))
    calls: list[object] = []

    class UnexpectedRelaxation:
        def run(self, *_args, **_kwargs):
            calls.append(object())
            raise AssertionError("downstream relaxation must not run")

    monkeypatch.setattr(convergence_module, "RelaxationProtocol", UnexpectedRelaxation)
    protocol = ConvergenceProtocol()
    for decision, selected in (("SCIENTIFIC_NOT_CONVERGED", None), ("CONVERGED", None)):
        result = protocol._run_downstream_relaxation(
            campaign,
            selected=selected,
            decision=decision,
            convergence_result={},
            root=tmp_path / decision,
            profile=None,
            project_config=None,
            recipe=None,
            overrides=None,
            force_new_attempt=False,
        )
        assert result is not None and result["status"] == "BLOCKED"
    assert calls == []


def test_relaxation_declaration_persists_and_public_plan_exposes_dependency(
    tmp_path: Path,
) -> None:
    path = relaxation_campaign_file(tmp_path)
    first = CampaignSpec.load(path)
    second = CampaignSpec.load(path)
    assert first.relaxation == second.relaxation
    dag = ConvergenceProtocol().plan(
        first,
        overrides={"partition": "local", "launcher": "direct", "executable": sys.executable},
    )["dag"]
    nodes = {item["node_id"]: item for item in dag}
    assert nodes["render_relaxation"]["depends_on"] == ["scientific_decision"]
    assert nodes["relaxation"]["depends_on"] == ["render_relaxation"]
    assert nodes["downstream_result"]["depends_on"] == ["relaxation"]


def test_chained_campaign_resume_reuses_convergence_and_status_exposes_downstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qraft.protocols.convergence as convergence_module

    campaign = relaxation_campaign_file(tmp_path)
    fake = tmp_path / "fake.py"
    fake.write_text(
        "import re,sys\ntext=open(sys.argv[1], encoding='utf-8').read()\n"
        "v=float(re.search(r'Mesh\\.Cutoff\\s+([0-9.]+)',text,re.I).group(1))\n"
        "energy={200.0:-10.0,250.0:-10.0005,300.0:-10.0009}[v]\n"
        "print('Siesta started')\nprint('SCF converged')\n"
        "print(f'siesta: E_KS(eV) = {energy}')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / ("fake-siesta.cmd" if os.name == "nt" else "fake-siesta")
    if os.name == "nt":
        wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{fake}" %1\r\n', encoding="utf-8")
    else:
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$1"\n', encoding="utf-8")
        wrapper.chmod(0o755)

    calls: list[Path] = []

    class FakeRelaxation:
        def run(self, fdf: Path, **_kwargs):
            calls.append(fdf)
            return {
                "status": "COMPLETED", "technical_validation": "PASS",
                "scientific_decision": "CONVERGED",
                "attempt": {"attempt_id": "attempt-0001", "stdout": "stdout.txt", "stderr": "stderr.txt"},
                "reused": len(calls) > 1,
            }

    monkeypatch.setattr(convergence_module, "RelaxationProtocol", FakeRelaxation)
    root = tmp_path / "runs"
    app = QraftApplication(ApplicationConfiguration(
        fdf=campaign, runs_root=root,
        overrides={"partition": "local", "launcher": "direct", "executable": str(wrapper)},
    ))
    first = app.run()
    second = app.run()
    assert first["downstream"]["status"] == "COMPLETED"
    assert all(point["reused"] for point in second["points"])
    assert second["downstream"]["result"]["reused"] is True
    status = app.status()
    assert status["campaign"]["downstream"]["selected_parameter"]["value"] == 300
    assert Path(status["campaign"]["downstream"]["provenance"]).is_file()
    assert len(calls) == 2


def test_downstream_interruption_is_resumable_and_not_a_campaign_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qraft.protocols.convergence as convergence_module

    campaign = relaxation_campaign_file(tmp_path)
    fake = tmp_path / "fake.py"
    fake.write_text(
        "import re,sys\ntext=open(sys.argv[1], encoding='utf-8').read()\n"
        "v=float(re.search(r'Mesh\\.Cutoff\\s+([0-9.]+)',text,re.I).group(1))\n"
        "energy={200.0:-10.0,250.0:-10.0005,300.0:-10.0009}[v]\n"
        "print('Siesta started')\nprint('SCF converged')\n"
        "print(f'siesta: E_KS(eV) = {energy}')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "fake-siesta"
    wrapper.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$1"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    calls = 0

    class FakeRelaxation:
        def run(self, _fdf: Path, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {
                    "status": "INTERRUPTED", "technical_validation": "INCOMPLETE",
                    "scientific_decision": "NOT_EVALUATED", "reused": False,
                    "attempt": {
                        "attempt_id": "attempt-0001", "stdout": "stdout.txt", "stderr": "stderr.txt",
                        "result": {"execution_state": "INTERRUPTED"},
                    },
                }
            return {
                "status": "COMPLETED", "technical_validation": "PASS",
                "scientific_decision": "CONVERGED", "reused": False,
                "attempt": {
                    "attempt_id": "attempt-0002", "stdout": "stdout.txt", "stderr": "stderr.txt",
                    "result": {"execution_state": "COMPLETED"},
                },
            }

    monkeypatch.setattr(convergence_module, "RelaxationProtocol", FakeRelaxation)
    root = tmp_path / "runs"
    app = QraftApplication(ApplicationConfiguration(
        fdf=campaign, runs_root=root,
        overrides={"partition": "local", "launcher": "direct", "executable": str(wrapper)},
    ))

    interrupted = app.run()
    assert interrupted["status"] == "INTERRUPTED"
    assert interrupted["technical_validation"] == "INCOMPLETE"
    status = app.status()
    assert status["campaign"]["execution_state"] == "INTERRUPTED"
    assert status["campaign"]["downstream"]["status"] == "INTERRUPTED"
    assert status["campaign"]["downstream"]["result"]["attempt"]["result"]["execution_state"] == "INTERRUPTED"
    assert status["runtime"]["status"] == "COMPLETED"
    assert status["campaign"]["selected_point"] == 300

    resumed = app.run()
    assert resumed["status"] == "COMPLETED"
    assert resumed["downstream"]["result"]["attempt"]["attempt_id"] == "attempt-0002"
    assert all(point["reused"] for point in resumed["points"])


def test_downstream_technical_failure_remains_a_campaign_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qraft.protocols.convergence as convergence_module

    campaign = relaxation_campaign_file(tmp_path)
    fake = tmp_path / "fake.py"
    fake.write_text(
        "import re,sys\ntext=open(sys.argv[1], encoding='utf-8').read()\n"
        "v=float(re.search(r'Mesh\\.Cutoff\\s+([0-9.]+)',text,re.I).group(1))\n"
        "print('Siesta started')\nprint('SCF converged')\n"
        "print(f'siesta: E_KS(eV) = {-10.0 - v / 1000000}')\nprint('Job completed')\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "fake-siesta"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$1"\n', encoding="utf-8")
    wrapper.chmod(0o755)

    class FailedRelaxation:
        def run(self, _fdf: Path, **_kwargs):
            return {
                "status": "FAILED", "technical_validation": "FAIL",
                "scientific_decision": "NOT_EVALUATED", "reused": False,
                "attempt": {"attempt_id": "attempt-0001", "stdout": "stdout.txt", "stderr": "stderr.txt", "result": {"execution_state": "FAILED"}},
            }

    monkeypatch.setattr(convergence_module, "RelaxationProtocol", FailedRelaxation)
    app = QraftApplication(ApplicationConfiguration(
        fdf=campaign, runs_root=tmp_path / "runs",
        overrides={"partition": "local", "launcher": "direct", "executable": str(wrapper)},
    ))
    result = app.run()
    assert result["status"] == "FAILED"


def test_execution_changes_do_not_change_rendered_science(tmp_path: Path) -> None:
    campaign = CampaignSpec.load(campaign_file(tmp_path))
    protocol = ConvergenceProtocol()
    first = protocol.plan(campaign, overrides={"partition": "a", "launcher": "direct", "executable": sys.executable, "mpi_ranks": 1})
    second = protocol.plan(campaign, overrides={"partition": "b", "launcher": "openmpi", "executable": sys.executable, "mpi_ranks": 2})
    assert [item["sha256"] for item in first["variants"]] == [item["sha256"] for item in second["variants"]]
    assert first["execution_spec"]["fingerprint"] != second["execution_spec"]["fingerprint"]


def test_cli_validate_plan_and_render_share_campaign_semantics(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    campaign = campaign_file(tmp_path)
    assert main(["validate", str(campaign), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["execution_checked"] is False
    execution = ["--partition", "local", "--launcher", "direct", "--siesta", sys.executable]
    assert main(["plan", str(campaign), *execution, "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert len(plan["variants"]) == 3 and plan["submitted"] is False
    output = tmp_path / "cli-render"
    assert main(["render", str(campaign), "--output", str(output), "--json"]) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["executed"] is False and Path(rendered["manifest"]).is_file()
