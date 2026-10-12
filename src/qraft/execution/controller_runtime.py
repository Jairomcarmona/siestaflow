"""ADR-017 composition into the existing runtime; no scientific interpretation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import math
from pathlib import Path
from typing import Any, Callable, Mapping

from qraft.contracts import CapabilityKind, CapabilityRegistry, WorkflowTaskNode
from qraft.core import ExecutionSpec, TechnicalValidation

from .controller_admission import ControllerAdmission, admit_controller
from .controller_contracts import (
    read_controller_ledger, validate_controller_descriptor,
    validate_controller_resume_verdict,
)
from .controller_files import atomic_controller_json, contained_path, read_controller_json
from .controller_launcher import ControllerLauncher
from .controller_ledger import evaluate_controller_ledger
from .controller_reservation import ControllerReservation
from .controller_state import previous_controller_owner
from .resource_coordinator import RuntimeAllocation
from .srun_launcher import StepLaunchSpec, StepOutcome


def ledger_rules(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_id": descriptor["task_id"], "hosts": descriptor["reserved"]["hosts"],
        "runtime_cpus": descriptor["reserved"]["runtime_cpus"],
        "max_concurrent": descriptor["inner"]["max_concurrent"],
        "stop_launching_at": descriptor["deadline"]["stop_launching_at"],
    }


def write_state_seal_evidence(attempt: Path, state_seal: str | None) -> None:
    """Persist the D.5 recovery marker as native attempt evidence, not a schema field."""
    if state_seal is None:
        return
    if state_seal != "ABSENT_AFTER_BOOT_CHANGE":
        raise ValueError("unsupported controller state seal evidence")
    atomic_controller_json(attempt / ".qraft/controller-attempt-evidence.json", {
        "state_seal": state_seal,
    })


class ControllerRuntimeContext:
    """Read-only admission and native attempt evidence, using one lease authority."""

    def __init__(
        self, *, root: Path, allocation: RuntimeAllocation,
        registry: CapabilityRegistry, tasks: tuple[WorkflowTaskNode, ...],
        execution_specs: Mapping[str, ExecutionSpec],
        reservations: Mapping[str, ControllerReservation],
        scheduler: str, environment: Mapping[str, str],
        launcher: ControllerLauncher, run_fingerprint: Callable[[], str],
        attempt_path: Callable[[str, str], Path], authority_generation: str | None,
    ) -> None:
        self.root, self.allocation, self.registry = root, allocation, registry
        self.reservations, self.executions = dict(reservations), dict(execution_specs)
        self.scheduler, self.environment, self.launcher = scheduler, dict(environment), launcher
        self.run_fingerprint, self.attempt_path = run_fingerprint, attempt_path
        self.authority_generation = authority_generation
        self.admissions: dict[str, ControllerAdmission] = {}
        self.templates: dict[tuple[str, str], dict[str, Any]] = {}
        for task in tasks:
            if task.task_id not in reservations:
                continue
            registered = registry.resolve(task.capability_id)
            if registered.descriptor.kind not in {CapabilityKind.ENGINE, CapabilityKind.EXECUTABLE}:
                raise ValueError("controller requires an executable capability")
            admission = admit_controller(
                reservations[task.task_id], registered.descriptor, allocation,
                execution_specs[task.task_id], scheduler=scheduler, environment=environment,
            )
            self.admissions[task.task_id] = admission
        self.runtime_host = next(iter(self.admissions.values())).runtime_host
        if any(item.runtime_host != self.runtime_host for item in self.admissions.values()):
            raise ValueError("controller runtime host must be unique")

    def previous(self, task_id: str, record: Mapping[str, Any]) -> dict[str, Any] | None:
        state = contained_path(self.root, f"controller-state/{task_id}")
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        previous = previous_controller_owner(
            self.root, state, current_boot_id=boot_id,
            current_host=self.admissions[task_id].runtime_host,
        )
        if previous is None:
            if record["attempts"]:
                raise ValueError("CONTROLLER_STATE_TAMPERED: prior native state is missing")
        elif previous["attempt_id"] != record["last_attempt"]:
            raise ValueError("CONTROLLER_STATE_TAMPERED: native owner disagrees with runtime")
        else:
            previous = {**previous, "outcome": record["status"]}
        return previous

    def attempt_context(
        self, task: WorkflowTaskNode, attempt_id: str, number: int,
        previous: dict[str, Any] | None,
    ) -> dict[str, Any]:
        remaining = self.allocation.remaining_seconds()
        if not math.isfinite(remaining) or remaining <= self.allocation.shutdown_margin_seconds:
            raise ValueError("controller requires a finite positive allocation deadline")
        now = datetime.now(timezone.utc)
        hard_stop = now + timedelta(seconds=remaining)
        stop_launching = hard_stop - timedelta(seconds=self.allocation.shutdown_margin_seconds)
        admission, reservation = self.admissions[task.task_id], self.reservations[task.task_id]
        registered = self.registry.resolve(task.capability_id)
        attempt = self.attempt_path(task.task_id, attempt_id)
        relative = attempt.relative_to(self.root).as_posix()
        previous_descriptor = previous
        if previous is not None and "state_seal" in previous:
            previous_descriptor = {
                key: previous[key] for key in (
                    "attempt_id", "outcome", "closure", "state_manifest_sha256",
                )
            }
            write_state_seal_evidence(attempt, previous["state_seal"])
        descriptor = {
            "contract": "qraft.controller-reservation@1.0",
            "run_fingerprint": self.run_fingerprint(), "task_id": task.task_id,
            "attempt_id": attempt_id, "attempt_number": number,
            "authority_generation": self.authority_generation,
            "capability": {"capability_id": task.capability_id,
                           "version": registered.descriptor.implementation_version,
                           "plugin_version": registered.plugin.plugin_version},
            "allocation": {"scheduler": self.scheduler, "allocation_id": self.allocation.allocation_id},
            "reserved": {"hosts": [admission.runtime_host], "nodes": 1,
                         "runtime_cpus": admission.runtime_cpus, "min_cpus": reservation.min_cpus,
                         "scheduler_cpus_on_host": {"value": admission.scheduler_cpus_on_host,
                                                    "source": admission.scheduler_cpu_source}},
            "inner": {"launcher_kind": reservation.inner_launcher,
                      "launcher_command": [*self.executions[task.task_id].launcher_command,
                                           *self.executions[task.task_id].launcher_arguments],
                      "processes_per_node": reservation.inner_processes_per_node,
                      "cpus_per_process": reservation.inner_cpus_per_process,
                      "max_concurrent": reservation.max_concurrent_inner_launches,
                      "environment": dict(self.executions[task.task_id].environment)},
            "deadline": {"stop_launching_at": stop_launching.isoformat().replace("+00:00", "Z"),
                         "hard_stop_at": hard_stop.isoformat().replace("+00:00", "Z")},
            "paths": {"state_dir": f"controller-state/{task.task_id}",
                      "stop_request": f"{relative}/.qraft/stop-request.json",
                      "inner_ledger": f"{relative}/.qraft/inner-ledger.jsonl",
                      "resume_verdict": f"{relative}/.qraft/resume-verdict.json"},
            "previous_attempt": previous_descriptor,
        }
        self.templates[(task.task_id, attempt_id)] = descriptor
        prior_ledgers = tuple(
            self.recorded_ledger(task.task_id, f"attempt-{index:04d}")
            for index in range(1, number)
        )
        # These are method-composition arguments, not workflow/schema fields.
        return {
            "controller_reservation_path": f"{relative}/.qraft/controller-reservation.json",
            "controller_state_dir": contained_path(self.root, descriptor["paths"]["state_dir"]),
            "controller_prior_ledgers": prior_ledgers,
            "controller_entrypoint": admission.entrypoint,
        }

    def recorded_ledger(self, task_id: str, attempt_id: str) -> str:
        descriptor = read_controller_json(self.attempt_path(task_id, attempt_id) / ".qraft/controller-reservation.json")
        validate_controller_descriptor(descriptor)
        if (descriptor["task_id"] != task_id or descriptor["attempt_id"] != attempt_id
                or descriptor["run_fingerprint"] != self.run_fingerprint()):
            raise ValueError("CONTROLLER_LEDGER_INCONSISTENT: prior descriptor identity mismatch")
        relative = descriptor["paths"]["inner_ledger"]
        contained_path(self.root, relative)
        return relative

    def bind(self, spec: StepLaunchSpec, check_authority: Callable[[], None]) -> None:
        admission = self.admissions[spec.task_id]
        self.launcher.bind_attempt(
            spec, self.templates[(spec.task_id, spec.attempt_id)],
            entrypoint=admission.entrypoint, check_authority=check_authority,
        )

    def can_release(self, task_id: str, attempt_id: str | None) -> bool:
        if attempt_id is None or not self.launcher.has_launched(task_id, attempt_id):
            return True
        return self.launcher.closure_proven(task_id, attempt_id)

    def validation(
        self, task: WorkflowTaskNode, attempt_id: str, outcome: StepOutcome,
    ) -> TechnicalValidation | None:
        if not self.launcher.closure_proven(task.task_id, attempt_id):
            return TechnicalValidation("BLOCKED", "CONTROLLER_CLOSURE_UNKNOWN",
                                       ("controller closure was not proven; lease retained",), {})
        try:
            descriptor = self._descriptor(task.task_id, attempt_id)
            if outcome.exit_code == 75:
                verdict = read_controller_json(contained_path(self.root, descriptor["paths"]["resume_verdict"]))
                validate_controller_resume_verdict(verdict)
                previous = descriptor["previous_attempt"]
                if (verdict["decision"] != "REFUSE" or verdict["task_id"] != task.task_id
                        or verdict["attempt_id"] != attempt_id
                        or previous is None or verdict["previous_attempt_id"] != previous["attempt_id"]):
                    raise ValueError("refusal verdict identity does not match the native attempt")
                return TechnicalValidation("BLOCKED", verdict["reason"], ("native controller refused resume",), {})
            attempts, rules = [], {}
            for index in range(1, descriptor["attempt_number"] + 1):
                identity = f"attempt-{index:04d}"
                old = self._descriptor(task.task_id, identity)
                if old["attempt_number"] != index:
                    raise ValueError("controller descriptor attempt number mismatch")
                ledger = contained_path(self.root, old["paths"]["inner_ledger"])
                if not ledger.is_file():
                    raise ValueError("native inner ledger is missing")
                # A prior attempt interrupted by a runtime crash may lack its
                # final manifest; descriptor/ledger and owner proof still apply.
                interrupted = (outcome.terminated_by_controller if identity == attempt_id
                               else self._prior_interrupted(task.task_id, identity))
                attempts.append({"attempt_id": identity, "end": "INTERRUPTED" if interrupted else "NORMAL",
                                 "lines": list(read_controller_ledger(ledger))})
                rules[identity] = ledger_rules(old)
            verdict = evaluate_controller_ledger(ledger_rules(descriptor), attempts, attempt_reservations=rules)
            if not verdict.accepted:
                return TechnicalValidation("FAIL", verdict.reason, (verdict.code,), {})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return TechnicalValidation("BLOCKED" if outcome.exit_code == 75 else "FAIL",
                                       "CONTROLLER_LEDGER_INCONSISTENT", (str(exc),), {})
        return None

    def _descriptor(self, task_id: str, attempt_id: str) -> dict[str, Any]:
        descriptor = read_controller_json(self.attempt_path(task_id, attempt_id) / ".qraft/controller-reservation.json")
        validate_controller_descriptor(descriptor)
        if (descriptor["task_id"] != task_id or descriptor["attempt_id"] != attempt_id
                or descriptor["run_fingerprint"] != self.run_fingerprint()):
            raise ValueError("controller descriptor identity mismatch")
        return descriptor

    def _prior_interrupted(self, task_id: str, attempt_id: str) -> bool:
        manifest = self.attempt_path(task_id, attempt_id) / "attempt.json"
        if not manifest.is_file():
            return True
        wrapper = read_controller_json(manifest)
        from qraft.contracts.serialization import contract_sha256
        if contract_sha256(wrapper["payload"]) != wrapper["sha256"]:
            raise ValueError("prior attempt manifest checksum mismatch")
        payload = wrapper["payload"]
        if payload["runtime_fingerprint"] != self.run_fingerprint():
            raise ValueError("prior attempt runtime identity mismatch")
        for relative, digest in payload["evidence_files"].items():
            path = contained_path(manifest.parent, relative)
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("prior attempt evidence checksum mismatch")
        return payload["attempt"]["result"]["execution_state"] == "INTERRUPTED"

    def evidence_files(self, task_id: str, attempt_id: str) -> dict[str, str]:
        attempt = self.attempt_path(task_id, attempt_id)
        result = {}
        for name in ("controller-reservation.json", "controller-closure.json",
                     "controller-state-manifest.json", "controller-attempt-evidence.json",
                     "inner-ledger.jsonl", "resume-verdict.json"):
            relative = f".qraft/{name}"
            path = contained_path(attempt, relative)
            if path.is_file():
                result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result
