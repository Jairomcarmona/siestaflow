"""Private immutable binary provenance; never an ExecutionSpec extension."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class _Binary:
    path: str
    version: str
    sha256: str
    version_evidence: str

    def verify(self):
        path = Path(self.path)
        if not path.is_absolute() or str(path.resolve()) != self.path or not self.version or not self.version_evidence:
            raise ValueError('Worker binary needs a resolved path and explicit version provenance')
        if _sha(path) != self.sha256:
            raise ValueError('Worker binary SHA-256 mismatch: '+self.path)


@dataclass(frozen=True)
class _WorkerEnvironment:
    lock_path: Path
    sha256: str
    siesta: _Binary
    fat: _Binary

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        payload = json.loads(path.read_bytes())
        if set(payload) != {'siesta', 'fat'}:
            raise ValueError('Worker lock must identify siesta and fat')
        result = cls(path, _sha(path), *(_Binary(**payload[name]) for name in ('siesta', 'fat')))
        result.verify()
        return result

    def verify(self):
        if _sha(self.lock_path) != self.sha256:
            raise ValueError('Immutable worker lock changed')
        self.siesta.verify()
        self.fat.verify()

    def launcher(self, delegate):
        environment = self
        class LockedLauncher:
            def launch(self, spec):
                environment.verify()
                if spec.executable != environment.siesta.path:
                    raise ValueError('Execution executable differs from worker lock')
                return delegate.launch(spec)

            def terminate_all(self, *, kill=False):
                return delegate.terminate_all(kill=kill)
        return LockedLauncher()
