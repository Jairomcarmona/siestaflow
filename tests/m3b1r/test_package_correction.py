from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from siestaflow.real_smoke import RealSiestaSmokePackager, RealSmokeSpec
from siestaflow.engines.siesta.models import OutputClassification
from siestaflow.engines.siesta.output_parser import SiestaOutputParser
from siestaflow.slurm_renderer import SlurmProfile


REPO = Path(__file__).resolve().parents[2]
PROJECT = REPO / "examples/reference_projects/graphene_surf_gr5x5"


def spec() -> RealSmokeSpec:
    return RealSmokeSpec(
        package_id="M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE",
        system_id="SURF_Gr5x5_clean_v01",
        geometry_path=PROJECT / "systems/SURF_Gr5x5_clean_v01.xyz",
        seed_fdf_path=PROJECT / "systems/SURF_Gr5x5_clean_v01.seed.fdf",
        pseudopotential_path=PROJECT / "pseudopotentials/C.psml",
        element="C", atomic_number=6,
        pseudopotential_provenance="PseudoDojo nc-sr-05 PBE stringent PSML; ONCVPSP metadata audited by T04A2/T06F",
        pseudopotential_license="CC-BY-4.0",
        redistribution_status="PERMITTED_WITH_ATTRIBUTION",
        profile=SlurmProfile(
            name="yoltla-m3b1-runtime-pending", verified_for_siesta=False,
            partition="q1h-20p", account="vini", qos="normal",
            nodes=1, ntasks=20, cpus_per_task=1, memory=None,
            walltime="00:10:00", signal="B:USR1@60", launcher_command=None,
        ),
    )


def package(tmp_path: Path) -> Path:
    return Path(RealSiestaSmokePackager(spec()).package(tmp_path).destination)


def test_manifest_uses_only_portable_packaged_paths(tmp_path: Path):
    root = package(tmp_path)
    manifest = json.loads((root / "package_manifest.json").read_text())
    for section in ("geometry", "fdf", "pseudopotential"):
        item = manifest[section]
        assert set(("packaged_path", "source_repository_path", "source_sha256", "packaged_sha256")) <= set(item)
        assert not Path(item["packaged_path"]).is_absolute()
        assert "\\" not in item["packaged_path"] and ".." not in Path(item["packaged_path"]).parts
    forbidden = ("C:\\", "/Users/", "/home/", "/LUSTRE/")
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() != ".psml":
            text = path.read_text(encoding="utf-8")
            assert not any(value in text for value in forbidden), (path, text)
    assert manifest["scheduler_profile"]["verified_for_siesta"] is False


def test_clean_linux_extraction_verifies_from_unrelated_cwd(tmp_path: Path):
    plan = RealSiestaSmokePackager(spec()).package(tmp_path / "release")
    extracted = tmp_path / "clean"; unrelated = tmp_path / "elsewhere"; unrelated.mkdir()
    with zipfile.ZipFile(plan.zip_path) as archive:
        archive.extractall(extracted)
    root = extracted / spec().package_id
    result = subprocess.run([sys.executable, str(root / "verify_package.py")], cwd=unrelated, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    print("CLEAN_LINUX_EXTRACTION_VERIFICATION_PASS")


@pytest.mark.parametrize("unsafe", ["/etc/passwd", "../outside.xyz", "geometry\\escape.xyz", "Z:/escape.xyz"])
def test_verifier_rejects_nonportable_or_escaping_manifest_paths(tmp_path: Path, unsafe: str):
    root = package(tmp_path)
    manifest_path = root / "package_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["geometry"]["packaged_path"] = unsafe
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    record_path = root / "package_manifest.sha256"
    record_path.write_text(f"{manifest_hash}  package_manifest.json\n")
    replacements = {
        "package_manifest.json": manifest_hash,
        "package_manifest.sha256": hashlib.sha256(record_path.read_bytes()).hexdigest(),
    }
    lines = []
    for line in (root / "checksums.sha256").read_text().splitlines():
        digest, name = line.split(None, 1)
        lines.append(f"{replacements.get(name, digest)}  {name}\n")
    (root / "checksums.sha256").write_text("".join(lines))
    result = subprocess.run([sys.executable, str(root / "verify_package.py")], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode != 0
    assert "UNSAFE_PACKAGED_PATH" in result.stderr


def test_distributed_package_has_no_preselected_slurm_and_no_runtime_search(tmp_path: Path):
    root = package(tmp_path)
    assert not list(root.rglob("*.slurm"))
    assert (root / "prepare_smoke_job.py").is_file()
    worker = (root / "scripts/run_siesta_smoke.sh").read_text()
    assert "for candidate in siesta" not in worker
    assert "for candidate in srun" not in worker
    assert "runtime_selection.json" in worker
    discovery = (root / "scripts/run_login_discovery.sh").read_text()
    assert "runtime_candidates.json" in discovery


def candidates(siesta=None, *, srun="/usr/bin/srun", mpi=True):
    executables = siesta if siesta is not None else [{"name": "siesta", "path": "/opt/siesta/bin/siesta", "mpi_confirmed": mpi, "version_output": "SIESTA MPI build"}]
    return {
        "source": "REAL_REMOTE_LOGIN_DISCOVERY",
        "modules_observed": ["siesta/5.4.2"],
        "modules_loaded": ["siesta/5.4.2"],
        "siesta_executables": executables,
        "srun": {"path": srun, "version_output": "slurm 23"} if srun else None,
        "other_launchers": [{"name": "mpiexec", "path": "/usr/bin/mpiexec"}],
        "scientific_calculation_performed": False,
        "job_submitted": False,
    }


def prepare(root: Path, data: dict, *extra: str):
    evidence = root / "evidence/login_discovery/runtime_candidates.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
    (evidence.parent / "runtime_candidates.sha256").write_text(f"{hashlib.sha256(evidence.read_bytes()).hexdigest()}  runtime_candidates.json\n")
    return subprocess.run([sys.executable, str(root / "prepare_smoke_job.py"), "--runtime-candidates", str(evidence), *extra], cwd=root, capture_output=True, text=True)


def test_unique_mpi_runtime_generates_selection_and_resources(tmp_path: Path):
    root = package(tmp_path)
    result = prepare(root, candidates())
    assert result.returncode == 0, result.stderr
    selection = json.loads((root / "generated/runtime_selection.json").read_text())
    assert selection["siesta_executable"] == "/opt/siesta/bin/siesta"
    assert selection["launcher"] == "/usr/bin/srun" and selection["mpi_confirmed"] is True
    script = (root / "generated/submit_real_siesta_smoke.slurm").read_text()
    assert "#SBATCH --nodes=1" in script
    assert "#SBATCH --ntasks=20" in script
    assert "#SBATCH --cpus-per-task=1" in script
    assert "#SBATCH --time=00:10:00" in script
    assert "trap '" in script and "USR1" in script
    assert script.index("trap '") < script.index("bash scripts/run_siesta_smoke.sh")


@pytest.mark.parametrize(
    "data,extra,code",
    [
        (candidates(siesta=[]), (), "SIESTA_RUNTIME_NOT_OBSERVED"),
        (candidates(siesta=[{"name":"a","path":"/opt/a","mpi_confirmed":True},{"name":"b","path":"/opt/b","mpi_confirmed":True}]), (), "SIESTA_RUNTIME_AMBIGUOUS_SELECTION"),
        (candidates(), ("--siesta-executable", "/not/observed"), "USER_SELECTION_NOT_SUPPORTED_BY_EVIDENCE"),
        (candidates(srun=None), (), "SRUN_RUNTIME_NOT_OBSERVED"),
        (candidates(mpi=False), (), "SIESTA_MPI_RUNTIME_NOT_CONFIRMED"),
    ],
)
def test_runtime_gates(tmp_path: Path, data: dict, extra: tuple[str, ...], code: str):
    root = package(tmp_path)
    result = prepare(root, data, *extra)
    assert result.returncode != 0
    assert code in result.stderr
    assert "SLURM_GENERATION_BLOCKED" in result.stderr
    assert not (root / "generated/submit_real_siesta_smoke.slurm").exists()


def test_usr1_trap_records_signal_without_killing_shell(tmp_path: Path):
    root = package(tmp_path); assert prepare(root, candidates()).returncode == 0
    script = (root / "generated/submit_real_siesta_smoke.slurm").read_text()
    # Self-signal avoids Windows/WSL background-process mediation while proving
    # that the installed handler records USR1 and returns control to the shell.
    script = script.replace("bash scripts/run_siesta_smoke.sh", "kill -USR1 $$\nprintf survived >\"$ROOT/evidence/shell_survived.txt\"")
    test_script = root / "generated/signal_test.slurm"; test_script.write_text(script, newline="\n")
    relative = Path(os.path.relpath(root, root)).as_posix()
    command = f'export SLURM_SUBMIT_DIR="$(cd {shlex.quote(relative)} && pwd -P)"; bash generated/signal_test.slurm'
    result = subprocess.run(["bash", "-c", command], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    signal = json.loads((root / "evidence/signal_summary.json").read_text())
    assert signal["signal_received"] is True
    assert (root / "evidence/shell_survived.txt").is_file()


def write_result_inputs(root: Path, output: str, *, code=0, state="COMPLETED", sacct_exit="0:0"):
    results = root / "results"; results.mkdir(exist_ok=True)
    (results / "siesta.out").write_text(output)
    (results / "siesta.err").write_text("")
    execution = root / "evidence/execution"; execution.mkdir(parents=True, exist_ok=True)
    (execution / "summary.json").write_text(json.dumps({"job_id":"42","exit_code":code}) + "\n")
    accounting = root / "evidence/accounting"; accounting.mkdir(parents=True, exist_ok=True)
    (accounting / "summary.json").write_text(json.dumps({"state":state,"exit_code":sacct_exit}) + "\n")


@pytest.mark.parametrize(
    "output,code,state,expected",
    [
        ("Siesta Version : 5.4.2\nSiesta started\nNumber of atoms: 50\nNumber of species: 1\nSCF cycle 1\nSCF converged\nJob completed\n", 0, "COMPLETED", "NORMAL_CONVERGED_TERMINATION"),
        ("Siesta started\nSCF cycle 4\nSCF not converged\nNormal termination\n", 0, "COMPLETED", "NORMAL_NONCONVERGED_TERMINATION"),
        ("Siesta started\nFDF error: bad input\n", 1, "FAILED", "INPUT_FAILURE"),
        ("Siesta started\nPseudopotential missing: C.psml\n", 1, "FAILED", "PSEUDOPOTENTIAL_FAILURE"),
        ("srun: error: task 0: Exited\nMPI_ABORT invoked\n", 1, "FAILED", "MPI_FAILURE"),
        ("Permission denied while opening output\n", 1, "FAILED", "FILESYSTEM_FAILURE"),
        ("Siesta started\n", 1, "TIMEOUT", "TIME_LIMIT"),
        ("Siesta started\n", 0, "COMPLETED", "UNKNOWN_FAILURE"),
    ],
)
def test_real_output_summary_uses_siesta_parser(tmp_path: Path, output: str, code: int, state: str, expected: str):
    root = package(tmp_path); write_result_inputs(root, output, code=code, state=state, sacct_exit="0:0" if code == 0 else "1:0")
    parser = root / "scripts/parse_siesta_result.py"
    result = subprocess.run([sys.executable, str(parser), "--package-root", str(root)], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    summary = json.loads((root / "evidence/result_summary.json").read_text())
    assert summary["termination_class"] == expected
    assert summary["scientific_interpretation_allowed"] is False
    assert summary["normal_termination"] is (expected.startswith("NORMAL_"))
    assert summary["pseudo_hash_verified"] and summary["fdf_hash_verified"] and summary["geometry_hash_verified"]
    assert summary["species"] == ["C"]
    assert "NaN_detected" in summary and "MPI_failure_detected" in summary and "filesystem_failure_detected" in summary


def test_parser_recognizes_observed_siesta_542_output_format():
    observed_excerpt = """\
Version         : 5.4.2
NumberOfAtoms 50
NumberOfSpecies 1
   scf:    1    -8261.879480    -8258.546688
   scf:   10    -8261.710079    -8261.710073
SCF Convergence by DM+H criterion
SCF cycle converged after 10 iterations
>> End of run:  21-JUL-2026  20:52:30
Job completed
"""
    record = SiestaOutputParser().parse(observed_excerpt.splitlines(True))
    assert record.classification is OutputClassification.COMPLETED
    assert record.version == "5.4.2"
    assert record.normal_termination is True
    assert record.scf_started is True
    assert record.scf_converged is True
    assert record.scf_iterations == 10
    assert record.atoms == 50
    assert record.species == 1


def test_parser_recognizes_successful_dm_restart_and_benign_deprecation():
    observed_excerpt = """\
Version         : 5.4.2
Reading input FDF
DM.UseSaveDM T
Attempting to read DM from file... Succeeded...
   scf:    1    -8261.879480    -8258.546688
SCF Convergence by DM+H criterion
SCF cycle converged after 1 iterations
WARNING: BASIS_ENTHALPY and BASIS_HARRIS_ENTHALPY files are deprecated.
>> End of run:  30-JUL-2026   0:36:33
Job completed
"""
    record = SiestaOutputParser().parse(observed_excerpt.splitlines(True))

    assert record.classification is OutputClassification.COMPLETED
    assert record.dm_restart_attempted is True
    assert record.dm_restart_succeeded is True
    assert len(record.warnings) == 1
    assert record.benign_warnings == record.warnings
