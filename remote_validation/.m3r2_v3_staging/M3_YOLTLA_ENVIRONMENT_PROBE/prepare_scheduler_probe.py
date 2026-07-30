#!/usr/bin/env python3
import argparse,json,os,re,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'scripts'))
from scheduler_resolution import ResourceRequest,SchedulerAssociation,VisiblePartition,PartitionPolicy,apply_human_selection,resolve_scheduler_candidates
p=argparse.ArgumentParser();p.add_argument('--login-evidence',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--account');p.add_argument('--partition');p.add_argument('--qos');a=p.parse_args()
data=json.loads(a.login_evidence.read_text(encoding='utf-8'))
associations=[SchedulerAssociation(**x) for x in data.get('eligible_associations',[])]
visible=[VisiblePartition(**x) for x in data.get('visible_partitions',[])]
policies=[PartitionPolicy(**x) for x in data.get('partition_policies',[])]
request=ResourceRequest();resolution=resolve_scheduler_candidates(associations,visible,policies,request)
manual=any(x is not None for x in (a.account,a.partition,a.qos))
if manual:
 if not a.account or not a.partition:raise SystemExit('USER_SELECTION_NOT_SUPPORTED_BY_EVIDENCE')
 try:resolution=apply_human_selection(resolution,a.account,a.partition,a.qos)
 except ValueError as exc:raise SystemExit(str(exc))
selected=resolution.get('selected')
if not selected:raise SystemExit(resolution['status'])
account,partition,qos=selected['account'],selected['partition'],selected.get('qos');safe=re.compile(r'^[A-Za-z0-9._-]+$')
if not safe.fullmatch(account) or not safe.fullmatch(partition) or (qos and not safe.fullmatch(qos)):raise SystemExit('SCHEDULER_PROBE_BLOCKED_UNSAFE_ASSOCIATION_VALUE')
a.output.parent.mkdir(parents=True,exist_ok=True)
if a.output.exists():raise SystemExit('REFUSING_OVERWRITE:'+str(a.output))
selection_path=a.output.parent/'scheduler_selection.json'
if selection_path.exists():raise SystemExit('REFUSING_OVERWRITE:'+str(selection_path))
qos_line=f'#SBATCH --qos={qos}\n' if qos else ''
script=f'''#!/usr/bin/env bash
# account: value origin = sacctmgr association; evidence status = OBSERVED
# partition: value origin = sinfo default marker + scontrol policy; evidence status = VERIFIED_BY_CROSS_SOURCE
# qos: value origin = sacctmgr association; evidence status = OBSERVED
# Probe minima origin: M3_NON_SCIENTIFIC_MINIMAL_RESOURCE_POLICY
#SBATCH --job-name=m3-environment-probe
#SBATCH --partition={partition}
#SBATCH --account={account}
{qos_line}#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --time=00:02:00
#SBATCH --signal=B:USR1@60
#SBATCH --output=evidence/stdout/scheduler-%j.out
#SBATCH --error=evidence/stderr/scheduler-%j.err
set -euo pipefail
ROOT=$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd -P)
OUT="$ROOT/evidence/scheduler_probe"
mkdir -p "$OUT" "$ROOT/evidence/stdout" "$ROOT/evidence/stderr"
[[ ! -e "$OUT/summary.json" ]] || {{ echo "REFUSING_OVERWRITE:$OUT/summary.json" >&2; exit 2; }}
trap 'date -u +%Y-%m-%dT%H:%M:%SZ >"$OUT/signal_received.txt"' USR1
env | grep '^SLURM_' | grep -Evi '(TOKEN|PASSWORD|SECRET|KEY|CREDENTIAL|COOKIE)' | head -n 200 >"$OUT/slurm_environment.txt" || true
hostname >"$OUT/hostname.txt"
kill -USR1 $$
python3 - "$OUT" <<'PY'
import json,os,sys,datetime,pathlib
o=pathlib.Path(sys.argv[1]);e=os.environ
d={{'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'job_id':e.get('SLURM_JOB_ID'),'partition':e.get('SLURM_JOB_PARTITION'),'account':e.get('SLURM_JOB_ACCOUNT'),'qos':e.get('SLURM_JOB_QOS'),'nodes':int(e.get('SLURM_NNODES','0')) or None,'ntasks':int(e.get('SLURM_NTASKS','0')) or None,'cpus_per_task':int(e.get('SLURM_CPUS_PER_TASK','0')) or None,'memory':None,'walltime':'00:02:00','signal':'B:USR1@60','signal_received':(o/'signal_received.txt').is_file(),'job_end_time':e.get('SLURM_JOB_END_TIME'),'scientific_calculation_performed':False}}
(o/'summary.json').write_text(json.dumps(d,sort_keys=True,indent=2)+'\\n',encoding='utf-8')
PY
echo NON_SCIENTIFIC_ENVIRONMENT_PROBE_COMPLETE
'''
temporary=a.output.with_name(a.output.name+'.tmp');temporary.write_text(script,encoding='utf-8',newline='\n')
validator=Path(__file__).resolve().parent/'scripts'/'validate_embedded_python.py'
for command,cwd in ((['bash','-n',temporary.name],temporary.parent),([sys.executable,str(validator),str(temporary)],None)):
 result=subprocess.run(command,cwd=cwd,capture_output=True,text=True,check=False)
 if result.returncode!=0:
  temporary.unlink(missing_ok=True);raise SystemExit('GENERATED_SCHEDULER_SCRIPT_INVALID:'+(result.stderr or result.stdout))
selection={'account':account,'partition':partition,'qos':qos,'nodes':request.nodes,'ntasks':request.ntasks,'cpus_per_task':request.cpus_per_task,'walltime':request.walltime,'association_scope':selected['association_scope'],'candidate_partitions':[x['partition'] for x in resolution['candidates']],'selection_policy':resolution['selection_policy'],'source_files':selected['source_files'],'evidence_status_by_field':{'account':'OBSERVED','partition':'VERIFIED_BY_CROSS_SOURCE','qos':'OBSERVED' if qos else 'MISSING'}}
selection_tmp=selection_path.with_name(selection_path.name+'.tmp');selection_tmp.write_text(json.dumps(selection,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
os.replace(temporary,a.output);os.replace(selection_tmp,selection_path);print(a.output);print(selection_path)
