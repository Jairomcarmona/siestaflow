from __future__ import annotations

import ast
from pathlib import Path


def _method(module: ast.Module, name: str) -> ast.FunctionDef:
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "ConvergenceProtocol":
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == name:
                    return member
    raise AssertionError(f"method not found: {name}")


def test_convergence_execution_uses_the_canonical_runtime() -> None:
    source_path = Path(__file__).parents[2] / "src/qraft/protocols/convergence.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    run_method = _method(tree, "run")

    direct_calls = [
        node for node in ast.walk(run_method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "execute_fdf_plan"
    ]
    compiler_calls = [
        node for node in ast.walk(run_method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "compile"
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Name)
        and node.func.value.func.id == "WorkflowCompiler"
    ]
    runtime_bindings = [
        node for node in ast.walk(run_method)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "runtime"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "CompiledWorkflowRuntime"
    ]
    runtime_calls = [
        node for node in ast.walk(run_method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "runtime"
    ]
    assert not direct_calls
    assert len(compiler_calls) == 1
    assert len(runtime_bindings) == 1
    assert len(runtime_calls) == 1
