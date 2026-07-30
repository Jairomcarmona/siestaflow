#!/usr/bin/env python3
import tarfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
required=[root/'package_manifest.json',root/'evidence/execution/summary.json',root/'evidence/accounting/summary.json',root/'evidence/result_summary.json',root/'results/siesta.out',root/'results/siesta.err']
missing=[str(p.relative_to(root)) for p in required if not p.is_file()]
if missing:raise SystemExit('MISSING_RESULT_EVIDENCE:'+','.join(missing))
out=root/'M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE_RESULTS.tar.gz'
if out.exists():raise SystemExit('REFUSING_OVERWRITE:'+str(out))
with tarfile.open(out,'x:gz') as archive:
 for base in ('package_manifest.json','generated/runtime_selection.json','evidence','results'):
  path=root/base
  if path.exists():archive.add(path,arcname=base,recursive=True)
print(out)
