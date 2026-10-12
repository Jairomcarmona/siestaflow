"""Compare packages against the real pinned builder, never frozen old runtime."""

from io import BytesIO
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest

from qraft.controller_package import ControllerPackageBuilder
from qraft.execution.allocation_controller_compat import load_controller_config
from qraft.execution.legacy_translation import translate_controller_config


ROOT = Path(__file__).parents[2]
BASELINE = "41043edcabef39026fe3cb6b7776362695faf9c6"


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


compare = module(ROOT / "tools/compare_controller_packages.py", "package_comparator").compare_packages


@pytest.fixture(scope="module")
def packages(tmp_path_factory):
    temp = tmp_path_factory.mktemp("actual-pinned-packages")
    archive = subprocess.run(["git", "archive", "--format=zip", BASELINE], cwd=ROOT, capture_output=True)
    if archive.returncode:
        if __import__("os").environ.get("GITHUB_ACTIONS") == "true":
            pytest.fail("checkout must fetch the pinned baseline for the package regression gate")
        pytest.skip("pinned Git history unavailable in this external consumer copy")
    baseline = temp / "baseline"
    baseline.mkdir()
    with ZipFile(BytesIO(archive.stdout)) as zipped:
        zipped.extractall(baseline)
    fixture = module(ROOT / "tests/m4/test_controller_package.py", "package_fixture")
    source = temp / "source"
    source.mkdir()
    campaign = fixture.source_campaign(source)
    data = json.loads(campaign.read_bytes())
    gate = dict(data["tasks"][0], task_id="gate", kind="gate", command=["synthetic-never-executed"],
                mpi_processes=1, nodes=0, require_scf_converged=False)
    data["tasks"].append(gate)
    campaign.write_bytes((json.dumps(data, indent=2) + "\n").encode())
    provenance = {}
    for name in ("workflow.lock.json", "run.lock.json", "execution-profile.json"):
        path = source / name
        path.write_bytes(b'{"synthetic_comparator":"fixed-materialized-input"}\n')
        provenance[name] = path
    old_out, new_out = temp / "old", temp / "new"
    old_out.mkdir()
    new_out.mkdir()
    script = temp / "old_builder.py"
    script.write_text(
        "import sys,json\nfrom pathlib import Path\n"
        "sys.path.insert(0,sys.argv[1])\n"
        "from qraft.controller_package import ControllerPackageBuilder\n"
        "source=Path(sys.argv[2])\n"
        "result=ControllerPackageBuilder(Path(sys.argv[1]).parent).build("
        "source/'campaign.json',Path(sys.argv[3]),"
        "provenance_files={name:source/name for name in ('workflow.lock.json','run.lock.json','execution-profile.json')})\n"
        "from qraft.execution.allocation_controller_compat import load_controller_config\n"
        "from qraft.execution.legacy_translation import translate_controller_config\n"
        "plan=translate_controller_config(load_controller_config(source/'campaign.json'),root=source)\n"
        "print(json.dumps({'zip':result.zip_path,'workflow':plan.workflow.payload(),"
        "'scientific':{key:value.fingerprint for key,value in plan.scientific_identities.items()},"
        "'execution':{key:value.fingerprint for key,value in plan.execution_specs.items()}}))\n", encoding="utf-8")
    old = subprocess.run([sys.executable, "-I", str(script), str(baseline / "src"), str(source), str(old_out)],
                         cwd=temp, capture_output=True, text=True)
    assert old.returncode == 0, old.stderr
    new = ControllerPackageBuilder(ROOT).build(campaign, new_out, provenance_files=provenance)
    report = json.loads(old.stdout)
    plan = translate_controller_config(load_controller_config(campaign), root=source)
    assert report["workflow"] == plan.workflow.payload()
    assert report["scientific"] == {key: value.fingerprint for key, value in plan.scientific_identities.items()}
    assert report["execution"] == {key: value.fingerprint for key, value in plan.execution_specs.items()}
    return Path(report["zip"]), Path(new.zip_path), temp


def test_real_baseline_preserves_all_non_runtime_bytes_and_verifies_new_hashes(packages):
    old, new, _ = packages
    result = compare(old, new)
    assert result["all_hashes_verified"] and result["runtime_changes"]
    assert result["old_zip_sha256"] != result["new_zip_sha256"]


def altered(package, target, destination, *, rehash=False):
    from hashlib import sha256
    with ZipFile(package) as archive:
        entries = [(entry, archive.read(entry)) for entry in archive.infolist()]
    prefix = entries[0][0].filename.split("/", 1)[0] + "/"
    files = {entry.filename.removeprefix(prefix): content for entry, content in entries}
    files[target] += b"\ncorruption\n"
    if rehash:
        manifest = json.loads(files["manifest.json"])
        manifest["immutable_files"][target] = sha256(files[target]).hexdigest()
        files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        files["checksums.sha256"] = "".join(f"{sha256(content).hexdigest()}  {name}\n"
            for name, content in sorted(files.items()) if name != "checksums.sha256").encode()
    with ZipFile(destination, "w") as archive:
        for entry, _ in entries:
            archive.writestr(entry, files[entry.filename.removeprefix(prefix)])
    return destination


@pytest.mark.parametrize("target", ["input/run.fdf", "campaign.yaml", "workflow.lock.json", "submit.slurm"])
def test_comparator_rejects_even_consistently_rehashed_scientific_and_package_changes(packages, target):
    old, new, temp = packages
    with pytest.raises(ValueError, match="non-runtime bytes changed"):
        compare(old, altered(new, target, temp / (target.replace("/", "-") + ".zip"), rehash=True))


def test_comparator_verifies_runtime_hash_instead_of_waiving_it(packages):
    old, new, temp = packages
    with pytest.raises(ValueError, match="immutable hash mismatch"):
        compare(old, altered(new, "runtime/qraft/execution/capability_runtime.py", temp / "runtime-corrupt.zip"))


def test_comparator_rejects_checksum_hash_corruption(packages):
    old, new, temp = packages
    with pytest.raises(ValueError, match="invalid checksum line"):
        compare(old, altered(new, "checksums.sha256", temp / "checksums-corrupt.zip"))


@pytest.mark.parametrize("case", ["duplicate", "unsafe", "missing", "extra", "permissions", "date", "manifest-field"])
def test_comparator_rejects_inventory_or_non_derived_metadata_changes(packages, case):
    from copy import copy
    from hashlib import sha256
    old, new, temp = packages
    with ZipFile(new) as archive:
        entries = [(copy(entry), archive.read(entry)) for entry in archive.infolist()]
    prefix = entries[0][0].filename.split("/", 1)[0] + "/"
    destination = temp / (case + ".zip")
    with ZipFile(destination, "w") as archive:
        for entry, data in entries:
            name = entry.filename.removeprefix(prefix)
            if name == "submit.slurm" and case == "permissions":
                entry.external_attr ^= 0o100 << 16
            if name == "submit.slurm" and case == "date":
                entry.date_time = (2001, 1, 1, 0, 0, 0)
            if name == "checksums.sha256":
                if case == "missing":
                    data = b"\n".join(data.splitlines()[1:]) + b"\n"
                elif case == "extra":
                    data += b"0" * 64 + b"  nonexistent.file\n"
                elif case == "manifest-field":
                    changed = json.loads(next(content for info, content in entries if info.filename == prefix + "manifest.json"))
                    changed["login_node_persistent_process_required"] = True
                    manifest_bytes = (json.dumps(changed, indent=2, sort_keys=True) + "\n").encode()
                    data = b"\n".join((sha256(manifest_bytes).hexdigest() + "  manifest.json").encode()
                        if line.endswith(b"  manifest.json") else line for line in data.splitlines()) + b"\n"
            if name == "manifest.json" and case == "manifest-field":
                changed = json.loads(data)
                changed["login_node_persistent_process_required"] = True
                data = (json.dumps(changed, indent=2, sort_keys=True) + "\n").encode()
            archive.writestr(entry, data)
        if case == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr(entries[0][0], entries[0][1])
        elif case == "unsafe":
            archive.writestr(prefix + "../escape", b"unsafe")
    with pytest.raises(ValueError):
        compare(old, destination)
