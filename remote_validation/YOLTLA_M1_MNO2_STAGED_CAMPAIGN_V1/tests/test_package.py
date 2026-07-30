from __future__ import annotations

import importlib.util
import hashlib
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def module_from(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


campaignctl = module_from(ROOT / "scripts/campaignctl.py", "campaignctl_test")
geometry_transfer = module_from(
    ROOT / "scripts/geometry_transfer.py", "geometry_transfer_test"
)


class PackageTests(unittest.TestCase):
    def test_scientific_structure_verifies_without_external_assets(self):
        result = campaignctl.verify(False)
        self.assertEqual(result["status"], "PACKAGE_SCIENTIFIC_STRUCTURE_VERIFIED")
        self.assertEqual(result["phases"], 9)

    def test_mesh_materialization_changes_only_declared_numeric_identity(self):
        base = campaignctl.BASE_FDF.read_text(encoding="utf-8")
        for mesh in (200, 250, 300, 350):
            task = {
                "task_id": f"mesh-{mesh}",
                "system_label": f"MESH_{mesh}",
                "mesh_ry": mesh,
                "kgrid": [3, 3, 1],
            }
            output = campaignctl.materialize_fdf(base, task, {})
            self.assertEqual(
                len(re.findall(r"^\s*Mesh\.Cutoff\s+", output, re.I | re.M)), 1
            )
            self.assertRegex(output, rf"(?m)^Mesh\.Cutoff {mesh} Ry$")
            self.assertRegex(output, r"(?m)^MD\.Steps 0$")
            self.assertRegex(output, r"(?m)^NetCharge 0$")
            self.assertRegex(output, r"(?m)^  0 0 1 0\.0$")

    def test_kgrid_materialization_requires_signed_mesh_value(self):
        base = campaignctl.BASE_FDF.read_text(encoding="utf-8")
        task = {
            "task_id": "kgrid-4",
            "system_label": "KGRID_4",
            "kgrid": [4, 4, 1],
        }
        output = campaignctl.materialize_fdf(
            base, task, {"selected_mesh_ry": 300}
        )
        self.assertRegex(output, r"(?m)^Mesh\.Cutoff 300 Ry$")
        self.assertRegex(output, r"(?m)^  4 0 0 0\.0$")
        self.assertRegex(output, r"(?m)^  0 4 0 0\.0$")
        with self.assertRaises(campaignctl.CampaignError):
            campaignctl.materialize_fdf(base, task, {})

    def test_observed_profile_is_not_silently_promoted_to_production(self):
        profile = ROOT / "profiles/yoltla_observed_20c_1h.json"
        data = campaignctl.validate_profile(profile, require_production=False)
        self.assertNotEqual(data["profile_status"], campaignctl.PROFILE_READY)
        with self.assertRaises(campaignctl.CampaignError):
            campaignctl.validate_profile(profile, require_production=True)

    def test_m1_parent_contracts_are_registered(self):
        deps = geometry_transfer.ADSORPTION_DEPENDENCIES
        self.assertEqual(
            deps["ADSORB_M1_Ca8w_OS_v01"],
            (
                "M1_delta_MnO2_neutral_surface_control_v01",
                "ADS_Ca8w_v01",
                54,
            ),
        )
        self.assertEqual(
            deps["ADSORB_M1_Mg6w_OS_v01"],
            (
                "M1_delta_MnO2_neutral_surface_control_v01",
                "ADS_Mg6w_v01",
                54,
            ),
        )

    def test_every_graph_node_has_a_phase_file(self):
        graph = json.loads((ROOT / "campaign_graph.json").read_text(encoding="utf-8"))
        graph_ids = {item["id"] for item in graph["phases"]}
        files = {path.stem for path in (ROOT / "campaigns").glob("*.json")}
        self.assertEqual(graph_ids, files)

    def test_no_automatic_submission_code(self):
        for path in ROOT.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(
                text,
                r"subprocess\.(?:run|Popen)\s*\(\s*\[[^\]]*['\"]sbatch",
                path.as_posix(),
            )
        preflight = (ROOT / "scripts/preflight.sh").read_text(encoding="utf-8")
        self.assertIn("sbatch --test-only", preflight)
        self.assertNotRegex(preflight, r"(?m)^\s*sbatch\s+(?!--test-only)")

    def test_prepare_materializes_isolated_tasks_and_never_submits(self):
        original_root = campaignctl.ROOT
        original_base = campaignctl.BASE_FDF
        original_hashes = dict(campaignctl.PSEUDO_HASHES)
        with tempfile.TemporaryDirectory(prefix="m1-package-test-") as directory:
            copied = Path(directory) / ROOT.name
            shutil.copytree(ROOT, copied)
            campaignctl.ROOT = copied
            campaignctl.BASE_FDF = (
                copied / "inputs/base/M1_U0_FM.pilot.NO_PRODUCTION.fdf"
            )
            pseudo_dir = copied / "external/pseudopotentials"
            pseudo_hashes = {}
            for name in ("Mn.psml", "O.psml"):
                payload = f"synthetic-test-only-{name}\n".encode()
                (pseudo_dir / name).write_bytes(payload)
                pseudo_hashes[name] = hashlib.sha256(payload).hexdigest()
            campaignctl.PSEUDO_HASHES = pseudo_hashes

            evidence = copied / "tests/fixture_gate_evidence.txt"
            evidence.write_text("synthetic gate evidence\n", encoding="utf-8")
            decisions = copied / "gates/decisions"
            decisions.mkdir()
            gate = {
                "schema_version": "1.0",
                "gate_id": "F2_SANITY_ACCEPTED",
                "decision": "ACCEPTED",
                "accepted_by": "UNIT_TEST",
                "accepted_at": "2026-07-26T00:00:00Z",
                "evidence_sha256": {
                    "tests/fixture_gate_evidence.txt": campaignctl.sha256(evidence)
                },
            }
            (decisions / "F2_SANITY_ACCEPTED.json").write_text(
                json.dumps(gate), encoding="utf-8"
            )
            try:
                result = campaignctl.prepare(
                    "03a_mesh",
                    copied / "profiles/yoltla_observed_20c_1h.json",
                )
            finally:
                campaignctl.ROOT = original_root
                campaignctl.BASE_FDF = original_base
                campaignctl.PSEUDO_HASHES = original_hashes

            self.assertEqual(result["tasks"], 4)
            controller = json.loads(
                (copied / "generated/03a_mesh/controller.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(len(controller["tasks"]), 4)
            self.assertEqual(
                [task["task_id"] for task in controller["tasks"]],
                [
                    "m1-mesh-200ry",
                    "m1-mesh-250ry",
                    "m1-mesh-300ry",
                    "m1-mesh-350ry",
                ],
            )
            submit = (copied / "generated/03a_mesh/submit.slurm").read_text(
                encoding="utf-8"
            )
            self.assertIn("scripts/campaignctl.py\" check-run", submit)
            self.assertNotRegex(submit, r"(?m)^\s*sbatch\b")


if __name__ == "__main__":
    unittest.main()
