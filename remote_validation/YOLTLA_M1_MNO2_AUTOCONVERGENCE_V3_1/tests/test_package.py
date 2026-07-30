from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/automatic_campaign.py"
SPEC = importlib.util.spec_from_file_location("automatic_campaign_tests", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
campaign = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = campaign
SPEC.loader.exec_module(campaign)


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = campaign.load_config(ROOT / "campaign.json")
        cls.base = (ROOT / cls.config["system"]["base_fdf"]).read_text(
            encoding="utf-8"
        )

    def test_exact_full_yoltla_allocation(self):
        slurm = self.config["slurm"]
        self.assertEqual(slurm["partition"], "qz2d-128p")
        self.assertEqual(slurm["nodes"], 2)
        self.assertEqual(slurm["ntasks"], 128)
        self.assertEqual(slurm["ntasks_per_node"], 64)
        submit = (ROOT / "submit.slurm").read_text(encoding="utf-8")
        for line in (
            "#SBATCH --nodes=2",
            "#SBATCH --ntasks=128",
            "#SBATCH --ntasks-per-node=64",
            "module load python/3.12",
        ):
            self.assertIn(line, submit)
        self.assertNotIn("dual_40", submit)
        self.assertNotIn("quad_20", submit)

    def test_static_input_and_pseudopotential_contract(self):
        hashes = campaign.validate_static_files(self.config)
        self.assertEqual(
            hashes["external/pseudopotentials/Mn.psml"],
            "0b97ccd71456e4a7b28316f78ddb30bb1f6a82d9aba386c7fde78090d31c0dc6",
        )
        self.assertEqual(
            hashes["external/pseudopotentials/O.psml"],
            "224ded5c59176d9bcb76d19b7a4a68a48d5dffabf8b262f64d5760250e87c35e",
        )

    def test_mesh_and_kgrid_materialization(self):
        variant = campaign.Variant("mesh_test", "01_mesh", 300, (4, 4, 1))
        text = campaign.render_fdf(self.base, self.config, variant)
        self.assertRegex(text, r"(?m)^Mesh\.Cutoff 300 Ry$")
        self.assertIn("  4 0 0 0.0", text)
        self.assertIn("  0 4 0 0.0", text)
        self.assertIn("  0 0 1 0.0", text)
        self.assertRegex(text, r"(?m)^MD\.Steps 0$")
        self.assertRegex(text, r"(?m)^NetCharge 0$")

    def test_explicit_triple_zeta_preserves_mn_semicore_shells(self):
        variant = campaign.Variant(
            "tzp_test", "03_basis", 350, (4, 4, 1), "EXPLICIT_TZP"
        )
        text = campaign.render_fdf(self.base, self.config, variant)
        self.assertIn("%block PAO.Basis", text)
        self.assertIn("Mn 4", text)
        for shell in ("n=3 0 3", "n=3 1 3", "n=3 2 3 P 1", "n=4 0 3"):
            self.assertIn(shell, text)
        self.assertIn("O 2", text)
        self.assertNotRegex(text, r"(?im)^\s*PAO\.BasisSize\s+TZP\b")
        self.assertNotRegex(text, r"(?im)^\s*PAO\.BasisSize\s+DZP\b")

    def test_dftu_uses_documented_v542_dudarev_convention(self):
        variant = campaign.Variant(
            "u4_test", "04_u_spin", 350, (4, 4, 1), "DZP", 4.0, "FM"
        )
        text = campaign.render_fdf(self.base, self.config, variant)
        self.assertIn("DFTU.ProjectorGenerationMethod 2", text)
        self.assertIn("DFTU.CutoffNorm 0.900000", text)
        self.assertIn("n=3 2", text)
        self.assertIn("4.000000 0.000000", text)
        self.assertIn("0.000000 0.000000", text)
        self.assertNotIn("LDAU.ProjectorGenerationMethod", text)

    def test_stripe_afm_partition_matches_only_mn_indices(self):
        variant = campaign.Variant(
            "stripe_test",
            "04_u_spin",
            350,
            (4, 4, 1),
            "DZP",
            3.8,
            "STRIPE_AFM",
        )
        text = campaign.render_fdf(self.base, self.config, variant)
        block = re.search(
            r"(?is)%block DM\.InitSpin(.*?)%endblock DM\.InitSpin", text
        )
        self.assertIsNotNone(block)
        signed = {
            int(index): token
            for index, token in re.findall(r"(?m)^\s*(\d+)\s+([+-])\s*$", block.group(1))
        }
        self.assertEqual(
            {index for index, token in signed.items() if token == "+"},
            set(self.config["magnetism"]["stripe_plus_indices"]),
        )
        self.assertEqual(
            {index for index, token in signed.items() if token == "-"},
            set(self.config["magnetism"]["stripe_minus_indices"]),
        )

    def test_plateau_selection_requires_all_later_increments_to_pass(self):
        selected, deltas = campaign.select_plateau(
            [(200, -100.0), (250, -100.2), (300, -100.201), (350, -100.202)],
            2.0,
            54,
        )
        self.assertEqual(selected, 300)
        self.assertEqual(len(deltas), 3)
        failed, _ = campaign.select_plateau(
            [(200, -100.0), (250, -100.2), (300, -100.4), (350, -100.6)],
            2.0,
            54,
        )
        self.assertIsNone(failed)

    def test_realistic_siesta_output_parser(self):
        sample = """SIESTA started
        iscf Eharris(eV) E_KS(eV)
SCF Convergence by DM+H criterion
SCF cycle converged after 17 iterations
siesta: Etot    =    -1234.567800
siesta: Edftu   =        0.123400
siesta: E_KS(eV) = -1234.5678
siesta: Final energy (eV):
siesta:         Total =   -1234.567800
Mulliken spin population Sz
>> End of run:  26-JUL-2026  11:48:31
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / "siesta.out"
            err = root / "siesta.err"
            out.write_text(sample, encoding="utf-8")
            err.write_text("", encoding="utf-8")
            result = campaign.parse_siesta_output(out, err, 0)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["energy_ev"], -1234.5678)
        self.assertEqual(result["edftu_ev"], 0.1234)
        self.assertEqual(result["scf_iterations"], 17)
        self.assertTrue(result["spin_evidence_lines"])

    def test_attempt_directories_are_never_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_name, first = campaign.next_attempt(root)
            second_name, second = campaign.next_attempt(root)
        self.assertEqual(first_name, "attempt-0001")
        self.assertEqual(second_name, "attempt-0002")
        self.assertNotEqual(first, second)

    def test_scope_contains_no_relaxation_or_electronic_postprocessing(self):
        self.assertEqual(
            self.config["scope"], "STATIC_NUMERICAL_BASIS_AND_U_SPIN_TESTS_ONLY"
        )
        self.assertNotIn("relax", json.dumps(self.config).casefold())
        self.assertNotIn("dos", json.dumps(self.config).casefold())

    def test_u_policy_forbids_cross_u_energy_ranking(self):
        magnetic = self.config["magnetism"]
        self.assertTrue(magnetic["cross_U_energy_ranking_forbidden"])
        self.assertEqual(
            magnetic["selection_rule"],
            "select_lower_energy_state_within_each_equal_U_only",
        )

    def test_complete_automatic_chain_and_reference_reuse(self):
        calls = []

        def fake_run(_config, _root, _events, _base, variant):
            calls.append(variant.task_id)
            if variant.stage == "01_mesh":
                energies = {
                    200: -100.000,
                    250: -100.200,
                    300: -100.201,
                    350: -100.202,
                }
                energy = energies[variant.mesh_ry]
            elif variant.stage == "02_kgrid":
                energies = {
                    (2, 2, 1): -200.000,
                    (3, 3, 1): -200.200,
                    (4, 4, 1): -200.201,
                    (5, 5, 1): -200.202,
                }
                energy = energies[variant.kgrid]
            elif variant.stage == "03_basis":
                energy = -200.250
            else:
                offsets = {
                    (3.8, "FM"): -300.000,
                    (3.8, "STRIPE_AFM"): -300.200,
                    (4.0, "FM"): -301.000,
                    (4.0, "STRIPE_AFM"): -301.180,
                }
                energy = offsets[(variant.ueff_ev, variant.magnetic_state)]
            return {
                "status": "PASS",
                "energy_ev": energy,
                "scf_iterations": 12,
                "elapsed_seconds": 1.0,
                "input_sha256": "a" * 64,
            }

        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            campaign, "remote_preflight", return_value=None
        ), mock.patch.object(campaign, "run_variant", side_effect=fake_run):
            final = campaign.run_campaign(self.config, Path(directory))
            basis = json.loads(
                (Path(directory) / final["decisions"]["basis"]).read_text(
                    encoding="utf-8"
                )
            )
            u_spin = json.loads(
                (Path(directory) / final["decisions"]["u_spin"]).read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(len(calls), 12)
        self.assertNotIn("kgrid_5x5x1", calls)
        self.assertEqual(final["selected_mesh_ry"], 300)
        self.assertEqual(final["selected_kgrid"], [4, 4, 1])
        self.assertEqual(basis["selected_basis"], "DZP")
        self.assertEqual(final["status"], "PASS_ROBUST")
        self.assertEqual(u_spin["selected_magnetic_order"], "STRIPE_AFM")


if __name__ == "__main__":
    unittest.main()
