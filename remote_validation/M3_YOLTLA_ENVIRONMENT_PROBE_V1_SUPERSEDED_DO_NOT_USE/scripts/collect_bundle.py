#!/usr/bin/env python3
import argparse,datetime,hashlib,json,os,shutil,tarfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--package-root',type=Path,required=True);a=p.parse_args();root=a.package_root.resolve(); stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'); stage=root/f'.m3_collect_{stamp}'
if stage.exists(): raise SystemExit('REFUSING_OVERWRITE:'+str(stage))
required=['login_probe','scheduler_probe','slurm_accounting','pseudo_verification','stdout','stderr']; missing=[x for x in required if not (root/'evidence'/x).exists()]
if missing: raise SystemExit('MISSING_EVIDENCE:'+','.join(missing))
for name in ['login_probe','scheduler_probe','slurm_accounting','pseudo_verification','stdout','stderr']: shutil.copytree(root/'evidence'/name,stage/name)
outs=sorted((stage/'stdout').glob('scheduler-*.out')); errs=sorted((stage/'stderr').glob('scheduler-*.err'))
if not outs or not errs: raise SystemExit('MISSING_SCHEDULER_STDOUT_OR_STDERR')
shutil.copy2(outs[-1],stage/'stdout/scheduler.out'); shutil.copy2(errs[-1],stage/'stderr/scheduler.err')
for name in ['siesta_discovery','mpi_discovery','filesystem']:(stage/name).mkdir(parents=True)
login=json.loads((stage/'login_probe/summary.json').read_text()); sched=json.loads((stage/'scheduler_probe/summary.json').read_text())
commands=login.get('commands',{}); observed=login.get('observed_at')
(stage/'siesta_discovery/summary.json').write_text(json.dumps({'observed_at':observed,'executable':commands.get('siesta') or commands.get('siesta-5.4.2'),'version':(login.get('siesta_version_candidates') or [None])[0],'version_evidence':'controlled module metadata' if login.get('siesta_version_candidates') else None,'status':login.get('siesta_discovery_status')},sort_keys=True,indent=2)+'\n')
launcher=next((x for x in ['mpiexec.hydra','srun','mpiexec','mpirun'] if commands.get(x)),None)
(stage/'mpi_discovery/summary.json').write_text(json.dumps({'observed_at':observed,'launcher':launcher,'launcher_command':commands.get(launcher) if launcher else None,'version':None},sort_keys=True,indent=2)+'\n')
env=login.get('environment',{}); scratch=env.get('SCRATCH') or env.get('TMPDIR')
(stage/'filesystem/summary.json').write_text(json.dumps({'observed_at':observed,'project_root':str(root),'project_root_visible':root.is_dir(),'scratch_root':scratch,'scratch_writable':bool(scratch and Path(scratch).is_dir() and os.access(scratch,os.W_OK))},sort_keys=True,indent=2)+'\n')
manifest={'probe_id':'M3_YOLTLA_ENVIRONMENT_PROBE','evidence_type':'REAL_REMOTE_ENVIRONMENT_PROBE','scientific_calculation_performed':False,'synthetic':False,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(stage/'results_manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n'); h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest(); (stage/'results_manifest.sha256').write_text(f"{h(stage/'results_manifest.json')}  results_manifest.json\n")
files=sorted(x for x in stage.rglob('*') if x.is_file()); (stage/'checksums.sha256').write_text(''.join(f'{h(x)}  {x.relative_to(stage).as_posix()}\n' for x in files))
bundle=root/f'M3_YOLTLA_ENVIRONMENT_RESULTS_{stamp}.tar.gz'
if bundle.exists(): raise SystemExit('REFUSING_OVERWRITE:'+str(bundle))
with tarfile.open(bundle,'w:gz',format=tarfile.PAX_FORMAT) as t:
 for x in sorted(stage.rglob('*')):
  info=t.gettarinfo(str(x),arcname=x.relative_to(stage).as_posix()); info.uid=info.gid=0; info.uname=info.gname=''; info.mtime=0
  if x.is_file():
   with x.open('rb') as f:t.addfile(info,f)
  else:t.addfile(info)
print(bundle)
