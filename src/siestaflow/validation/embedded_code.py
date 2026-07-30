"""Extract and compile Python heredocs without executing their contents."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_OPEN = re.compile(r"<<(?P<tabs>-)?\s*(?P<quote>['\"]?)(?P<tag>PY)(?P=quote)(?:\s|$)")


@dataclass(frozen=True)
class EmbeddedPythonBlock:
    path: Path
    start_line: int
    end_line: int
    source: str


@dataclass(frozen=True)
class EmbeddedPythonDiagnostic:
    path: Path
    start_line: int
    error_line: int
    message: str


def extract_python_heredocs(path: Path) -> tuple[EmbeddedPythonBlock, ...]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    blocks: list[EmbeddedPythonBlock] = []
    index = 0
    while index < len(lines):
        match = _OPEN.search(lines[index])
        if not match:
            index += 1
            continue
        strip_tabs = bool(match.group("tabs"))
        delimiter = match.group("tag")
        start = index + 2
        body: list[str] = []
        index += 1
        while index < len(lines):
            candidate = lines[index].rstrip("\r\n")
            compared = candidate.lstrip("\t") if strip_tabs else candidate
            if compared == delimiter:
                blocks.append(EmbeddedPythonBlock(path, start, index + 1, "".join(body)))
                break
            body.append(lines[index].lstrip("\t") if strip_tabs else lines[index])
            index += 1
        else:
            raise ValueError(f"unterminated Python heredoc: {path}:{start - 1}")
        index += 1
    return tuple(blocks)


def validate_files(paths: Iterable[Path]) -> tuple[EmbeddedPythonDiagnostic, ...]:
    diagnostics: list[EmbeddedPythonDiagnostic] = []
    for path in paths:
        try:
            blocks = extract_python_heredocs(path)
        except (OSError, UnicodeError, ValueError) as exc:
            diagnostics.append(EmbeddedPythonDiagnostic(path, 1, 1, str(exc)))
            continue
        for block in blocks:
            filename = f"{block.path}:{block.start_line}"
            try:
                compile(block.source, filename, "exec")
            except SyntaxError as exc:
                relative = exc.lineno or 1
                diagnostics.append(EmbeddedPythonDiagnostic(
                    block.path, block.start_line, block.start_line + relative - 1,
                    exc.msg,
                ))
    return tuple(diagnostics)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile Python heredocs without executing them")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    diagnostics = validate_files(args.files)
    if diagnostics:
        print("EMBEDDED_PYTHON_SYNTAX_ERROR")
        for item in diagnostics:
            print(f"file={item.path} start_line={item.start_line} error_line={item.error_line} message={item.message}")
        return 2
    print("EMBEDDED_PYTHON_SYNTAX_VERIFIED")
    return 0


STANDALONE_VALIDATOR = r'''#!/usr/bin/env python3
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
'''


if __name__ == "__main__":
    raise SystemExit(main())
