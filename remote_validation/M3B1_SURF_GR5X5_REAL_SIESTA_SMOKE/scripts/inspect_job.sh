#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ $# -eq 1 && "$1" =~ ^[0-9]+$ ]] || { echo 'usage: inspect_job.sh JOB_ID' >&2; exit 2; }
OUT="$ROOT/evidence/accounting"; mkdir -p "$OUT"
squeue -h -j "$1" -o '%i|%T|%P|%a|%q|%M|%N' >"$OUT/squeue.txt" 2>"$OUT/squeue.err" || true
sacct -n -P -j "$1" -o JobID,State,ExitCode,Elapsed,NodeList,Partition,Account,QOS >"$OUT/sacct.txt" 2>"$OUT/sacct.err" || true
python3 - "$OUT" "$1" <<'PY'
import json,pathlib,sys
o=pathlib.Path(sys.argv[1]); rows=[]
for line in (o/'sacct.txt').read_text(errors='replace').splitlines():
 f=line.strip().split('|')
 if len(f)>=3 and f[0]==sys.argv[2]: rows.append(f)
d={'job_id':sys.argv[2],'state':rows[0][1] if rows else None,'exit_code':rows[0][2] if rows else None}
(o/'summary.json').write_text(json.dumps(d,sort_keys=True,indent=2)+'\n')
PY
python3 "$ROOT/scripts/parse_siesta_result.py" --package-root "$ROOT"
echo "ACCOUNTING_CAPTURED:$OUT"
