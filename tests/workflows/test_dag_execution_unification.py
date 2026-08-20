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


def test_convergence_execution_seam_is_characterized_before_unification() -> None:
    source_path = Path(__file__).parents[2] / "src/qraft/protocols/convergence.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    run_method = _method(tree, "run")

    direct_calls = [
        node for node in ast.walk(run_method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "execute_fdf_plan"
    ]
    assert len(direct_calls) == 1
    assert any(
        isinstance(node, ast.For)
        and any(child in direct_calls for child in ast.walk(node))
        for node in ast.walk(run_method)
    ), "the current protocol-owned execution loop must remain explicit until bridged"
