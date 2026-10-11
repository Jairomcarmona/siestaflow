"""Linux containment primitives for a dedicated ADR-017 supervisor process."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import sys
from typing import Callable


class ControllerContainmentError(ValueError):
    """Positive containment or process identity is unavailable."""


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_time_ticks: str
    boot_id: str

    def to_mapping(self) -> dict[str, int | str]:
        return {"pid": self.pid, "start_time_ticks": self.start_time_ticks,
                "boot_id": self.boot_id}


def process_identity(pid: int) -> ProcessIdentity:
    fields = (Path("/proc") / str(pid) / "stat").read_text().rpartition(") ")[2].split()
    return ProcessIdentity(pid, fields[19], Path("/proc/sys/kernel/random/boot_id").read_text().strip())


class PidfdSignals:
    """glibc fallback for installed Python builds without pidfd wrappers."""

    def __init__(self) -> None:
        if not sys.platform.startswith("linux"):
            raise ControllerContainmentError("CONTROLLER_CONTAINMENT_UNAVAILABLE")
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.open: Callable[[int, int], int] = getattr(os, "pidfd_open", None)
        self.send: Callable[[int, int], None] = getattr(signal, "pidfd_send_signal", None)
        try:
            if self.open is None:
                opening = self.libc.pidfd_open
                opening.argtypes, opening.restype = (ctypes.c_int, ctypes.c_uint), ctypes.c_int
                self.open = lambda pid, flags=0: self._check(opening(pid, flags))
            if self.send is None:
                sending = self.libc.pidfd_send_signal
                sending.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint)
                sending.restype = ctypes.c_int
                self.send = lambda fd, number: self._check(sending(fd, number, None, 0))
            descriptor = self.open(os.getpid(), 0)
            try:
                self.send(descriptor, 0)
            finally:
                os.close(descriptor)
        except (AttributeError, OSError) as exc:
            raise ControllerContainmentError("CONTROLLER_CONTAINMENT_UNAVAILABLE") from exc

    @staticmethod
    def _check(result: int) -> int:
        if result == -1:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return result

    def signal_identity(self, identity: ProcessIdentity, number: int) -> None:
        """Open first, recheck the recorded birth identity, then signal the handle."""
        descriptor = self.open(identity.pid, 0)
        try:
            if process_identity(identity.pid) != identity:
                raise ControllerContainmentError("controller process identity changed")
            self.send(descriptor, number)
        finally:
            os.close(descriptor)


class SupervisorChildren:
    """Subreaping is enabled only in the dedicated isolated supervisor."""

    def __init__(self) -> None:
        if not sys.flags.isolated:
            raise ControllerContainmentError("supervisor requires an isolated installed interpreter")
        self.signals = PidfdSignals()
        self.root = os.getpid()
        # PR_SET_CHILD_SUBREAPER = 36; process-local, no site configuration.
        prctl = self.signals.libc.prctl
        prctl.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong)
        prctl.restype = ctypes.c_int
        if prctl(36, 1, 0, 0, 0) != 0:
            raise ControllerContainmentError("CONTROLLER_CONTAINMENT_UNAVAILABLE")

    def descendants(self) -> dict[int, ProcessIdentity]:
        """Traverse all threads' child lists, including adopted setsid descendants."""
        pending, seen, result = [self.root], {self.root}, {}
        while pending:
            parent = pending.pop()
            try:
                threads = tuple((Path("/proc") / str(parent) / "task").iterdir())
            except FileNotFoundError:
                continue
            for thread in threads:
                try:
                    children = (thread / "children").read_text().split()
                except FileNotFoundError:
                    continue
                for child in map(int, children):
                    if child in seen:
                        continue
                    seen.add(child)
                    try:
                        result[child] = process_identity(child)
                    except FileNotFoundError:
                        continue
                    pending.append(child)
        return result

    def _is_descendant(self, pid: int) -> bool:
        seen: set[int] = set()
        while pid not in seen and pid > 1:
            seen.add(pid)
            try:
                fields = (Path("/proc") / str(pid) / "stat").read_text().rpartition(") ")[2].split()
            except FileNotFoundError:
                return False
            pid = int(fields[1])
            if pid == self.root:
                return True
        return False

    def signal_owned(self, identity: ProcessIdentity, number: int) -> None:
        try:
            descriptor = self.signals.open(identity.pid, 0)
        except ProcessLookupError:
            return
        try:
            # An observed numeric PID alone is never ownership. Both checks are
            # AFTER pidfd_open, which pins the target before signalling.
            if process_identity(identity.pid) != identity:
                return
            if not self._is_descendant(identity.pid):
                return
            self.signals.send(descriptor, number)
        except (ProcessLookupError, FileNotFoundError):
            pass
        finally:
            os.close(descriptor)

    def signal_all(self, number: int) -> None:
        for identity in self.descendants().values():
            self.signal_owned(identity, number)

    @staticmethod
    def reap() -> tuple[dict[int, int], bool]:
        """ECHILD, and only ECHILD, proves the dedicated supervisor has no children."""
        exits: dict[int, int] = {}
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return exits, True
            if pid == 0:
                return exits, False
            exits[pid] = os.waitstatus_to_exitcode(status)
