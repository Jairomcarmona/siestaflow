"""Detect accidental edits to the legacy namespace in tracked source files."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tools" / "legacy_namespace.json"
TOKEN = re.compile(r"\bsiestaflow\.[A-Za-z0-9_.-]*")


def inventory(root: Path) -> dict[str, dict[str, int]]:
    """Count literal namespace references; ignore untracked build products."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "src/qraft"],
        cwd=root, check=True, capture_output=True,
    )
    found = {}
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = raw_path.decode("utf-8")
        path = root / relative
        if not path.is_file():
            continue  # Deletion of a protected file produces a missing entry.
        counts = Counter(TOKEN.findall(path.read_bytes().decode("utf-8", errors="replace")))
        if counts:
            found[relative] = dict(sorted(counts.items()))
    return dict(sorted(found.items()))


def differences(expected: dict, actual: dict) -> list[str]:
    changes = []
    for path in sorted(expected.keys() | actual.keys()):
        before, after = expected.get(path, {}), actual.get(path, {})
        for token in sorted(before.keys() | after.keys()):
            old, new = before.get(token, 0), after.get(token, 0)
            if old != new:
                changes.append(f"{path}: {token}: expected {old}, found {new}")
    return changes


def main() -> int:
    try:
        expected = json.loads(BASELINE.read_text(encoding="utf-8"))
        if not isinstance(expected, dict) or not expected:
            raise ValueError("The namespace baseline must be a nonempty mapping")
        changes = differences(expected, inventory(ROOT))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Cannot check legacy namespace: {exc}", file=sys.stderr)
        return 2
    if changes:
        print("Legacy namespace changed; review compatibility before updating the baseline:")
        print("\n".join(changes))
        return 1
    print(f"Legacy namespace preserved in {len(expected)} source files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
