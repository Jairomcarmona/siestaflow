#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 1 && "$1" =~ ^[0-9]+$ ]] || { echo 'usage: inspect_probe_job.sh JOB_ID' >&2; exit 2; }
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
OUT="$ROOT/evidence/slurm_accounting"
mkdir -p "$OUT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
[[ ! -e "$OUT/squeue_${STAMP}.txt" && ! -e "$OUT/sacct_${STAMP}.txt" ]] || { echo REFUSING_TIMESTAMP_COLLISION >&2; exit 2; }
squeue -h -j "$1" -o '%i|%T|%P|%a|%q|%M|%N' >"$OUT/squeue_${STAMP}.txt" || true
sacct -n -P -j "$1" -o JobID,State,ExitCode,Elapsed,AllocTRES,MaxRSS,NodeList,Partition,Account,QOS >"$OUT/sacct_${STAMP}.txt" || true
python3 - "$OUT" "$1" "$STAMP" <<'PY'
import json,pathlib,sys,datetime
o=pathlib.Path(sys.argv[1]); jid=sys.argv[2]; stamp=sys.argv[3]
sq=(o/f'squeue_{stamp}.txt').read_text().strip(); lines=[x for x in (o/f'sacct_{stamp}.txt').read_text().splitlines() if x.strip()]
row=next((x.split('|') for x in lines if x.split('|')[0].strip()==jid), None)
state=row[1].strip().split()[0].rstrip('+') if row and len(row)>2 else None; exit_code=row[2].strip() if row and len(row)>2 else None
terminal=state in {'COMPLETED','FAILED','CANCELLED','TIMEOUT','NODE_FAIL','OUT_OF_MEMORY'} and bool(exit_code)
d={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'job_id':jid,'squeue_present':bool(sq),'sacct_available':bool(lines),'terminal_evidence':terminal,'state':state,'exit_code':exit_code,'elapsed':row[3].strip() if row and len(row)>3 else None,'alloc_tres':row[4].strip() if row and len(row)>4 else None,'max_rss':row[5].strip() if row and len(row)>5 else None,'node_list':row[6].strip() if row and len(row)>6 else None,'partition':row[7].strip() if row and len(row)>7 else None,'account':row[8].strip() if row and len(row)>8 else None,'qos':row[9].strip() if row and len(row)>9 else None}
(o/'summary.json').write_text(json.dumps(d,sort_keys=True,indent=2)+'
')
PY
echo "ACCOUNTING_EVIDENCE_CAPTURED:$OUT"
