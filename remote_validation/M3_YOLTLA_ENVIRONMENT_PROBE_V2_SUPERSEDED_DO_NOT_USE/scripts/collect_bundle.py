#!/usr/bin/env python3
import argparse,datetime,gzip,hashlib,json,os,re,shutil,tarfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--package-root',type=Path,required=True);p.add_argument('--timestamp');a=p.parse_args()
root=a.package_root.resolve();evidence=root/'evidence';stamp=a.timestamp or datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z',stamp):raise SystemExit('INVALID_TIMESTAMP')
required=['login_probe/summary.json','scheduler_probe/summary.json','slurm_accounting/summary.json','pseudo_verification/summary.json','stdout/login_probe.log','stderr/login_probe.err']
missing=[name for name in required if not (evidence/name).is_file()]
outs=sorted(evidence.glob('stdout/scheduler-*.out'));errs=sorted(evidence.glob('stderr/scheduler-*.err'))
if not outs:missing.append('stdout/scheduler-*.out')
if not errs:missing.append('stderr/scheduler-*.err')
if missing:raise SystemExit('MISSING_EVIDENCE:'+','.join(missing))
for path in evidence.rglob('*'):
 if path.is_symlink():raise SystemExit('UNSAFE_EVIDENCE_SYMLINK:'+str(path))
 try:path.resolve().relative_to(evidence.resolve())
 except ValueError:raise SystemExit('UNSAFE_EVIDENCE_PATH:'+str(path))
bundle=root/f'M3_YOLTLA_ENVIRONMENT_RESULTS_{stamp}.tar.gz';stage=root/f'.m3_collect_{stamp}'
if bundle.exists() or stage.exists():raise SystemExit('REFUSING_OVERWRITE:'+str(bundle if bundle.exists() else stage))
for name in ['login_probe','scheduler_probe','slurm_accounting','pseudo_verification','stdout','stderr']:shutil.copytree(evidence/name,stage/name)
shutil.copy2(outs[-1],stage/'stdout/scheduler.out');shutil.copy2(errs[-1],stage/'stderr/scheduler.err')
for name in ['siesta_discovery','mpi_discovery','filesystem']:(stage/name).mkdir(parents=True)
login=json.loads((stage/'login_probe/summary.json').read_text(encoding='utf-8'));commands=login.get('commands',{});observed=login.get('observed_at')
write=lambda path,data:path.write_text(json.dumps(data,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
write(stage/'siesta_discovery/summary.json',{'observed_at':observed,'executable':commands.get('siesta') or commands.get('siesta-5.4.2'),'version':(login.get('siesta_version_candidates') or [None])[0],'version_evidence':'controlled module metadata' if login.get('siesta_version_candidates') else None,'status':login.get('siesta_discovery_status')})
launcher=next((x for x in ['mpiexec.hydra','srun','mpiexec','mpirun'] if commands.get(x)),None)
write(stage/'mpi_discovery/summary.json',{'observed_at':observed,'launcher':launcher,'launcher_command':commands.get(launcher) if launcher else None,'version':None})
env=login.get('environment',{});scratch=env.get('SCRATCH') or env.get('TMPDIR')
write(stage/'filesystem/summary.json',{'observed_at':observed,'project_root':str(root),'project_root_visible':root.is_dir(),'scratch_root':scratch,'scratch_writable':bool(scratch and Path(scratch).is_dir() and os.access(scratch,os.W_OK))})
write(stage/'results_manifest.json',{'probe_id':'M3_YOLTLA_ENVIRONMENT_PROBE','package_revision':2,'evidence_type':'REAL_REMOTE_ENVIRONMENT_PROBE','scientific_calculation_performed':False,'synthetic':False,'observed_at':observed})
h=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
(stage/'results_manifest.sha256').write_text(f"{h(stage/'results_manifest.json')}  results_manifest.json\n",encoding='utf-8',newline='\n')
files=sorted(path for path in stage.rglob('*') if path.is_file());(stage/'checksums.sha256').write_text(''.join(f'{h(path)}  {path.relative_to(stage).as_posix()}\n' for path in files),encoding='utf-8',newline='\n')
with bundle.open('xb') as raw:
 with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as compressed:
  with tarfile.open(fileobj=compressed,mode='w',format=tarfile.PAX_FORMAT) as archive:
   for path in sorted(stage.rglob('*')):
    info=archive.gettarinfo(str(path),arcname=path.relative_to(stage).as_posix());info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
    if path.is_file():
     with path.open('rb') as stream:archive.addfile(info,stream)
    elif path.is_dir():archive.addfile(info)
shutil.rmtree(stage);print(bundle)
