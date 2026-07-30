#!/usr/bin/env python3
import argparse,json,os,re,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--login-evidence',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
data=json.loads(a.login_evidence.read_text(encoding='utf-8'));candidates=data.get('eligible_associations',[])
unique={(x.get('account'),x.get('partition'),x.get('qos')) for x in candidates if x.get('account') and x.get('partition')}
if len(unique)!=1:raise SystemExit('SCHEDULER_PROBE_BLOCKED_NO_UNIQUE_EVIDENCE_BACKED_ASSOCIATION')
account,partition,qos=next(iter(unique));safe=re.compile(r'^[A-Za-z0-9._-]+$')
if not safe.fullmatch(account) or not safe.fullmatch(partition) or (qos and not safe.fullmatch(qos)):raise SystemExit('SCHEDULER_PROBE_BLOCKED_UNSAFE_ASSOCIATION_VALUE')
a.output.parent.mkdir(parents=True,exist_ok=True)
if a.output.exists():raise SystemExit('REFUSING_OVERWRITE:'+str(a.output))
temporary=a.output.with_name(a.output.name+'.tmp')
if temporary.exists():raise SystemExit('REFUSING_OVERWRITE:'+str(temporary))
qos_line=f'#SBATCH --qos={qos}\n' if qos else ''
script=f'''#!/usr/bin/env bash
# Values account/partition/QoS: OBSERVED in {a.login_evidence}
# Probe minima origin: M3R_NON_SCIENTIFIC_MINIMAL_RESOURCE_POLICY
#SBATCH --job-name=m3-yoltla-env
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
module list >"$OUT/module_list.txt" 2>&1 || true
for c in siesta siesta-5.4.2 srun mpirun mpiexec mpiexec.hydra; do command -v "$c" >>"$OUT/executables.txt" 2>/dev/null || true; done
for c in srun mpirun mpiexec mpiexec.hydra; do command -v "$c" >/dev/null 2>&1 && "$c" --version >>"$OUT/mpi_versions.txt" 2>&1 || true; done
df -Pk "$ROOT" >"$OUT/filesystem.txt"
kill -USR1 $$
python3 - "$OUT" <<'PY'
import json,os,sys,datetime,pathlib
o=pathlib.Path(sys.argv[1]); e=os.environ
d={{'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'job_id':e.get('SLURM_JOB_ID'),'partition':e.get('SLURM_JOB_PARTITION'),'account':e.get('SLURM_JOB_ACCOUNT'),'qos':e.get('SLURM_JOB_QOS'),'nodes':int(e.get('SLURM_NNODES','0')) or None,'ntasks':int(e.get('SLURM_NTASKS','0')) or None,'cpus_per_task':int(e.get('SLURM_CPUS_PER_TASK','0')) or None,'memory':None,'walltime':'00:02:00','signal':'B:USR1@60','signal_received':(o/'signal_received.txt').is_file(),'job_end_time':e.get('SLURM_JOB_END_TIME'),'scientific_calculation_performed':False}}
(o/'summary.json').write_text(json.dumps(d,sort_keys=True,indent=2)+'\\n',encoding='utf-8')
PY
echo NON_SCIENTIFIC_ENVIRONMENT_PROBE_COMPLETE
'''
temporary.write_text(script,encoding='utf-8',newline='\n')
validator=Path(__file__).resolve().parent/'scripts'/'validate_embedded_python.py'
checks=((['bash','-n',temporary.name],temporary.parent),([sys.executable,str(validator),str(temporary)],None))
for command,cwd in checks:
 result=subprocess.run(command,cwd=cwd,capture_output=True,text=True,check=False)
 if result.returncode!=0:
  temporary.unlink(missing_ok=True)
  print(result.stdout,end='',file=sys.stderr);print(result.stderr,end='',file=sys.stderr)
  raise SystemExit('GENERATED_SCHEDULER_SCRIPT_INVALID')
os.replace(temporary,a.output);print(a.output)
