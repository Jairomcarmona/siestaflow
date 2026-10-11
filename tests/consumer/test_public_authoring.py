"""Platform consumer uses only the declared integration surface."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qraft.api import (
    API_VERSION, RecipePolicy, WorkflowComposer, WorkflowFragment, WorkflowCompiler,
    RunPreparer, RunInspector, RunPreparationRequest, write_workflow_lock,
)


def definition():
    fragment = WorkflowFragment.single("fragment", {
        "task_id": "step", "kind": "calculation", "capability": "consumer.engine",
        "inputs": [], "outputs": [], "resources": {},
    }, input_contracts={})
    return WorkflowComposer().compose(
        SimpleNamespace(intent_id="intent", project_id="project", sha256="a" * 64, metadata={}),
        RecipePolicy("consumer.recipe", "1.0", "test", "fixture"), [fragment],
    )


@pytest.mark.parametrize("encoding", ["json", "yaml"])
def test_memory_and_file_share_exact_native_lock(tmp_path, encoding):
    assert API_VERSION == "1.0"
    mapping = definition()
    if encoding == "yaml":
        import yaml
        raw = yaml.safe_dump(mapping, allow_unicode=True).encode("utf-8")
    else:
        raw = json.dumps(mapping, indent=4, ensure_ascii=False).encode("utf-8")
    source = tmp_path / f"workflow.{encoding}"
    source.write_bytes(raw)
    compiler = WorkflowCompiler()
    memory = compiler.compile_mapping(mapping, source_root=tmp_path, source_bytes=raw)
    assert memory.valid
    assert memory.lock_dict() == compiler.compile(source).lock_dict()
    lock = tmp_path / "workflow.lock.json"
    write_workflow_lock(memory, lock)
    assert lock.is_file()
    assert not (tmp_path / ".qraft-definition.json").exists()


def test_mapping_does_not_create_file_and_rejects_forged_bytes(tmp_path):
    compiler = WorkflowCompiler()
    mapping = definition()
    assert compiler.compile_mapping(mapping, source_root=tmp_path).valid
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ValueError, match="do not represent"):
        compiler.compile_mapping(mapping, source_root=tmp_path, source_bytes=b'{}')


def test_prepare_public_adapter_registration_is_explicit_and_no_replacement(tmp_path):
    adapter = lambda *args, **kwargs: {}
    preparer = RunPreparer(tmp_path, task_adapters={"consumer.engine": adapter})
    assert "consumer.engine" in preparer.task_adapter_ids
    assert "consumer.engine" not in RunPreparer(tmp_path).task_adapter_ids
    with pytest.raises(TypeError, match="callable"):
        RunPreparer(tmp_path, task_adapters={"consumer.engine": object()})
    with pytest.raises(ValueError, match="already registered"):
        RunPreparer(tmp_path, task_adapters={RunPreparer(tmp_path).task_adapter_ids[0]: adapter})


def test_public_inspector_verifies_prepared_consumer_fixture(tmp_path):
    # Existing end-to-end fixture includes fan-out/gate, immutable hashes and ZIP.
    import importlib.util
    fixture_path = Path(__file__).parents[1] / "runs/test_adaptive_prepared_run.py"
    spec = importlib.util.spec_from_file_location("prepared_consumer_fixture", fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    _, result, root = fixture.prepared(tmp_path)
    inspected = RunInspector().inspect(root)
    assert inspected.run_id == result.run_id
    assert inspected.task_count == result.task_count
    assert not result.submission_performed and not inspected.execution_authorized
    (root / "campaign.yaml").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError):
        RunInspector().inspect(root)
