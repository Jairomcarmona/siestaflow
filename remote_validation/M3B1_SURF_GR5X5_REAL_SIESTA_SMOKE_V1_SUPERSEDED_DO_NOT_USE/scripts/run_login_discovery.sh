#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ -f "$ROOT/package_manifest.json" ]] || { echo "INVALID_PACKAGE_ROOT:$ROOT" >&2; exit 2; }
OUT="$ROOT/evidence/login_discovery"
[[ ! -e "$OUT" ]] || { echo "REFUSING_OVERWRITE:$OUT" >&2; exit 2; }
mkdir -p "$OUT"
date -u +%Y-%m-%dT%H:%M:%SZ >"$OUT/observed_at.txt"
for command in siesta siesta-5.4.2 srun mpiexec.hydra mpiexec mpirun sbatch sacct squeue; do
  command -v "$command" >"$OUT/command_${command//./_}.txt" 2>/dev/null || true
done
if type module >/dev/null 2>&1; then
  module -t avail siesta >"$OUT/module_avail_siesta.txt" 2>&1 || true
  module list >"$OUT/module_list.txt" 2>&1 || true
fi
python3 - "$OUT" <<'PY'
import json,pathlib,sys
o=pathlib.Path(sys.argv[1]); commands={}
for p in o.glob('command_*.txt'):
 commands[p.stem.removeprefix('command_').replace('_','.')]=p.read_text(errors='replace').strip() or None
d={'source':'REAL_REMOTE_LOGIN_DISCOVERY','commands':commands,'scientific_calculation_performed':False,'job_submitted':False}
(o/'summary.json').write_text(json.dumps(d,sort_keys=True,indent=2)+'\n')
PY
echo "LOGIN_DISCOVERY_COMPLETE:$OUT"
