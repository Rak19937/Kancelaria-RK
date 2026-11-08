#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Non-destructive repository-wide static audit for RK KANCELARIA.

Checks ALL Python sources, tracked file inventory, the CI topology and several
families of high-risk idioms. It never runs arbitrary repository code and never
reads or copies customer data. Report findings are triaged, NOT a certificate
that a program has no bugs. Only objectively demonstrable critical conditions
fail the audit. Heuristic patterns are findings for manual verification.
"""
from __future__ import annotations
import argparse
import ast
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED={'.git','.venv','venv','build','dist','__pycache__','.pytest_cache','.mypy_cache'}
SENSITIVE_SUFFIXES={'.sqlite','.sqlite3','.sqlite3-wal','.sqlite3-shm','.pfx','.p12','.pem','.key'}
FINDINGS=(
    ('SHELL_TRUE','high',re.compile(r'\bshell\s*=\s*True\b'),
     'Uruchamianie powloki z argumentami — sprawdz wstrzykniecie polecen.'),
    ('EVAL_OR_EXEC','high',re.compile(r'(?<![.\w])(?:eval|exec)\s*\('),
     'Dynamiczne wykonanie kodu — sprawdz pochodzenie danych.'),
    ('PICKLE_DESERIALIZATION','high',re.compile(r'\bpickle\.(?:load|loads)\s*\('),
     'Deserializacja pickle — niedopuszczalna na niezaufanych plikach.'),
    ('TEMP_MKTEMP','medium',re.compile(r'\btempfile\.mktemp\s*\('),
     'Niezabezpieczone tworzenie tymczasowej nazwy pliku.'),
    ('BROAD_EXCEPT_PASS','medium',re.compile(r'except\s+(?:Exception|BaseException)\s*:\s*(?:pass\b|return\s+None\b)'),
     'Wyjatek pominiety bez diagnostyki — mozliwy ukryty blad.'),
    ('SQL_DYNAMIC','medium',re.compile(r'(?i)(?:SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\b[^\n]{0,180}(?:\{[^}]+\}|\.format\s*\()'),
     'SQL budowany dynamicznie — potwierdz, ze identyfikatory sa biale-listowane.'),
)


def _walk_files(root:Path):
    for f in root.rglob('*'):
        if not f.is_file():continue
        if any(p in EXCLUDED for p in f.relative_to(root).parts):continue
        yield f


def _tracked(root:Path):
    try:
        proc=subprocess.run(['git','ls-files','-z'],cwd=root,capture_output=True,check=True,timeout=20)
        return [Path(s.decode('utf-8','replace')) for s in proc.stdout.split(b'\0') if s]
    except (OSError,subprocess.SubprocessError):
        return [f.relative_to(root) for f in _walk_files(root)]


def _f(out,code,severity,path,line=0,detail='',note=''):
    out.append({'code':code,'severity':severity,'file':str(path).replace('\\','/'),
                'line':line,'detail':detail[:260],'recommendation':note[:360]})


def run(root:Path, out:Path|None=None):
    root=root.resolve()
    if not (root/'app.py').exists():raise ValueError('Podaj glowny katalog repo z app.py')
    files=list(_walk_files(root))
    py=sorted((f for f in files if f.suffix.lower() in ('.py','.pyw')),
              key=lambda p:p.as_posix())
    findings=[];parsed=0;source_lines=0
    for f in py:
        rel=f.relative_to(root)
        try:s=f.read_text('utf-8')
        except (OSError,UnicodeError) as e:
            _f(findings,'SOURCE_UNREADABLE','critical',rel,detail=type(e).__name__)
            continue
        source_lines+=s.count('\n')+1
        try:
            tree=ast.parse(s,filename=str(rel));parsed+=1
        except SyntaxError as e:
            _f(findings,'PYTHON_SYNTAX','critical',rel,e.lineno or 0,str(e.msg),
               'Popraw skladnie przed jakimkolwiek buildem.')
            continue
        # Functions with the same definition in one lexical class/module scope.
        # Nested branches of the same function are intentionally not traversed here.
        scopes=[tree]
        while scopes:
            node=scopes.pop()
            definitions=[(n.name,n.lineno) for n in node.body
                         if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
            seen={}
            for name,line in definitions:
                if name in seen:
                    _f(findings,'SHADOWED_DEFINITION','medium',rel,line,
                       f'{name} (poprzednia linia {seen[name]})',
                       'Pozniejsza definicja przyslania wczesniejsza.')
                else:seen[name]=line
            scopes.extend(n for n in node.body if isinstance(n,ast.ClassDef))
        for code,sev,regex,note in FINDINGS:
            lines=s.splitlines()
            for i,line in enumerate(lines,1):
                if regex.search(line) and not line.lstrip().startswith('#'):
                    _f(findings,code,sev,rel,i,line.strip(),note)
        # Dangerously broad excepts are warnings only; many recovery sections
        # properly re-raise and must not be treated as vulnerabilities by regex.
        for node in ast.walk(tree):
            if not isinstance(node,ast.ExceptHandler) or node.type is not None:continue
            body=node.body
            if len(body)==1 and isinstance(body[0],ast.Pass):
                _f(findings,'BARE_EXCEPT_PASS','medium',rel,node.lineno,
                   'except: pass','Przyjzyj sie, czy blad nie jest bezpowrotnie ukrywany.')
    tracked=_tracked(root)
    tracked_set={p.as_posix() for p in tracked}
    for rel in sorted(tracked):
        path=rel.as_posix();name=rel.name.lower()
        if any(x in EXCLUDED for x in rel.parts):
            if '__pycache__' in rel.parts:
                _f(findings,'TRACKED_PYCACHE','low',rel,
                   detail='Zbedny wygenerowany plik .pyc w historii Git.',
                   note='Usun z indeksu Git; nie wgrywaj skompilowanych cache.')
            continue
        if name.endswith(tuple(SENSITIVE_SUFFIXES)) and not name.endswith('.example'):
            _f(findings,'SENSITIVE_FILE_TRACKED','critical',rel,
               detail='W repo sledzony jest potencjalnie poufny typ pliku.',
               note='Usun plik z historii Git i rotuj ujawnione klucze, jesli to konieczne.')
        if (name=='.env' or name.startswith('.env.') and not name.endswith('.example')):
            _f(findings,'ENV_FILE_TRACKED','critical',rel,
               detail='Potencjalny plik konfiguracji z haslami w Git.',
               note='Nie przechowuj danych dostepowych w repozytorium.')
    if '.github/workflows/main.yml' in tracked_set and 'main.yml' in tracked_set:
        _f(findings,'DUPLICATE_WORKFLOW_NAME','low','main.yml',
           detail='Istnieje tez root/main.yml: sam w sobie nie uruchamia GitHub Actions.',
           note='Rozwaz usuniecie historycznego pliku, by uniknac pomylek.')
    if (root/'.github/workflows/main.yml').is_file() and (root/'.github/workflows/aktualizacja-dev5.yml').is_file():
        manual=(root/'.github/workflows/main.yml').read_text('utf-8')
        auto=(root/'.github/workflows/aktualizacja-dev5.yml').read_text('utf-8')
        if 'push:' in manual and 'push:' in auto:
            _f(findings,'DUPLICATE_PUSH_BUILD','medium','.github/workflows',
               detail='Dwa workflow reagujace na push moga uruchamiac przestarzale testy i przeciwne migracje.',
               note='Zostaw tylko jeden automatyczny pipeline; drugi manualny.')
        if re.search(r'git add[^\n]*\.github/workflows',auto):
            _f(findings,'WORKFLOW_PERMISSION_PUSH','high','.github/workflows/aktualizacja-dev5.yml',
               detail='Bot probuje zapisac plik workflow bez uprawnienia workflows.',
               note='Workflow uploaduj recznie i nie dodawaj go do git add w CI.')
    if not (root/'RK_KANCELARIA_PORTABLE.spec').exists():
        _f(findings,'PORTABLE_SPEC_MISSING','critical','RK_KANCELARIA_PORTABLE.spec',
           detail='Brak pliku do budowy EXE')
    by_code=Counter(x['code'] for x in findings)
    report={'title':'RK KANCELARIA — repo-wide static audit',
            'generated_utc':datetime.now(timezone.utc).isoformat(),
            'files_checked':len(files), 'tracked_files':len(tracked),
            'python_files':len(py), 'python_syntax_valid':parsed,
            'python_lines':source_lines,
            'important_limitations':[
                'Audyt statyczny wykrywa typowe ryzyka, nie wszystkie mozliwe usterki.',
                'Raport nie zastępuje testow GUI, wielu uzytkownikow, migracji na prawdziwej bazie ani przegladu bezpieczenstwa.',
                'Wynik kompilacji/testow GitHub Actions jest osobnym wymogiem wydania.'
            ],
            'counts':dict(Counter(x['severity'] for x in findings)),
            'by_code':dict(by_code),
            'critical_count':sum(x['severity']=='critical' for x in findings),
            'findings':findings[:2000],
            'truncated_findings':max(0,len(findings)-2000)}
    if out:
        out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--root',type=Path,default=Path('.'))
    cli.add_argument('--out',type=Path,default=Path('RAPORT_DEV5_AUDYT_REPO.json'))
    a=cli.parse_args()
    report=run(a.root,a.out)
    print(f"Przeskanowano plikow: {report['files_checked']}; Python: {report['python_files']}; ",
          f"skladnia OK: {report['python_syntax_valid']}; krytyczne: {report['critical_count']};",
          f"ostrzezenia: {len(report['findings'])-report['critical_count']}")
    print(f"Raport: {a.out}")
    if report['critical_count']:raise SystemExit(1)
