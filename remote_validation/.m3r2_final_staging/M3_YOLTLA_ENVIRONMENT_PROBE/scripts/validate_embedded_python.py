#!/usr/bin/env python3
import argparse,re
from pathlib import Path
OPEN=re.compile(r"<<(?P<tabs>-)?\s*(?P<quote>['\"]?)(?P<tag>PY)(?P=quote)(?:\s|$)")
def blocks(path):
 lines=path.read_text(encoding='utf-8').splitlines(keepends=True); out=[]; i=0
 while i<len(lines):
  m=OPEN.search(lines[i])
  if not m:i+=1;continue
  tabs=bool(m.group('tabs')); start=i+2; body=[]; i+=1
  while i<len(lines):
   raw=lines[i].rstrip('\r\n'); compared=raw.lstrip('\t') if tabs else raw
   if compared=='PY':out.append((start,''.join(body)));break
   body.append(lines[i].lstrip('\t') if tabs else lines[i]);i+=1
  else:raise ValueError(f'unterminated Python heredoc: {path}:{start-1}')
  i+=1
 return out
def main():
 p=argparse.ArgumentParser();p.add_argument('files',nargs='+',type=Path);a=p.parse_args();bad=[]
 for path in a.files:
  try:
   for start,source in blocks(path):
    try:compile(source,f'{path}:{start}','exec')
    except SyntaxError as e:bad.append((path,start,start+(e.lineno or 1)-1,e.msg))
  except (OSError,UnicodeError,ValueError) as e:bad.append((path,1,1,str(e)))
 if bad:
  print('EMBEDDED_PYTHON_SYNTAX_ERROR')
  for path,start,line,msg in bad:print(f'file={path} start_line={start} error_line={line} message={msg}')
  return 2
 print('EMBEDDED_PYTHON_SYNTAX_VERIFIED');return 0
raise SystemExit(main())
