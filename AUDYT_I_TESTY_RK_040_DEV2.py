#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-pass static code audit + exhaustive CI test runner for RK 0.4.0-dev2.

Report scans all repository text sources including historical installers and tests;
external binaries, Qt runtime visuals and user data are NOT represented as audited
or proven correct. Tests are sequential so their fixed test ports do not collide.
"""
from __future__ import annotations
import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

EXCLUDE={'.git','.github','.venv','venv','dist','build','Data','__pycache__',
         '.rk_backup_before_040','.rk_backup_before_040_dev2','.rk_audit_patch_backup_040_dev2',
         '.rk_inbox_fix_backup_0310'}
EXTS={'.py','.pyw','.js','.css','.json','.md','.txt','.yml','.yaml','.bat','.vbs','.sh','.spec','.webmanifest'}


def source_files(root:Path):
    for path in root.rglob('*'):
        if path.is_file() and path.suffix.lower() in EXTS and not any(p in EXCLUDE or p.startswith('.rk_backup') for p in path.relative_to(root).parts):
            yield path


def audit(root:Path)->dict:
    files=sorted(source_files(root))
    report={'version':'0.4.0-dev3','files_scanned':len(files),'py_files':0,'lines_scanned':0,
            'syntax_errors':[],'js_syntax_errors':[],'top_functions':[],
            'warnings':[],'binary_assets_not_parsed':[], 'test_files':[]}
    fn_sizes=[]
    node=shutil.which('node')
    for f in files:
        rel=f.relative_to(root).as_posix()
        try:src=f.read_text(encoding='utf-8-sig')
        except (UnicodeDecodeError,OSError) as exc:
            report['warnings'].append(f'{rel}: nie można odczytać tekstu ({exc})')
            continue
        report['lines_scanned']+=len(src.splitlines())
        if f.name.startswith('TEST_') and f.suffix=='.py':report['test_files'].append(rel)
        if f.suffix in ('.py','.pyw'):
            report['py_files']+=1
            try: tree=ast.parse(src,filename=rel)
            except SyntaxError as exc:
                report['syntax_errors'].append(f'{rel}:{exc.lineno}: {exc.msg}')
                continue
            for n in ast.walk(tree):
                if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
                    fn_sizes.append({'file':rel,'name':n.name,'lines':n.end_lineno-n.lineno+1,'line':n.lineno})
        elif f.suffix=='.js' and node:
            proc=subprocess.run([node,'--check',str(f)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
            if proc.returncode:
                report['js_syntax_errors'].append(f'{rel}: {proc.stderr.strip()[-1300:]}')
    report['top_functions']=sorted(fn_sizes,key=lambda x:x['lines'],reverse=True)[:20]
    for key in ('rk_core/schema.py','rk_core/sync_atomic.py','rk_domains/inbox/worker.py',
                'rk_core/request_security.py','rk_core/cloud_security.py','assets/rk_csrf.js'):
        if not (root/key).exists():report['warnings'].append('Brak modułu dev2: '+key)
    for text in ('assets/ocr/tessdata/eng.traineddata','assets/ocr/tessdata/pol.traineddata',
                 'assets/rk_kancelaria.ico','assets/rk_kancelaria_logo.png'):
        if (root/text).is_file():report['binary_assets_not_parsed'].append(text)
    if (root/'main.yml').is_file() and (root/'.github/workflows/main.yml').is_file():
        report['warnings'].append('main.yml w głównym katalogu jest historyczną kopią; aktywny workflow jest w .github/workflows/main.yml.')
    return report


def run_tests(root:Path,report:dict,log_dir:Path)->bool:
    log_dir.mkdir(parents=True,exist_ok=True)
    test_files=sorted(root.glob('TEST_*.py'))
    outcomes=[]
    for path in test_files:
        started=time.monotonic()
        print('TEST:',path.name,flush=True)
        try:
            proc=subprocess.run([sys.executable,str(path)],cwd=root,stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,timeout=120,encoding='utf-8',errors='replace')
            status='PASS' if proc.returncode==0 else f'FAIL({proc.returncode})'
            content=proc.stdout
        except subprocess.TimeoutExpired as exc:
            status='TIMEOUT';content=(exc.stdout or b'')
            if isinstance(content,bytes):content=content.decode('utf-8','replace')
            content+='\nPrzekroczono limit 120 sekund; test został przerwany.'
        elapsed=round(time.monotonic()-started,2)
        path_log=log_dir/(path.stem+'.log')
        path_log.write_text(content,encoding='utf-8',errors='replace')
        outcomes.append({'file':path.name,'result':status,'elapsed_seconds':elapsed,'log':path_log.relative_to(root).as_posix()})
        print('  '+status+f' ({elapsed}s)',flush=True)
        if status!='PASS':
            # Avoid uploading huge source dumps in the Actions console.
            print('  === LAST 35 LINES ===')
            for line in content.splitlines()[-35:]:print('  '+line[:330])
    report['test_results']=outcomes
    report['tests_passed']=sum(x['result']=='PASS' for x in outcomes)
    report['tests_failed']=len(outcomes)-report['tests_passed']
    return report['tests_failed']==0


def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',default='.')
    parser.add_argument('--out',default='RAPORT_AUDYT_040_DEV2.json')
    parser.add_argument('--skip-tests',action='store_true')
    args=parser.parse_args()
    root=Path(args.root).resolve()
    report=audit(root)
    ok=not report['syntax_errors'] and not report['js_syntax_errors']
    if not args.skip_tests:
        ok=run_tests(root,report,root/'CI_AUDYT_LOGI') and ok
    out=root/args.out
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"AUDYT: {report['files_scanned']} tekstowych źródeł, {report['py_files']} plików Python, "
          f"{report['lines_scanned']} linii; błędy składni: "
          f"{len(report['syntax_errors'])+len(report['js_syntax_errors'])}")
    if not args.skip_tests:
        print(f"TESTY: {report['tests_passed']} OK, {report['tests_failed']} FAILED")
    for error in (report['syntax_errors']+report['js_syntax_errors']):print('ERROR:',error)
    print('Pełny raport:',out)
    return 0 if ok else 1


if __name__=='__main__':raise SystemExit(main())
