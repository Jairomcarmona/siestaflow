#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ -f "$ROOT/package_manifest.json" ]] || { echo "INVALID_PACKAGE_ROOT:$ROOT" >&2; exit 2; }
OUT="$ROOT/evidence/login_discovery"
[[ ! -e "$OUT" ]] || { echo "REFUSING_OVERWRITE:$OUT" >&2; exit 2; }
mkdir -p "$OUT/versions"
date -u +%Y-%m-%dT%H:%M:%SZ >"$OUT/observed_at.txt"
for command_name in siesta siesta-5.4.2 srun mpiexec.hydra mpiexec mpirun; do
  resolved=$(command -v "$command_name" 2>/dev/null || true)
  if [[ -n "$resolved" ]]; then
    readlink -f "$resolved" >"$OUT/command_${command_name//./_}.txt" 2>/dev/null || printf '%s\n' "$resolved" >"$OUT/command_${command_name//./_}.txt"
    "$resolved" --version >"$OUT/versions/${command_name//./_}.txt" 2>&1 || true
  fi
done
if type module >/dev/null 2>&1; then
  module -t avail siesta >"$OUT/module_avail_siesta.txt" 2>&1 || true
  module -t list >"$OUT/module_list.txt" 2>&1 || true
else
  : >"$OUT/module_avail_siesta.txt"; : >"$OUT/module_list.txt"
fi
python3 - "$OUT" <<'PY'
import hashlib,json,pathlib,re,sys
o=pathlib.Path(sys.argv[1])
def modules(path):
 text=path.read_text(errors='replace')
 text=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',text)
 return sorted({x.strip().rstrip('*') for x in re.split(r'[\s,]+',text) if '/' in x and not x.startswith('---')})
def command(name):
 p=o/('command_'+name.replace('.','_')+'.txt')
 return p.read_text(errors='replace').strip() if p.is_file() else None
def version(name):
 p=o/'versions'/(name.replace('.','_')+'.txt')
 return p.read_text(errors='replace') if p.is_file() else ''
siesta=[]
for name in ('siesta','siesta-5.4.2'):
 path=command(name)
 if path:
  v=version(name)
  siesta.append({'name':name,'path':path,'version_output':v,'mpi_confirmed':bool(re.search(r'\bMPI\b',v,re.I))})
srun_path=command('srun')
others=[]
for name in ('mpiexec.hydra','mpiexec','mpirun'):
 path=command(name)
 if path: others.append({'name':name,'path':path,'version_output':version(name)})
d={'source':'REAL_REMOTE_LOGIN_DISCOVERY','modules_observed':modules(o/'module_avail_siesta.txt'),'modules_loaded':modules(o/'module_list.txt'),'siesta_executables':siesta,'srun':({'path':srun_path,'version_output':version('srun')} if srun_path else None),'other_launchers':others,'scientific_calculation_performed':False,'job_submitted':False}
target=o/'runtime_candidates.json'; target.write_text(json.dumps(d,sort_keys=True,indent=2)+'\n')
(o/'runtime_candidates.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest()+'  runtime_candidates.json\n')
PY
echo "LOGIN_DISCOVERY_COMPLETE:$OUT/runtime_candidates.json"
