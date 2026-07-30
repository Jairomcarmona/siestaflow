#!/usr/bin/env python3
import hashlib,json,re,subprocess
from pathlib import Path,PurePosixPath
root=Path(__file__).resolve().parent
def fail(code,detail): raise SystemExit(f'{code}:{detail}')
def packaged(value):
 if not isinstance(value,str) or '\\' in value or re.match(r'^[A-Za-z]:',value): fail('UNSAFE_PACKAGED_PATH',str(value))
 p=PurePosixPath(value)
 if p.is_absolute() or '..' in p.parts or not p.parts: fail('UNSAFE_PACKAGED_PATH',value)
 candidate=root.joinpath(*p.parts)
 if candidate.is_symlink(): fail('UNSAFE_PACKAGE_SYMLINK',value)
 target=candidate.resolve()
 try: target.relative_to(root.resolve())
 except ValueError: fail('PACKAGED_PATH_OUTSIDE_ROOT',value)
 if not target.is_file() or target.is_symlink(): fail('PACKAGED_FILE_MISSING',value)
 return target
manifest_path=root/'package_manifest.json'; manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
record=(root/'package_manifest.sha256').read_text().strip().split(None,1)
if len(record)!=2 or record[1]!='package_manifest.json' or hashlib.sha256(manifest_path.read_bytes()).hexdigest()!=record[0]: fail('MANIFEST_HASH_MISMATCH','package_manifest.json')
seen=set()
for line in (root/'checksums.sha256').read_text().splitlines():
 match=re.fullmatch(r'([0-9a-f]{64})\s+(.+)',line)
 if not match: fail('INVALID_CHECKSUM_RECORD',line)
 digest,name=match.groups()
 if name in seen: fail('DUPLICATE_CHECKSUM_RECORD',name)
 seen.add(name); target=packaged(name)
 if hashlib.sha256(target.read_bytes()).hexdigest()!=digest: fail('PACKAGE_HASH_MISMATCH',name)
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.relative_to(root).parts[0] not in {'evidence','results','work','generated'}}-{'checksums.sha256'}
if seen!=actual: fail('CHECKSUM_COVERAGE_MISMATCH',str(sorted(actual^seen)))
for key in ('geometry','fdf','pseudopotential'):
 item=manifest[key]; target=packaged(item['packaged_path'])
 if hashlib.sha256(target.read_bytes()).hexdigest()!=item['packaged_sha256']: fail(key.upper()+'_HASH_MISMATCH',item['packaged_path'])
for path in root.rglob('*'):
 if path.is_symlink(): fail('UNSAFE_PACKAGE_SYMLINK',str(path.relative_to(root)))
 if path.is_file() and path.suffix in {'.sh','.slurm'}:
  result=subprocess.run(['bash','-n',path.relative_to(root).as_posix()],cwd=root,capture_output=True,text=True)
  if result.returncode: fail('BASH_SYNTAX_FAILURE',result.stderr.strip())
print('CLEAN_LINUX_EXTRACTION_VERIFICATION_PASS')
print('PORTABLE_MANIFEST_PASS')
print('M3B1_PACKAGE_VERIFIED')
