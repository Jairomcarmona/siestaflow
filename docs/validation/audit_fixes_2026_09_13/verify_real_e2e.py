"""Linux acceptance of an installed wheel with an explicitly selected SIESTA.

Run with --wheel, --engine, --fixture (input.fdf/Mg.psf/O.psf), and a new
--output directory. All execution and installation data stays below --output.
This checks engineering behavior, not scientific convergence or HPC acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import venv


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("wheel", "engine", "fixture", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    wheel, engine, fixture, output = (
        getattr(args, name).resolve() for name in ("wheel", "engine", "fixture", "output")
    )
    assert os.name == "posix", "This acceptance runner requires Linux"
    assert wheel.is_file() and engine.is_file()
    input_files = [fixture / name for name in ("input.fdf", "Mg.psf", "O.psf")]
    assert all(path.is_file() for path in input_files)
    output.mkdir(parents=True, exist_ok=False)
    project = output / "user project"
    project.mkdir()
    environment = output / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / "bin/python"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update(PYTHONNOUSERSITE="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    steps = []
    summary = {
        "status": "INCOMPLETE", "wheel_sha256": sha(wheel),
        "engine": str(engine), "engine_sha256": sha(engine),
        "input_sha256": {path.name: sha(path) for path in input_files},
        "scientific_validity_asserted": False, "steps": steps,
    }

    def save() -> None:
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    def command(label: str, argv: list[str]) -> str:
        started = time.monotonic()
        process = subprocess.Popen(
            argv, cwd=project, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        (output / (label + ".stdout")).write_text(stdout)
        (output / (label + ".stderr")).write_text(stderr)
        steps.append({"step": label, "argv": argv, "exit_code": process.returncode,
                      "seconds": round(time.monotonic() - started, 3), "timed_out": timed_out})
        save()
        assert process.returncode == 0 and not timed_out, (label, stdout, stderr)
        return stdout

    try:
        command("install", [str(python), "-m", "pip", "install", str(wheel)])
        command("dependencies", [str(python), "-m", "pip", "check"])
        module = command("import", [str(python), "-c", "import qraft; print(qraft.__file__)"]).strip()
        assert Path(module).is_relative_to(environment), module
        summary["installed_module"] = module
        for source in input_files:
            shutil.copy2(source, project / source.name)
        profile = project / "local.json"
        profile.write_text(json.dumps({
            "schema_version": "1.0", "name": "audit-real-local", "scheduler": "local",
            "launcher": {"name": "direct", "command": [], "arguments": []},
            "partition": "local", "nodes": 1, "cpus_per_node": 1, "mpi_ranks": 1,
            "cpus_per_rank": 1, "engine": {"executable": str(engine), "arguments": []},
            "environment": {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"},
        }))
        qraft = str(environment / "bin/qraft")
        fdf = str(project / "input.fdf")
        runs = project / "runs"

        def invoke(label: str, *arguments: str):
            text = command(label, [qraft, *arguments])
            return json.loads(text) if "--json" in arguments else text

        invoke("version", "--version")
        invoke("help", "--help")
        invoke("init", "init", "starter.yaml")
        invoke("env", "setup", "env", "--profile", str(profile), "--json")
        invoke("check", "check", fdf, "--profile", str(profile), "--json")
        invoke("plan", "inspect", "plan", fdf, "--profile", str(profile), "--json")
        result = invoke("run", "run", fdf, "--profile", str(profile), "--runs-root", str(runs), "--json")
        status = invoke("status", "status", "--runs-root", str(runs), "--json")
        inventory = invoke("results", "results", "--runs-root", str(runs), "--json")
        manifests = {str(path.relative_to(runs)): sha(path) for path in runs.rglob("attempt.json")}
        resumed = invoke("resume", "resume", "--runs-root", str(runs), "--json")
        checks = {
            "technical_pass": result["attempt"]["result"]["technical_validation"]["status"] == "PASS",
            "status_completed": status["state"] == "COMPLETED",
            "inventory_has_attempt_and_stdout": all(any(
                Path(item["path"]).name == name and Path(item["path"]).is_file()
                for item in inventory["artifacts"]
            ) for name in ("attempt.json", "stdout.txt")),
            "reused_attempt": resumed["status"] == "REUSED_VALIDATED_ATTEMPT",
            "single_immutable_attempt": len(manifests) == 1 and manifests == {
                str(path.relative_to(runs)): sha(path) for path in runs.rglob("attempt.json")
            },
        }
        summary.update(checks=checks, observed_status=status["state"], attempt_count=len(manifests))
        assert all(checks.values()), checks
        summary["status"] = "PASS"
    except Exception as exc:
        summary.update(status="FAIL", error=f"{type(exc).__name__}: {exc}")
    save()
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
