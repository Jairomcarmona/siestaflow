"""ADR-017 C.1: compare actual ZIP members, including all runtime hashes."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from zipfile import ZipFile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
            or ":" in name or "\x00" in name or path.as_posix() != name):
        raise ValueError("unsafe package member")
    return name


@dataclass
class Package:
    files: dict
    metadata: dict
    manifest: dict
    checksums: dict


def read_package(path):
    files, metadata = {}, {}
    with ZipFile(path) as archive:
        names = [entry.filename for entry in archive.infolist()]
        if len(names) != len(set(names)):
            raise ValueError("duplicate package member")
        for entry in archive.infolist():
            name = safe_name(entry.filename)
            if name in files or entry.is_dir():
                raise ValueError("duplicate or unexpected directory member")
            files[name] = archive.read(entry)
            metadata[name] = (entry.date_time, entry.external_attr, entry.create_system,
                              entry.internal_attr, entry.comment, entry.extra)
    prefixes = {name.split("/", 1)[0] for name in files}
    if len(prefixes) != 1 or any("/" not in name for name in files):
        raise ValueError("package must have one root")
    prefix = next(iter(prefixes)) + "/"
    files = {name.removeprefix(prefix): data for name, data in files.items()}
    metadata = {name.removeprefix(prefix): data for name, data in metadata.items()}
    manifest = json.loads(files["manifest.json"], object_pairs_hook=object_pairs)
    immutable = manifest["immutable_files"]
    if not isinstance(immutable, dict) or set(immutable) != set(files) - {"manifest.json", "checksums.sha256"}:
        raise ValueError("immutable inventory mismatch")
    for name, expected in immutable.items():
        safe_name(name)
        if digest(files[name]) != expected:
            raise ValueError("immutable hash mismatch: " + name)
    checksums = {}
    for line in files["checksums.sha256"].decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError("invalid checksum line")
        expected, name = match.groups()
        safe_name(name)
        if name in checksums:
            raise ValueError("duplicate checksum name")
        checksums[name] = expected
    if set(checksums) != set(files) - {"checksums.sha256"}:
        raise ValueError("checksum inventory mismatch")
    for name, expected in checksums.items():
        if digest(files[name]) != expected:
            raise ValueError("checksum mismatch: " + name)
    return Package(files, metadata, manifest, checksums)


def compare_packages(old_path, new_path):
    old, new = read_package(old_path), read_package(new_path)
    outside = lambda name: not name.startswith("runtime/")
    old_names = {name for name in old.files if outside(name)}
    new_names = {name for name in new.files if outside(name)}
    if old_names != new_names:
        raise ValueError("non-runtime inventory changed")
    for name in old_names - {"manifest.json", "checksums.sha256"}:
        if old.files[name] != new.files[name]:
            raise ValueError("non-runtime bytes changed: " + name)
    for name in old.files.keys() & new.files.keys():
        if old.metadata[name] != new.metadata[name]:
            raise ValueError("non-derived ZIP metadata changed: " + name)
    old_manifest = {key: value for key, value in old.manifest.items() if key != "immutable_files"}
    new_manifest = {key: value for key, value in new.manifest.items() if key != "immutable_files"}
    if old_manifest != new_manifest:
        raise ValueError("manifest fields changed")
    for name in old_names - {"manifest.json", "checksums.sha256"}:
        if old.manifest["immutable_files"][name] != new.manifest["immutable_files"][name]:
            raise ValueError("non-runtime immutable digest changed")
        if old.checksums[name] != new.checksums[name]:
            raise ValueError("non-runtime checksum changed")
    changed = sorted(name for name in old.files.keys() | new.files.keys()
                     if name.startswith("runtime/") and old.files.get(name) != new.files.get(name))
    return {"non_runtime_files": len(old_names), "runtime_changes": changed,
            "old_zip_sha256": digest(Path(old_path).read_bytes()),
            "new_zip_sha256": digest(Path(new_path).read_bytes()), "all_hashes_verified": True}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare_packages(args.baseline, args.candidate), sort_keys=True))
