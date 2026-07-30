#!/usr/bin/env python3
import argparse, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from scheduler_resolution import model_dicts,parse_sacctmgr_associations,parse_scontrol_partitions,parse_sinfo_partitions
p=argparse.ArgumentParser(); p.add_argument('--raw',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args()
def read(name):
    q=a.raw/name
    return q.read_text(encoding='utf-8',errors='replace').strip() if q.is_file() else None
commands={}
for q in a.raw.glob('command_*.txt'):
    commands[q.stem.removeprefix('command_').replace('_','.')]=read(q.name) or None
environment={}
for line in (read('environment_redacted.txt') or '').splitlines():
    if '=' in line:
        k,v=line.split('=',1); environment[k]=v
observed=read('observed_at.txt')
associations,assoc_diagnostics=parse_sacctmgr_associations(read('sacctmgr_assoc.txt') or '',observed_at=observed)
visible,sinfo_diagnostics=parse_sinfo_partitions(read('sinfo.txt') or '')
policies,scontrol_diagnostics=parse_scontrol_partitions(read('scontrol_partitions.txt') or '')
module_text='\n'.join(filter(None,[read('module_spider_siesta.txt'),read('module_avail_siesta.txt'),read('module_show_siesta.txt')]))
import re
versions=sorted(set(re.findall(r'(?<!\d)(5\.\d+(?:\.\d+)?)(?!\d)',module_text)))
summary={'observed_at':observed,'hostname':read('hostname.txt'),'user':read('user.txt'),'system':read('system.txt'),'shell':read('shell.txt'),'module_available':read('module_available.txt')=='true','commands':commands,'environment':environment,'slurm_commands_available':all(commands.get(x) for x in ('sbatch','squeue','sinfo','sacct','scontrol')),'eligible_associations':model_dicts(associations),'visible_partitions':model_dicts(visible),'partition_policies':model_dicts(policies),'scheduler_diagnostics':assoc_diagnostics+sinfo_diagnostics+scontrol_diagnostics,'module_commands':[],'siesta_module_candidates':(read('module_siesta_candidates.txt') or '').splitlines()[:10],'siesta_version_candidates':versions,'siesta_discovery_status':'SIESTA_EXECUTABLE_DISCOVERED_VERSION_COMMAND_UNVERIFIED' if commands.get('siesta') or commands.get('siesta-5.4.2') else 'SIESTA_EXECUTABLE_NOT_DISCOVERED','scientific_calculation_performed':False}
a.output.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n',encoding='utf-8')
