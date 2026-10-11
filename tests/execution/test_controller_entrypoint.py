"""No PATH discovery, entrypoint imports or generic command substitution."""

from dataclasses import replace
from importlib import metadata
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from qraft.contracts import CapabilityDescriptor, CapabilityKind, EXECUTION_REQUEST
from qraft.execution.controller_entrypoint import (
    ControllerExtension, resolve_controller_entrypoint, validate_controller_command,
)


def extension():
    return ControllerExtension("qraft-hpc", "qraft", ("openmpi",), "NONE")


def descriptor(**changes):
    values = dict(schema_version="1.0", distribution="qraft-hpc", entrypoint="qraft",
                  inner_launchers=["openmpi"], resume="NONE") | changes
    return CapabilityDescriptor("consumer.controller", CapabilityKind.EXECUTABLE,
                                "1.0", (EXECUTION_REQUEST,), (),
                                metadata={"qraft.controller": values})


def test_declared_extension_requires_known_version_and_fields():
    assert ControllerExtension.from_descriptor(descriptor()) == extension()
    for change in ({"schema_version": "2.0"}, {"command": "arbitrary"},
                   {"inner_launchers": "openmpi"}, {"resume": "NATIVE_ASSERTED"}):
        with pytest.raises(ValueError):
            ControllerExtension.from_descriptor(descriptor(**change))
    no_metadata = replace(descriptor(), metadata={})
    with pytest.raises(ValueError):
        ControllerExtension.from_descriptor(no_metadata)
    with pytest.raises(ValueError):
        ControllerExtension.from_descriptor(replace(descriptor(), kind=CapabilityKind.LAUNCHER))


@pytest.mark.parametrize("changes", [
    {"distribution": "../bad"}, {"distribution": "qraft-hpc==1.0"},
    {"entrypoint": "/bin/sh"}, {"entrypoint": "bad command"},
    {"inner_launchers": ("srun",)}, {"inner_launchers": ("openmpi", "openmpi")},
    {"inner_launchers": ()}, {"resume": "NATIVE_ASSERTED"},
])
def test_no_executable_paths_or_undeclared_metadata(changes):
    with pytest.raises(ValueError):
        replace(extension(), **changes)


def test_platform_rejection_before_metadata_access(monkeypatch):
    import qraft.execution.controller_entrypoint as module
    # Replace this module's os reference, not Python's shared os.name/Path behavior.
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(metadata, "distribution", lambda name: pytest.fail("lookup on Windows"))
    with pytest.raises(ValueError, match="CONTROLLER_REQUIRES_POSIX"):
        resolve_controller_entrypoint(extension())


@pytest.mark.skipif(os.name != "posix", reason="controller entrypoints require POSIX")
def test_explicit_distribution_record_does_not_import_or_search_path(tmp_path, monkeypatch):
    import qraft.execution.controller_entrypoint as module
    scripts = tmp_path / "bin"
    scripts.mkdir()
    executable = scripts / "qraft"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    point = metadata.EntryPoint(name="qraft", value="not_imported:main", group="console_scripts")
    monkeypatch.setattr(metadata.EntryPoint, "load", lambda *args: pytest.fail("entrypoint imported"))
    distribution = SimpleNamespace(entry_points=[point], files=["../bin/qraft"],
                                   locate_file=lambda item: tmp_path / "lib" / item)
    (tmp_path / "lib").mkdir()
    looked_up = []
    monkeypatch.setattr(metadata, "distribution", lambda name: looked_up.append(name) or distribution)
    monkeypatch.setattr(module.sysconfig, "get_path", lambda name: str(scripts))
    monkeypatch.setenv("PATH", "/path/which/must/not/be/searched")
    assert resolve_controller_entrypoint(extension()) == executable
    assert looked_up == ["qraft-hpc"]
    distribution.files = []
    with pytest.raises(ValueError, match="CONTROLLER_ENTRYPOINT_MISSING"):
        resolve_controller_entrypoint(extension())
    distribution.files = ["../bin/qraft"]
    distribution.entry_points = []
    with pytest.raises(ValueError, match="CONTROLLER_ENTRYPOINT_MISSING"):
        resolve_controller_entrypoint(extension())


def test_command_must_match_declared_entrypoint_and_relative_descriptor():
    entrypoint = Path("/installed/bin/controller")
    descriptor_path = ".qraft/controller-reservation.json"
    command = (str(entrypoint), "--qraft-reservation", descriptor_path, "--campaign", "plan.json")
    assert validate_controller_command(command, entrypoint, descriptor_path) == command
    for invalid in (
        ("arbitrary", *command[1:]), (*command[:2], "other.json"),
        (*command, "/absolute/input"), (*command, "--input=/absolute/input"),
        (*command, "C:\\absolute\\input"), (*command, "../other/input"),
        (*command, "--qraft-reservation=other.json"), command[0],
    ):
        with pytest.raises(ValueError):
            validate_controller_command(invalid, entrypoint, descriptor_path)
