#!/usr/bin/env python3
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
expected={'Mn':('Mn.psml','0b97ccd71456e4a7b28316f78ddb30bb1f6a82d9aba386c7fde78090d31c0dc6'),'O':('O.psml','224ded5c59176d9bcb76d19b7a4a68a48d5dffabf8b262f64d5760250e87c35e')}; result={'root':str(a.root),'observed_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}; states=[]
for species,(name,digest) in expected.items():
 candidates=sorted(a.root.rglob(name))[:20] if a.root.is_dir() else []; q=candidates[0] if len(candidates)==1 else a.root/name
 item={'filename':name,'candidate_count':len(candidates),'candidate_path':str(q) if len(candidates)==1 else None,'expected_sha256':digest,'exists':len(candidates)==1 and q.is_file(),'readable':False,'size':None,'sha256':None,'format':'UNKNOWN','format_valid':False,'verified':False}
 if item['exists']:
  try: data=q.read_bytes(); fmt=b'<psml' in data[:8192].lower(); item.update(readable=True,size=len(data),sha256=hashlib.sha256(data).hexdigest(),format='PSML' if fmt else 'UNKNOWN',format_valid=fmt); item['verified']=item['sha256']==digest and len(data)>0 and fmt
  except OSError: pass
 result[species]=item; states.append('VERIFIED' if item['verified'] else 'REVIEW' if len(candidates)>1 else 'MISMATCH' if item['exists'] else 'MISSING')
result['status']='PSEUDOS_MN_O_HASH_VERIFIED' if states==['VERIFIED','VERIFIED'] else 'PSEUDOS_MN_O_HASH_MISMATCH' if 'MISMATCH' in states else 'PSEUDOS_MN_O_REVIEW' if 'REVIEW' in states else 'PSEUDOS_MN_O_MISSING'
if a.output.exists(): raise SystemExit('REFUSING_OVERWRITE:'+str(a.output))
a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n'); print(result['status'])
