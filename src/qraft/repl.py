"""Small standard-library interactive shell backed by :mod:`qraft.application`."""

from __future__ import annotations

import cmd
import json
import shlex
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .application import (
    QraftApplication, render_config, render_plan, render_preflight,
)
from .environment_inspection import render_environment
from .errors import QraftError


_BANNER = """============================================================
                         Q R A F T
       Quantum Reproducible Automation & Flow Toolkit
============================================================"""

_KEYS = {
    "np": "mpi_ranks", "nodes": "nodes", "partition": "partition",
    "launcher": "launcher", "walltime": "walltime_seconds",
    "cpus-per-rank": "cpus_per_rank", "siesta": "executable",
    "profile": "profile", "protocol": "protocol", "runs-root": "runs_root",
}


class QraftShell(cmd.Cmd):
    prompt = "qraft> "

    def __init__(
        self, application: QraftApplication | None = None, *,
        stdin: TextIO | None = None, stdout: TextIO | None = None,
    ) -> None:
        super().__init__(stdin=stdin, stdout=stdout)
        self.application = application or QraftApplication()
        self._history: list[str] = []
        self.intro = self._intro()

    def _intro(self) -> str:
        state = self.application.show()
        profile_hint = (
            "Run 'env' to inspect this machine; select a profile only when needed."
            if not state["profile"] else "Run 'env' and 'config' before execution."
        )
        return "\n".join((
            _BANNER,
            f"Version : {__version__}",
            "Engine  : SIESTA",
            f"Profile : {state['profile'] or 'none'}",
            f"Root    : {Path(state['runs_root']).resolve()}",
            "",
            profile_hint,
            "Type 'help' for commands.",
        ))

    def onecmd(self, line: str) -> bool:
        clean = line.strip()
        if clean:
            self._history.append(clean)
        try:
            return bool(super().onecmd(line))
        except (OSError, ValueError, RuntimeError, KeyError, QraftError) as exc:
            self.stdout.write(f"QRAFT_ERROR: {exc}\n")
            return False

    def emptyline(self) -> bool:
        return False

    def do_version(self, arg: str) -> None:
        """version: show the installed QRAFT version."""
        self.stdout.write(f"QRAFT {__version__}\n")

    def do_show(self, arg: str) -> None:
        """show [resolved]: display active or fully resolved configuration."""
        value = self.application.show(resolved=arg.strip().casefold() == "resolved")
        self.stdout.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")

    def do_set(self, arg: str) -> None:
        """set NAME VALUE: set a session override."""
        tokens = shlex.split(arg)
        if len(tokens) < 2:
            raise ValueError("set requires NAME VALUE")
        self.application.set_value(_KEYS.get(tokens[0], tokens[0]), " ".join(tokens[1:]))

    def do_unset(self, arg: str) -> None:
        """unset NAME: remove one session setting."""
        if not arg.strip():
            raise ValueError("unset requires a setting name")
        self.application.unset(_KEYS.get(arg.strip(), arg.strip()))

    def do_reset(self, arg: str) -> None:
        """reset: clear the complete REPL session configuration."""
        self.application.reset()

    def do_fdf(self, arg: str) -> None:
        """fdf PATH: select the principal SIESTA FDF."""
        if not arg.strip():
            self.stdout.write(f"{self.application.show()['fdf'] or 'none'}\n")
            return
        self.application.set_value("fdf", shlex.split(arg)[0])

    def _setting(self, name: str, arg: str) -> None:
        if not arg.strip():
            value = self.application.show()["overrides"].get(_KEYS[name])
            self.stdout.write(f"{value if value is not None else 'unset'}\n")
            return
        self.application.set_value(_KEYS[name], shlex.split(arg)[0])

    def do_np(self, arg: str) -> None:
        """np [N]: show or set MPI ranks."""
        self._setting("np", arg)

    def do_nodes(self, arg: str) -> None:
        """nodes [N]: show or set node count."""
        self._setting("nodes", arg)

    def do_partition(self, arg: str) -> None:
        """partition [NAME]: show or set scheduler partition."""
        self._setting("partition", arg)

    def do_launcher(self, arg: str) -> None:
        """launcher [NAME]: show or set a registered launcher."""
        self._setting("launcher", arg)

    def do_walltime(self, arg: str) -> None:
        """walltime [SECONDS]: show or set walltime in seconds."""
        self._setting("walltime", arg)

    def do_profile(self, arg: str) -> None:
        """profile [NAME|PATH|list|show|validate]: manage external execution profiles."""
        if not arg.strip():
            self.stdout.write(f"{self.application.show()['profile'] or 'none'}\n")
            return
        tokens = shlex.split(arg)
        action = tokens[0].casefold()
        if action == "list":
            self.stdout.write(json.dumps({"profiles": self.application.profiles()}, indent=2) + "\n")
        elif action in {"show", "validate"}:
            reference = tokens[1] if len(tokens) > 1 else None
            self.stdout.write(json.dumps(self.application.profile(reference), indent=2) + "\n")
        else:
            self.application.set_value("profile", tokens[0])

    def do_env(self, arg: str) -> None:
        """env: inspect installed engine, scheduler, launcher and filesystem capabilities."""
        self.stdout.write(render_environment(self.application.environment()) + "\n")

    def do_config(self, arg: str) -> None:
        """config: show the effective configuration and value provenance."""
        self.stdout.write(render_config(self.application.config()) + "\n")

    def do_validate(self, arg: str) -> None:
        """validate [FDF] [KEY VALUE ...]: run the shared non-executing preflight."""
        report = self.application.validate(command_overrides=self._inline(arg))
        self.stdout.write(render_preflight(report) + "\n")

    def do_campaign(self, arg: str) -> None:
        """campaign [NAME]: show or label the active campaign."""
        if not arg.strip():
            self.stdout.write(f"{self.application.show()['campaign'] or 'none'}\n")
            return
        self.application.set_value("campaign", arg.strip())

    def do_protocol(self, arg: str) -> None:
        """protocol [NAME]: show or select a registered scientific protocol."""
        if not arg.strip():
            self.stdout.write(f"{self.application.show()['protocol']}\n")
            return
        self.application.set_value("protocol", arg.strip())

    def _inline(self, arg: str) -> dict[str, Any]:
        tokens = shlex.split(arg)
        overrides: dict[str, Any] = {}
        if tokens and tokens[0].lstrip("-") not in _KEYS:
            self.application.set_value("fdf", tokens.pop(0))
        index = 0
        while index < len(tokens):
            key = tokens[index].lstrip("-")
            if key not in _KEYS or index + 1 >= len(tokens):
                raise ValueError(f"invalid command override near: {tokens[index]}")
            value: Any = tokens[index + 1]
            resolved = _KEYS[key]
            if resolved in {"profile", "protocol", "runs_root"}:
                self.application.set_value(resolved, value)
            else:
                if resolved in {"mpi_ranks", "nodes", "cpus_per_rank", "walltime_seconds"}:
                    value = int(value)
                overrides[resolved] = value
            index += 2
        return overrides

    def do_plan(self, arg: str) -> None:
        """plan [FDF] [KEY VALUE ...]: inspect DAG/resources without submission."""
        result = self.application.plan(command_overrides=self._inline(arg))
        self.stdout.write(render_plan(result) + "\n")

    def do_run(self, arg: str) -> None:
        """run [FDF] [KEY VALUE ...]: execute through the shared QRAFT backend."""
        overrides = self._inline(arg)
        invocation = "qraft> run" + (f" {arg.strip()}" if arg.strip() else "")
        result = self.application.run(
            command_overrides=overrides, invocation=invocation,
            preflight_callback=lambda value: self.stdout.write(render_preflight(value) + "\n"),
        )
        technical = (
            result.get("attempt", {}).get("result", {})
            .get("technical_validation", {}).get("status", result.get("status"))
        )
        self.stdout.write(f"Status     : {technical}\n")
        self.stdout.write(f"QRAFT out  : {result.get('qraft_output', '-')}\n")

    def do_status(self, arg: str) -> None:
        """status: inspect authoritative state files under the active runs root."""
        self.stdout.write(json.dumps(self.application.status(), indent=2) + "\n")

    def do_resume(self, arg: str) -> None:
        """resume: recover/reuse the active calculation through normal run semantics."""
        result = self.application.run(
            invocation="qraft> resume",
            preflight_callback=lambda value: self.stdout.write(render_preflight(value) + "\n"),
        )
        self.stdout.write(f"Status : {result['status']}\n")

    def do_dag(self, arg: str) -> None:
        """dag: display the active resolved DAG without execution."""
        plan = self.application.plan()
        for node in plan["dag"]:
            self.stdout.write(
                f"{node['node_id']} <- {','.join(node['depends_on']) or '-'}\n"
            )

    def do_paths(self, arg: str) -> None:
        """paths: show active FDF, run root and qraft.out paths."""
        state = self.application.show()
        root = Path(state["runs_root"]).resolve()
        self.stdout.write(json.dumps({
            "fdf": state["fdf"], "runs_root": str(root),
            "qraft_output": str(root / "qraft.out"),
        }, indent=2) + "\n")

    def do_attempts(self, arg: str) -> None:
        """attempts: list persisted immutable attempts."""
        self.stdout.write(json.dumps(self.application.attempts(), indent=2) + "\n")

    def do_errors(self, arg: str) -> None:
        """errors: list failure/error events from authoritative evidence."""
        self.stdout.write(json.dumps(self.application.errors(), indent=2) + "\n")

    def do_history(self, arg: str) -> None:
        """history: show commands entered in this REPL session."""
        for index, line in enumerate(self._history, 1):
            self.stdout.write(f"{index:4d}  {line}\n")

    def do_clear(self, arg: str) -> None:
        """clear: add visual separation without terminal-specific escape codes."""
        self.stdout.write("\n" * 20)

    def do_exit(self, arg: str) -> bool:
        """exit: leave QRAFT."""
        return True

    def do_quit(self, arg: str) -> bool:
        """quit: leave QRAFT."""
        return True

    def do_EOF(self, arg: str) -> bool:
        self.stdout.write("\n")
        return True


def run_repl(application: QraftApplication | None = None) -> int:
    QraftShell(application).cmdloop()
    return 0
