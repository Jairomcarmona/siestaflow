#!/usr/bin/env python3
import hashlib,re
from pathlib import Path
root=Path(__file__).resolve().parent; bad=[]
for line in (root/'checksums.sha256').read_text().splitlines():
 m=re.fullmatch(r'([0-9a-f]{64})\s+(.+)',line)
 if not m: bad.append('INVALID_RECORD'); continue
 d,n=m.groups(); p=root/n
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=d: bad.append(n)
if bad: raise SystemExit('PACKAGE_HASH_FAILURE:'+','.join(bad))
for p in root.rglob('*'):
 if p.is_file() and p.suffix.lower() in {'.fdf','.psml','.psf','.xyz'}: raise SystemExit('FORBIDDEN_SCIENTIFIC_FILE:'+str(p))
print('M3_PACKAGE_HASHES_VERIFIED')
