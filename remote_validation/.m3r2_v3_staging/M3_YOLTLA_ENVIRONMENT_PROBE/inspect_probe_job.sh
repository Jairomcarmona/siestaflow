#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 1 && "$1" =~ ^[0-9]+$ ]] || { echo 'usage: inspect_probe_job.sh JOB_ID' >&2; exit 2; }
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
OUT="$ROOT/evidence/slurm_accounting"
mkdir -p "$OUT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
[[ ! -e "$OUT/squeue_${STAMP}.txt" && ! -e "$OUT/sacct_${STAMP}.txt" ]] || { echo REFUSING_TIMESTAMP_COLLISION >&2; exit 2; }
set +e
squeue -h -j "$1" -o '%i|%T|%P|%a|%q|%M|%N' >"$OUT/squeue_${STAMP}.txt" 2>"$OUT/squeue_${STAMP}.err"
SQUEUE_CODE=$?
sacct -n -P -j "$1" -o JobID,State,ExitCode,Elapsed,AllocTRES,MaxRSS,NodeList,Partition,Account,QOS >"$OUT/sacct_${STAMP}.txt" 2>"$OUT/sacct_${STAMP}.err"
SACCT_CODE=$?
set -e
printf '%s
' "$SQUEUE_CODE" >"$OUT/squeue_${STAMP}.exit_code"
printf '%s
' "$SACCT_CODE" >"$OUT/sacct_${STAMP}.exit_code"
python3 - "$OUT" "$1" "$STAMP" "$SQUEUE_CODE" "$SACCT_CODE" <<'PY'
import json,pathlib,sys,datetime
o=pathlib.Path(sys.argv[1]);jid=sys.argv[2];stamp=sys.argv[3];sq_code=int(sys.argv[4]);sa_code=int(sys.argv[5])
sq=(o/f'squeue_{stamp}.txt').read_text(encoding='utf-8',errors='replace').strip()
lines=[x for x in (o/f'sacct_{stamp}.txt').read_text(encoding='utf-8',errors='replace').splitlines() if x.strip()]
rows=[line.split('|') for line in lines]
row=next((items for items in rows if items and items[0].strip()==jid),None)
values=(row or [])+['']*(10-len(row or []))
raw_state=values[1].strip() if row else ''
state=raw_state.split()[0].rstrip('+').upper() if raw_state else None
exit_code=(values[2].strip() or None) if row else None
terminal_states={'COMPLETED','FAILED','CANCELLED','TIMEOUT','NODE_FAIL','OUT_OF_MEMORY','PREEMPTED','BOOT_FAIL','DEADLINE'}
nonterminal_states={'PENDING','RUNNING','CONFIGURING','COMPLETING','SUSPENDED','RESIZING'}
terminal=state in terminal_states and bool(exit_code)
review=bool(state and not terminal and state not in nonterminal_states) or (bool(lines) and row is None)
d={'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'job_id':jid,'squeue_present':bool(sq),'squeue_exit_code':sq_code,'sacct_command_exit_code':sa_code,'sacct_available':bool(lines) and sa_code==0,'main_job_row_found':row is not None,'terminal_evidence':terminal,'review_required':review,'state':state,'exit_code':exit_code,'elapsed':(values[3].strip() or None) if row else None,'alloc_tres':(values[4].strip() or None) if row else None,'max_rss':(values[5].strip() or None) if row else None,'node_list':(values[6].strip() or None) if row else None,'partition':(values[7].strip() or None) if row else None,'account':(values[8].strip() or None) if row else None,'qos':(values[9].strip() or None) if row else None}
target=o/'summary.json';temporary=o/f'summary_{stamp}.json.tmp'
temporary.write_text(json.dumps(d,sort_keys=True,indent=2)+'\n',encoding='utf-8')
temporary.replace(target)
PY
echo "ACCOUNTING_EVIDENCE_CAPTURED:$OUT"
