#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zależności, duże metody i moduły RK 0.4; bez dostępu do danych klientów."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

EXCLUDED = {'ZASTOSUJ_040.py'}


def analyze(root: Path) -> dict:
    entries = []
    for path in sorted([root/'app.py'] + list((root/'rk_core').rglob('*.py')) + list((root/'rk_domains').rglob('*.py'))):
        if not path.is_file(): continue
        content=path.read_text(encoding='utf-8')
        tree=ast.parse(content)
        methods=[]
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                length=node.end_lineno - node.lineno + 1
                if length>=60:
                    methods.append({'name':node.name,'lines':length,'start':node.lineno})
        direct_queries=sum(1 for node in ast.walk(tree)
                           if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                           and node.func.attr in ('execute','executemany','executescript'))
        entries.append({'file':path.relative_to(root).as_posix(),'lines':len(content.splitlines()),
                        'sql_calls':direct_queries,'large_methods':sorted(methods,key=lambda x:-x['lines'])[:20]})
    return {'version':'0.4.0-dev5','note':'Wskaźniki utrzymywalności; nie certyfikat bezpieczeństwa.',
            'modules':entries,'total_lines':sum(e['lines'] for e in entries),
            'large_methods_150plus':[(x['file'],m['name'],m['lines']) for x in entries for m in x['large_methods'] if m['lines']>=150]}


def main(argv=None) -> int:
    p=argparse.ArgumentParser()
    p.add_argument('repo',nargs='?',default='.')
    p.add_argument('--out',default='RAPORT_JAKOSCI_040.json')
    args=p.parse_args(argv)
    root=Path(args.repo).resolve();result=analyze(root)
    dest=root/args.out
    dest.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f"RK 0.4: {len(result['modules'])} plików, {result['total_lines']} linii; raport: {dest.name}")
    for file,name,lines in sorted(result['large_methods_150plus'],key=lambda e:-e[2])[:8]:
        print(f'  DO DALSZEGO PODZIAŁU: {file}::{name} ({lines} linii)')
    return 0

if __name__=='__main__':raise SystemExit(main())
