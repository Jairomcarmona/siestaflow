#!/usr/bin/env python3
import argparse, json
from pathlib import Path
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
associations=[]
for line in (read('sacctmgr_assoc.txt') or '').splitlines():
    parts=[x.strip() for x in line.split('|')]
    if len(parts)>=2 and parts[0] and parts[1]: associations.append({'account':parts[0],'partition':parts[1],'qos':parts[2] if len(parts)>2 and parts[2] else None,'source':'sacctmgr_assoc.txt'})
module_text='\n'.join(filter(None,[read('module_spider_siesta.txt'),read('module_avail_siesta.txt'),read('module_show_siesta.txt')]))
import re
versions=sorted(set(re.findall(r'(?<!\d)(5\.\d+(?:\.\d+)?)(?!\d)',module_text)))
summary={'observed_at':read('observed_at.txt'),'hostname':read('hostname.txt'),'user':read('user.txt'),'system':read('system.txt'),'shell':read('shell.txt'),'module_available':read('module_available.txt')=='true','commands':commands,'environment':environment,'slurm_commands_available':all(commands.get(x) for x in ('sbatch','squeue','sinfo','sacct','scontrol')),'eligible_associations':associations,'module_commands':[],'siesta_module_candidates':(read('module_siesta_candidates.txt') or '').splitlines()[:10],'siesta_version_candidates':versions,'siesta_discovery_status':'SIESTA_EXECUTABLE_DISCOVERED_VERSION_COMMAND_UNVERIFIED' if commands.get('siesta') or commands.get('siesta-5.4.2') else 'SIESTA_EXECUTABLE_NOT_DISCOVERED','scientific_calculation_performed':False}
a.output.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n',encoding='utf-8')
