#!/usr/bin/env python3
import hashlib,json,os,re,subprocess,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
required={'README_RUN.md','EXACT_COMMANDS.md','PROBE_CHECKLIST.md','expected_evidence.json','probe_manifest.json','probe_manifest.sha256','checksums.sha256','run_login_probe.sh','prepare_scheduler_probe.py','submit_environment_probe.slurm','inspect_probe_job.sh','collect_probe_results.sh','scripts/probe_common.sh','scripts/build_login_summary.py','scripts/scheduler_resolution.py','scripts/verify_pseudos.py','scripts/collect_bundle.py','scripts/validate_embedded_python.py'}
def fail(code,detail):raise SystemExit(f'{code}:{detail}')
for name in required:
 path=root/name
 if not path.is_file() or path.is_symlink() or not os.access(path,os.R_OK):fail('PACKAGE_STRUCTURE_FAILURE',name)
try:manifest=json.loads((root/'probe_manifest.json').read_text(encoding='utf-8'))
except (OSError,json.JSONDecodeError) as exc:fail('PROBE_MANIFEST_INVALID',str(exc))
if manifest.get('package_revision')!=3 or manifest.get('reproducibility_epoch')!='M3_STATIC_V3' or manifest.get('supersedes')!='M3_STATIC_V2':fail('PROBE_MANIFEST_REVISION_INVALID','expected V3')
record=(root/'probe_manifest.sha256').read_text(encoding='utf-8').strip().split(None,1)
if len(record)!=2 or record[1].lstrip('*')!='probe_manifest.json' or hashlib.sha256((root/'probe_manifest.json').read_bytes()).hexdigest()!=record[0]:fail('PROBE_MANIFEST_HASH_FAILURE','probe_manifest.json')
seen=set()
for number,line in enumerate((root/'checksums.sha256').read_text(encoding='utf-8').splitlines(),1):
 match=re.fullmatch(r'([0-9a-f]{64})\s+(.+)',line)
 if not match:fail('PACKAGE_HASH_FAILURE',f'invalid record line {number}')
 digest,name=match.groups();parts=Path(name).parts
 if Path(name).is_absolute() or '..' in parts or name in seen:fail('PACKAGE_PATH_FAILURE',name)
 seen.add(name);path=root.joinpath(*parts)
 try:path.resolve().relative_to(root)
 except ValueError:fail('PACKAGE_PATH_FAILURE',name)
 if not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:fail('PACKAGE_HASH_FAILURE',name)
actual={path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}-{'checksums.sha256'}
if seen!=actual:fail('PACKAGE_STRUCTURE_FAILURE','checksum coverage mismatch')
for name,digest in manifest.get('files',{}).items():
 path=root.joinpath(*Path(name).parts)
 if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:fail('PROBE_MANIFEST_FILE_HASH_FAILURE',name)
assignment=re.compile(r'(?im)^\s*(?:export\s+)?(?:PASSWORD|TOKEN|SECRET|AWS_SECRET_ACCESS_KEY|COOKIE|CREDENTIAL)\s*=\s*[^\s#][^\r\n]*$')
private_key=re.compile(r'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----')
for path in root.rglob('*'):
 if path.is_symlink():fail('PACKAGE_PATH_FAILURE',str(path.relative_to(root)))
 if not path.is_file():continue
 if path.suffix.lower() in {'.fdf','.psml','.psf','.xyz'}:fail('FORBIDDEN_SCIENTIFIC_FILE',str(path.relative_to(root)))
 try:text=path.read_text(encoding='utf-8')
 except UnicodeDecodeError:continue
 for number,line in enumerate(text.splitlines(),1):
  if assignment.search(line) or private_key.search(line):fail('PACKAGE_SECRET_FAILURE',f'{path.relative_to(root)}:{number}')
python_files=sorted(str(path) for path in root.rglob('*.py'))
shell_paths=sorted((path for path in root.rglob('*') if path.suffix in {'.sh','.slurm'}),key=str)
with tempfile.TemporaryDirectory() as cache:
 env=dict(os.environ);env['PYTHONPYCACHEPREFIX']=cache
 result=subprocess.run([sys.executable,'-m','py_compile',*python_files],capture_output=True,text=True,env=env,check=False)
 if result.returncode:fail('DIRECT_PYTHON_SYNTAX_FAILURE',(result.stderr or result.stdout).strip())
for path in shell_paths:
 result=subprocess.run(['bash','-n',path.relative_to(root).as_posix()],cwd=root,capture_output=True,text=True,check=False)
 if result.returncode:fail('BASH_SYNTAX_FAILURE',f'{path}:{(result.stderr or result.stdout).strip()}')
result=subprocess.run([sys.executable,str(root/'scripts/validate_embedded_python.py'),*[str(path) for path in shell_paths]],capture_output=True,text=True,check=False)
if result.returncode:fail('EMBEDDED_PYTHON_SYNTAX_FAILURE',(result.stdout+result.stderr).strip())
print('M3_PACKAGE_HASHES_VERIFIED')
print('M3_PACKAGE_RUNTIME_SYNTAX_VERIFIED')
print('M3_PACKAGE_STRUCTURE_VERIFIED')
