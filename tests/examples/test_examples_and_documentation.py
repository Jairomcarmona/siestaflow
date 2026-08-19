from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from qraft.cli import build_parser
from qraft.examples import ExampleRegistry, ExampleService, public_api_contract


REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples"


def _commands(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    result: set[tuple[str, ...]] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                command = prefix + (name,)
                result.add(command)
                result.update(_commands(child, command))
    return result


def test_cli_reference_matches_implemented_command_tree():
    implemented = _commands(build_parser())
    documented = {
        ("environment", "check"),
        ("project", "init"), ("project", "inspect"), ("project", "validate"), ("project", "load"),
        ("fdf", "inspect"), ("input", "validate"), ("input", "rules"), ("pseudo", "verify"),
        ("campaign", "create"), ("campaign", "validate"), ("campaign", "simulate"), ("campaign", "status"),
        ("examples", "list"), ("examples", "inspect"), ("examples", "validate"), ("examples", "stage"),
        ("examples", "package"), ("examples", "run"), ("examples", "results", "import"),
        ("remote", "package"), ("remote", "results", "import"),
        ("remote", "environment", "package"), ("remote", "environment", "import"),
        ("workflow", "validate"), ("workflow", "preflight"), ("workflow", "plan"),
        ("workflow", "graph"), ("workflow", "compile"),
    }
    text = (REPO / "docs" / "user" / "CLI_REFERENCE.md").read_text(encoding="utf-8")
    assert documented <= implemented
    assert not [command for command in documented if " ".join(command) not in text]
    assert public_api_contract()["operations"] == ["list", "inspect", "validate", "stage", "package", "results import", "run"]


def test_all_required_documentation_and_primary_links_exist():
    required = (
        "README.md", "CHANGELOG.md", "CONTRIBUTING.md",
        "docs/user/USER_MANUAL.md", "docs/user/INSTALLATION.md", "docs/user/QUICK_START.md",
        "docs/user/CLI_REFERENCE.md", "docs/user/TROUBLESHOOTING.md",
        "docs/user/SIESTA_VALIDATION_GUIDE.md",
        "docs/operations/YOLTLA_RUNBOOK.md", "docs/operations/REMOTE_VALIDATION_WORKFLOW.md",
        "docs/operations/RECOVERY_AND_RESUME.md", "docs/scientific/SCIENTIFIC_GOVERNANCE.md",
        "docs/scientific/CAMPAIGN_GATES.md", "docs/developer/DEVELOPER_GUIDE.md",
        "docs/developer/ARCHITECTURE.md", "docs/developer/TESTING.md",
        "docs/validation/PHASE6_VALIDATION_FOUNDATION_ACCEPTANCE.md",
    )
    assert not [name for name in required if not (REPO / name).is_file()]
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for target in ("docs/user/USER_MANUAL.md", "docs/user/CLI_REFERENCE.md", "docs/operations/YOLTLA_RUNBOOK.md"):
        assert target in readme and (REPO / target).is_file()
    governance = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for target in ("CLI_REFERENCE.md", "USER_MANUAL.md", "YOLTLA_RUNBOOK.md", "SCIENTIFIC_GOVERNANCE.md", "CHANGELOG.md"):
        assert target in governance


def test_example_packages_inspect_validate_and_have_example_contracts():
    registry = ExampleRegistry((EXAMPLES,))
    service = ExampleService(registry)
    found = registry.list()
    assert {name for name, _ in found} == {"generic/minimal_siesta_smoke", "reference_projects/birnessite_mn_o"}
    for name, path in found:
        assert (path / "example.yaml").is_file()
        assert service.validate(name).valid
        assert service.inspect(name)["execution_claim"] == "INSPECTION_ONLY"


def test_example_staging_blocks_missing_hash_and_dry_run_has_no_effect(tmp_path: Path):
    service = ExampleService(ExampleRegistry((EXAMPLES,)))
    missing_destination = tmp_path / "missing"
    missing = service.stage("generic/minimal_siesta_smoke", tmp_path / "none", missing_destination, policy="copy", dry_run=True)
    assert missing.example_status == "EXAMPLE_BLOCKED_MISSING_PSEUDOS"
    assert not missing_destination.exists()

    pseudo_root = tmp_path / "pseudos"
    pseudo_root.mkdir()
    (pseudo_root / "X.psml").write_text("<psml>wrong hash</psml>\n", encoding="utf-8")
    (pseudo_root / "Y.psml").write_text("<psml>wrong hash</psml>\n", encoding="utf-8")
    mismatch = service.stage("generic/minimal_siesta_smoke", pseudo_root, tmp_path / "mismatch", policy="copy", dry_run=True)
    assert mismatch.example_status == "EXAMPLE_BLOCKED_HASH_MISMATCH"
    assert not (tmp_path / "mismatch").exists()


def test_example_archive_is_reproducible_and_package_dry_run_is_clean(tmp_path: Path):
    service = ExampleService(ExampleRegistry((EXAMPLES,)))
    dry_root = tmp_path / "dry"
    report = service.package("generic/minimal_siesta_smoke", dry_root, dry_run=True)
    assert report["dry_run"] and not dry_root.exists()
    first = service.package("generic/minimal_siesta_smoke", tmp_path / "one")
    second = service.package("generic/minimal_siesta_smoke", tmp_path / "two")
    assert Path(first["archive"]).read_bytes() == Path(second["archive"]).read_bytes()


def test_cli_help_and_documented_examples_are_executable(tmp_path: Path):
    env = os.environ.copy(); env["PYTHONPATH"] = str(REPO / "src")
    commands = (
        ["--help"], ["project", "--help"], ["campaign", "create", "--help"],
        ["examples", "stage", "--help"], ["remote", "environment", "package", "--help"],
    )
    for command in commands:
        result = subprocess.run([sys.executable, "-m", "qraft.cli", *command], cwd=REPO, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    validate = subprocess.run(
        [sys.executable, "-m", "qraft.cli", "examples", "validate", "generic/minimal_siesta_smoke", "--json"],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=30,
    )
    assert validate.returncode == 0 and '"valid": true' in validate.stdout
