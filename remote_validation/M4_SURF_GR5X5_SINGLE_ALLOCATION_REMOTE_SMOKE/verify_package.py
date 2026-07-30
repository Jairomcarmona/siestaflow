#!/usr/bin/env python3
import hashlib,json,re,subprocess,sys
from pathlib import Path,PurePosixPath
sys.dont_write_bytecode=True
root=Path(__file__).resolve().parent
def fail(code,detail=''): raise SystemExit(code+(':'+detail if detail else ''))
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
if manifest.get('package_id')!='M4_SURF_GR5X5_SINGLE_ALLOCATION_REMOTE_SMOKE': fail('PACKAGE_ID_MISMATCH')
for name,expected in manifest.get('immutable_files',{}).items():
 p=PurePosixPath(name)
 if p.is_absolute() or '..' in p.parts or '\\' in name: fail('UNSAFE_PATH',name)
 target=root.joinpath(*p.parts)
 if not target.is_file() or target.is_symlink(): fail('MISSING_IMMUTABLE_FILE',name)
 if hashlib.sha256(target.read_bytes()).hexdigest()!=expected: fail('IMMUTABLE_HASH_MISMATCH',name)
seen=set()
for line in (root/'checksums.sha256').read_text(encoding='utf-8').splitlines():
 m=re.fullmatch(r'([0-9a-f]{64})\s+(.+)',line)
 if not m: fail('INVALID_CHECKSUM_LINE',line)
 expected,name=m.groups()
 if name in seen: fail('DUPLICATE_CHECKSUM',name)
 seen.add(name); target=root.joinpath(*PurePosixPath(name).parts)
 if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=expected: fail('CHECKSUM_MISMATCH',name)
mutable={'state','work','results','evidence'}
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.relative_to(root).parts[0] not in mutable and not p.name.startswith('slurm-')}
if actual != seen|{'checksums.sha256'}: fail('CHECKSUM_COVERAGE_MISMATCH',str(sorted(actual^(seen|{'checksums.sha256'}))))
if any(p.is_symlink() for p in root.rglob('*')): fail('PACKAGE_SYMLINK_FORBIDDEN')
sys.path.insert(0,str(root/'runtime'))
from siestaflow.execution.allocation_controller import load_controller_config
load_controller_config(root/'campaign.yaml')
script=(root/'campaign.slurm').read_text(encoding='utf-8')
if re.search(r'^\s*srun\b.*run_worker',script,re.M): fail('CONTROLLER_MUST_NOT_USE_SRUN')
if 'exec python3 "$ROOT/scripts/run_worker.py"' not in script: fail('DIRECT_BATCH_CONTROLLER_MISSING')
for path in (root/'campaign.slurm',root/'scripts/preflight.sh',root/'scripts/inspect_job.sh'):
 result=subprocess.run(['bash','-n',path.relative_to(root).as_posix()],cwd=root,capture_output=True,text=True)
 if result.returncode: fail('BASH_SYNTAX_FAILURE',result.stderr.strip())
print('M4_PACKAGE_VERIFIED')
print('NO_LOGIN_PERSISTENT_PROCESS_REQUIRED')
