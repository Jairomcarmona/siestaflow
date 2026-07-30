from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))


def module_from(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


profilectl = module_from(ROOT / "scripts/profilectl.py", "profilectl_test")
campaignctl = module_from(ROOT / "scripts/campaignctl.py", "campaignctl_test")
geometry_transfer = module_from(
    ROOT / "scripts/geometry_transfer.py", "geometry_transfer_test"
)
runtime_preflight = module_from(
    ROOT / "scripts/runtime_preflight.py", "runtime_preflight_test"
)
verifier = module_from(ROOT / "verify_package.py", "verify_package_test")

from siestaflow.execution.allocation_controller import (
    AllocationController,
    ExecutionStatus,
)
from siestaflow.execution.resource_manager import ResourceManager
from siestaflow.execution.srun_launcher import (
    HydraSshLauncher,
    SrunLauncher,
    StepLaunchSpec,
    StepOutcome,
)
from siestaflow.execution.time_utils import (
    canonical_slurm_walltime,
    parse_slurm_walltime,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeCompleted:
    def __init__(self, output: str, code: int = 0):
        self.stdout = output
        self.stderr = ""
        self.returncode = code


class SequenceLauncher:
    backend = "mock"

    def __init__(self, exits: list[int]):
        self.exits = list(exits)
        self.calls = 0

    def launch(self, spec):
        self.calls += 1
        code = self.exits.pop(0)
        spec.stdout_path.write_text(
            "Version: 5.4.2\nReading input FDF\nSCF iteration 1\n"
            "SCF converged\nJob completed\n",
            encoding="utf-8",
        )
        spec.stderr_path.write_text("", encoding="utf-8")
        return StepOutcome(
            spec.task_id,
            spec.attempt_id,
            ("mock",),
            code,
            0.01,
            False,
            "mock",
            spec.reservation.as_dict(),
            None,
        )

    def terminate_all(self, *, kill=False):
        return ()


def controller_fixture(root: Path, exits: list[int], *, end_seconds: float = 300):
    (root / "input").mkdir()
    (root / "pseudopotentials").mkdir()
    fdf = root / "input/task.fdf"
    pseudo = root / "pseudopotentials/X.psml"
    fdf.write_text("TEST\n", encoding="utf-8")
    pseudo.write_text("PSML\n", encoding="utf-8")
    config = {
        "schema_version": "2.0",
        "campaign_id": "retry-test",
        "system_id": "synthetic",
        "slurm": {"partition": "test", "account": "test", "qos": "normal"},
        "resources": {
            "nodes": 1,
            "physical_cpus_per_node": 2,
            "total_cpus": 2,
            "tasks_per_node": 2,
            "walltime": "00:05:00",
            "max_parallel_steps": 1,
            "shutdown_margin_seconds": 1,
            "termination_grace_seconds": 0,
        },
        "runtime": {
            "siesta_executable": "siesta",
            "required_siesta_version": "5.4.2",
            "launcher": {
                "backend": "hydra_ssh",
                "command": ["mpiexec.hydra"],
                "arguments": [],
                "bootstrap": "ssh",
            },
            "environment": {},
        },
        "tasks": [
            {
                "task_id": "task",
                "input": "input/task.fdf",
                "input_hashes": {
                    "input/task.fdf": sha(fdf),
                    "pseudopotentials/X.psml": sha(pseudo),
                },
                "required_artifacts": [],
                "mpi_processes": 1,
                "cpus_per_process": 1,
                "nodes_required": 1,
                "estimated_runtime_seconds": 2,
                "max_attempts": 3,
                "retry_backoff_seconds": 0,
                "retryable_exit_codes": [124],
                "require_scf_converged": True,
                "depends_on": [],
                "postcondition": None,
            }
        ],
    }
    path = root / "controller.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    environment = {
        "SLURM_JOB_ID": "test-job",
        "SLURM_SUBMIT_DIR": str(root),
        "SLURM_JOB_END_TIME": str(time.time() + end_seconds),
        "SLURM_NNODES": "1",
        "SLURM_NTASKS": "2",
        "SLURM_NTASKS_PER_NODE": "2",
        "SLURM_CPUS_PER_TASK": "1",
        "SLURM_JOB_NODELIST": "node1",
        "SIESTAFLOW_ALLOCATED_HOSTS": "node1",
    }
    launcher = SequenceLauncher(exits)
    controller = AllocationController.from_file(
        path,
        environment=environment,
        launcher=launcher,
        poll_interval_seconds=0.01,
    )
    return controller, launcher


@contextmanager
def prepared_package_copy(parent: Path):
    copied = parent / ROOT.name
    shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    old_root = campaignctl.ROOT
    old_base = campaignctl.BASE_FDF
    old_profile_root = campaignctl.profilectl.ROOT
    campaignctl.ROOT = copied
    campaignctl.BASE_FDF = copied / "inputs/base/M1_U0_FM.pilot.NO_PRODUCTION.fdf"
    campaignctl.profilectl.ROOT = copied
    try:
        evidence = copied / "site/evidence/unit/evidence.txt"
        evidence.parent.mkdir(parents=True)
        evidence.write_text("SIESTA 5.4.2 hydra ssh sbatch test-only\n", encoding="utf-8")
        profile = json.loads(
            (copied / "profiles/yoltla_qz2d_128p.template.json").read_text()
        )
        profile["profile_status"] = profilectl.PRODUCTION
        profile["runtime"]["launcher"]["remote_validation_status"] = "VERIFIED"
        profile["resource_layouts"]["selection_status"] = "HUMAN_ACCEPTED"
        profile["evidence_sha256"] = {
            "site/evidence/unit/evidence.txt": sha(evidence)
        }
        profile_path = copied / "site/profiles/yoltla.json"
        profile_path.parent.mkdir(parents=True)
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        decisions = copied / "gates/decisions"
        decisions.mkdir(parents=True, exist_ok=True)
        for gate_id in ("F0_EXECUTION_AUTHORIZATION", "RESOURCE_LAYOUT_ACCEPTED"):
            gate_evidence = {
                "site/evidence/unit/evidence.txt": sha(evidence)
            }
            gate_extra = {}
            if gate_id == "F0_EXECUTION_AUTHORIZATION":
                bound = [
                    copied / "inputs/base/M1_U0_FM.pilot.NO_PRODUCTION.fdf",
                    copied / "external/pseudopotentials/Mn.psml",
                    copied / "external/pseudopotentials/O.psml",
                    copied / "scripts/runtime_preflight.py",
                    copied / "scripts/profilectl.py",
                    profile_path,
                ]
                gate_evidence.update(
                    {
                        item.relative_to(copied).as_posix(): sha(item)
                        for item in bound
                    }
                )
                gate_extra = {
                    "authorized_scope": "01_sanity_03a_mesh",
                    "output_directory": str(copied / "generated"),
                }
            gate = {
                "schema_version": "1.0",
                "gate_id": gate_id,
                "decision": "ACCEPTED",
                "accepted_by": "UNIT_TEST",
                "accepted_at": "2026-07-26T00:00:00Z",
                "evidence_sha256": gate_evidence,
                **gate_extra,
            }
            (decisions / f"{gate_id}.json").write_text(
                json.dumps(gate), encoding="utf-8"
            )
        result = campaignctl.prepare("01_sanity_03a_mesh", profile_path)
        yield copied, profile_path, result
    finally:
        campaignctl.ROOT = old_root
        campaignctl.BASE_FDF = old_base
        campaignctl.profilectl.ROOT = old_profile_root


class PackageTests(unittest.TestCase):
    def test_scientific_structure_and_packaged_pseudos(self):
        result = campaignctl.verify(True)
        self.assertEqual(result["package_id"], campaignctl.PACKAGE_ID)
        self.assertTrue(result["pseudopotentials_packaged_and_verified"])
        self.assertEqual(campaignctl.verify_pseudos(), campaignctl.PSEUDO_HASHES)

    def test_walltime_positive_and_negative_forms(self):
        self.assertEqual(parse_slurm_walltime("12:34:56"), 45296)
        self.assertEqual(parse_slurm_walltime("128:00:00"), 460800)
        self.assertEqual(parse_slurm_walltime("2-00:00:00"), 172800)
        self.assertEqual(canonical_slurm_walltime("48:00:00"), "2-00:00:00")
        for invalid in ("", "2-24:00:00", "01:60:00", "01:00:60", "abc"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_slurm_walltime(invalid)

    def test_qz_profile_exact_request_and_memory_policy(self):
        profile = profilectl.validate(
            ROOT / "profiles/yoltla_qz2d_128p.template.json"
        )
        self.assertEqual(profile["slurm"]["partition"], "qz2d-128p")
        self.assertEqual(profile["resources"]["nodes"], 2)
        self.assertEqual(profile["resources"]["total_cpus"], 80)
        self.assertEqual(profile["resources"]["tasks_per_node"], 40)
        self.assertEqual(profile["resources"]["walltime"], "2-00:00:00")
        self.assertEqual(
            profile["resources"]["memory_policy"]["mode"], "partition_default"
        )

    def test_siesta_version_exact_mismatch_missing_and_unexpected(self):
        with mock.patch.object(profilectl.shutil, "which", return_value="/x/siesta"):
            with mock.patch.object(
                profilectl.subprocess,
                "run",
                return_value=FakeCompleted("SIESTA version 5.4.2"),
            ):
                self.assertEqual(profilectl.check_siesta_version("siesta"), "5.4.2")
            with mock.patch.object(
                profilectl.subprocess,
                "run",
                return_value=FakeCompleted("SIESTA version 5.4.1"),
            ), self.assertRaises(profilectl.ProfileError):
                profilectl.check_siesta_version("siesta")
            with mock.patch.object(
                profilectl.subprocess,
                "run",
                return_value=FakeCompleted("unknown output"),
            ), self.assertRaises(profilectl.ProfileError):
                profilectl.check_siesta_version("siesta")
        with mock.patch.object(profilectl.shutil, "which", return_value=None):
            with self.assertRaises(profilectl.ProfileError):
                profilectl.check_siesta_version("siesta")

    def test_resource_layouts_are_non_overlapping_80_2x40_4x20(self):
        for count, mpi, nodes in ((1, 80, 2), (2, 40, 1), (4, 20, 1)):
            manager = ResourceManager(("n1", "n2"), 40)
            reservations = []
            for index in range(count):
                item = manager.reserve(f"t{index}", mpi, nodes)
                self.assertIsNotNone(item)
                reservations.append(item)
            owners = manager.snapshot()["owners"]
            self.assertEqual(
                sum(slot is not None for slots in owners.values() for slot in slots),
                80,
            )

    def test_srun_and_hydra_commands_are_explicit_and_hydra_slurm_forbidden(self):
        manager = ResourceManager(("n1", "n2"), 40)
        reservation = manager.reserve("task", 40, 1)
        assert reservation is not None
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            spec = StepLaunchSpec(
                "task",
                "attempt-1",
                work,
                work / "input.fdf",
                work / "out",
                work / "err",
                40,
                1,
                "siesta",
                reservation=reservation,
            )
            srun = SrunLauncher(srun_command=["srun"])
            command = srun.build_command(spec)
            self.assertIn("--ntasks=40", command)
            self.assertIn("--ntasks-per-node=40", command)
            self.assertIn("--nodelist=n1", command)
            hydra = HydraSshLauncher(
                hydra_command=["mpiexec.hydra"], bootstrap="ssh"
            )
            hcommand = hydra.build_command(spec)
            self.assertEqual(hcommand[hcommand.index("-bootstrap") + 1], "ssh")
            hostfile = Path(hcommand[hcommand.index("-f") + 1])
            self.assertEqual(hostfile.read_text(encoding="utf-8"), "n1:40\n")
            with self.assertRaises(ValueError):
                HydraSshLauncher(
                    hydra_command=["mpiexec.hydra"], bootstrap="slurm"
                )

    def test_retry_occurs_inside_same_allocation_and_persists_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, launcher = controller_fixture(root, [124, 0])
            result = controller.run(install_signal_handlers=False)
            self.assertEqual(result, ExecutionStatus.COMPLETED)
            self.assertEqual(launcher.calls, 2)
            self.assertTrue((root / "work/task/attempt-0001").is_dir())
            self.assertTrue((root / "work/task/attempt-0002").is_dir())
            state = json.loads(
                (root / "state/campaign_state.json").read_text(encoding="utf-8")
            )["payload"]
            self.assertEqual(state["tasks"]["task"]["attempts"], 2)

    def test_deterministic_terminal_error_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, launcher = controller_fixture(root, [7])
            self.assertEqual(
                controller.run(install_signal_handlers=False),
                ExecutionStatus.FAILED_TERMINAL,
            )
            self.assertEqual(launcher.calls, 1)

    def test_walltime_margin_stops_launch_and_is_resumable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, launcher = controller_fixture(root, [0], end_seconds=0.1)
            self.assertEqual(
                controller.run(install_signal_handlers=False),
                ExecutionStatus.INTERRUPTED,
            )
            self.assertEqual(launcher.calls, 0)
            self.assertTrue((root / "state/campaign_state.json").is_file())
            self.assertTrue((root / "results/campaign_summary.json").is_file())

    def test_materialization_is_deterministic_and_provenance_unique(self):
        base = campaignctl.BASE_FDF.read_text(encoding="utf-8")
        task = {
            "task_id": "mesh-250",
            "system_label": "MESH_250",
            "mesh_ry": 250,
            "kgrid": [3, 3, 1],
        }
        first = campaignctl.materialize_fdf(base, task, {})
        second = campaignctl.materialize_fdf(first, task, {})
        self.assertEqual(first, second)
        self.assertEqual(first.count("# generation_policy="), 1)
        self.assertNotIn("generated_at", first)

    def test_runtime_preflight_fails_closed_without_loaded_module(self):
        profile = json.loads(
            (ROOT / "profiles/yoltla_qz2d_128p.template.json").read_text()
        )
        profile["profile_status"] = profilectl.PRODUCTION
        profile["runtime"]["launcher"]["remote_validation_status"] = "VERIFIED"
        profile["resource_layouts"]["selection_status"] = "HUMAN_ACCEPTED"
        profile["evidence_sha256"] = {"missing": "0" * 64}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaises(runtime_preflight.PreflightError):
                runtime_preflight.preflight(path, Path(directory))

    def test_site_profile_prepare_bundle_guard_and_submit_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            with prepared_package_copy(Path(directory)) as (copied, profile, result):
                self.assertEqual(result["tasks"], 5)
                guard = json.loads(
                    (copied / "generated/01_sanity_03a_mesh/launch_guard.json").read_text()
                )
                self.assertEqual(guard["profile_sha256"], sha(profile))
                controller = json.loads(
                    (copied / "generated/01_sanity_03a_mesh/controller.json").read_text()
                )
                self.assertEqual(
                    controller["tasks"][1]["depends_on"], ["m1-u0-fm-sanity"]
                )
                self.assertEqual(
                    controller["tasks"][0]["postcondition"],
                    "m1_sanity_automatic_technical_v1",
                )
                submit = (
                    copied / "generated/01_sanity_03a_mesh/submit.slurm"
                ).read_text()
                self.assertIn("#SBATCH --nodes=2", submit)
                self.assertIn("#SBATCH --ntasks=80", submit)
                self.assertIn("#SBATCH --ntasks-per-node=40", submit)
                self.assertIn("#SBATCH --time=2-00:00:00", submit)
                self.assertNotRegex(submit, r"(?m)^#SBATCH --mem=")
                self.assertIn("scripts/runtime_preflight.py", submit)
                self.assertNotRegex(submit, r"(?m)^\s*sbatch\b")
                check = campaignctl.check_run(
                    "01_sanity_03a_mesh",
                    profile,
                    copied / "generated/01_sanity_03a_mesh",
                )
                self.assertIn("RUN_GUARDS_PASS", check["status"])

    def test_profile_gate_and_pseudo_tamper_are_detected_after_prepare(self):
        with tempfile.TemporaryDirectory() as directory:
            with prepared_package_copy(Path(directory)) as (copied, profile, _):
                prepared = copied / "generated/01_sanity_03a_mesh"
                data = json.loads(profile.read_text())
                data["accepted_by"] = "CHANGED_AFTER_MATERIALIZATION"
                profile.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(campaignctl.CampaignError):
                    campaignctl.check_run("01_sanity_03a_mesh", profile, prepared)

        with tempfile.TemporaryDirectory() as directory:
            with prepared_package_copy(Path(directory)) as (copied, profile, _):
                prepared = copied / "generated/01_sanity_03a_mesh"
                gate_path = copied / "gates/decisions/RESOURCE_LAYOUT_ACCEPTED.json"
                gate = json.loads(gate_path.read_text())
                gate["accepted_at"] = "2026-07-26T00:00:01Z"
                gate_path.write_text(json.dumps(gate), encoding="utf-8")
                with self.assertRaises(campaignctl.CampaignError):
                    campaignctl.check_run("01_sanity_03a_mesh", profile, prepared)

        with tempfile.TemporaryDirectory() as directory:
            with prepared_package_copy(Path(directory)) as (copied, profile, _):
                prepared = copied / "generated/01_sanity_03a_mesh"
                (prepared / "pseudopotentials/Mn.psml").write_text("tampered")
                with self.assertRaises(campaignctl.CampaignError):
                    campaignctl.check_run("01_sanity_03a_mesh", profile, prepared)

    def test_scientifically_undefined_phase_remains_blocked(self):
        with self.assertRaises(campaignctl.CampaignError) as context:
            campaignctl.prepare(
                "04_u_spin", ROOT / "site/profiles/nonexistent.json"
            )
        self.assertIn("BLOCKED_BY_DESIGN", str(context.exception))

    def test_verifier_allows_site_profile_but_rejects_immutable_profile_injection(self):
        if not (ROOT / "manifest.json").is_file():
            self.skipTest("manifest is generated only at final packaging")
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / ROOT.name
            shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            mutable_profile = copied / "site/profiles/runtime.json"
            mutable_profile.parent.mkdir(parents=True)
            mutable_profile.write_text("{}\n")
            passed = subprocess.run(
                [sys.executable, "verify_package.py"],
                cwd=copied,
                capture_output=True,
                text=True,
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            (copied / "profiles/unmanifested.json").write_text("{}\n")
            failed = subprocess.run(
                [sys.executable, "verify_package.py"],
                cwd=copied,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("IMMUTABLE_COVERAGE_MISMATCH", failed.stderr + failed.stdout)

    def test_no_automatic_sbatch_submission(self):
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".sh", ".slurm"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotRegex(
                text,
                r"(?m)^\s*sbatch\s+(?!--test-only)",
                path.as_posix(),
            )
        self.assertIn(
            "sbatch --test-only",
            (ROOT / "scripts/capture_site_evidence.sh").read_text(),
        )

    def test_mutable_site_profiles_and_immutable_profiles_policy(self):
        self.assertTrue(verifier.mutable(PurePosixPath("site/profiles/new.json")))
        self.assertFalse(verifier.mutable(PurePosixPath("profiles/new.json")))
        self.assertFalse(
            verifier.mutable(PurePosixPath("external/pseudopotentials/Mn.psml"))
        )

    def test_parent_geometry_dependencies_remain_registered(self):
        deps = geometry_transfer.ADSORPTION_DEPENDENCIES
        self.assertEqual(deps["ADSORB_M1_Ca8w_OS_v01"][2], 54)
        self.assertEqual(deps["ADSORB_M1_Mg6w_OS_v01"][2], 54)


if __name__ == "__main__":
    unittest.main()
