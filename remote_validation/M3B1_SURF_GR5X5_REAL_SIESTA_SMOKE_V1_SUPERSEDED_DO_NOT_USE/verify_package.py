#!/usr/bin/env python3
import hashlib,json,re,subprocess,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parent
def fail(code,detail):raise SystemExit(f'{code}:{detail}')
manifest=json.loads((root/'package_manifest.json').read_text(encoding='utf-8'))
record=(root/'package_manifest.sha256').read_text().strip().split(None,1)
if len(record)!=2 or record[1]!='package_manifest.json' or hashlib.sha256((root/'package_manifest.json').read_bytes()).hexdigest()!=record[0]:fail('MANIFEST_HASH_MISMATCH','package_manifest.json')
seen=set()
for line in (root/'checksums.sha256').read_text().splitlines():
 match=re.fullmatch(r'([0-9a-f]{64})\s+(.+)',line)
 if not match:fail('INVALID_CHECKSUM_RECORD',line)
 digest,name=match.groups(); path=Path(name)
 if path.is_absolute() or '..' in path.parts or name in seen:fail('UNSAFE_PACKAGE_PATH',name)
 seen.add(name); target=root.joinpath(*path.parts)
 if not target.is_file() or target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:fail('PACKAGE_HASH_MISMATCH',name)
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.relative_to(root).parts[0] not in {'evidence','results','work'}}-{'checksums.sha256'}
if seen!=actual:fail('CHECKSUM_COVERAGE_MISMATCH',str(sorted(actual^seen)))
pseudo=manifest['pseudopotential']; target=root/'pseudopotentials'/pseudo['filename']
if hashlib.sha256(target.read_bytes()).hexdigest()!=pseudo['packaged_sha256']:fail('PSEUDOPOTENTIAL_HASH_MISMATCH',pseudo['filename'])
geometry=manifest['geometry']; target=root/'geometry'/Path(geometry['source_geometry_path']).name
if hashlib.sha256(target.read_bytes()).hexdigest()!=geometry['packaged_sha256']:fail('GEOMETRY_HASH_MISMATCH',target.name)
for path in root.rglob('*'):
 if path.is_symlink():fail('UNSAFE_PACKAGE_SYMLINK',str(path.relative_to(root)))
 if path.is_file() and path.suffix in {'.sh','.slurm'}:
  result=subprocess.run(['bash','-n',path.relative_to(root).as_posix()],cwd=root,capture_output=True,text=True)
  if result.returncode:fail('BASH_SYNTAX_FAILURE',result.stderr.strip())
print('M3B1_PACKAGE_HASHES_VERIFIED')
print('M3B1_PSEUDOPOTENTIAL_VERIFIED')
print('M3B1_GEOMETRY_VERIFIED')
print('M3B1_PACKAGE_VERIFIED')
