#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bezpieczna poprawka czytelności przesyłania pliku do skrzynki RK KANCELARIA 0.3.10.

Nie zmienia bazy danych ani mechanizmu OCR; pokazuje stan trwającej operacji,
weryfikuje plik jeszcze w przeglądarce i zapobiega ponownemu wysłaniu formularza.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

BASE_SHA = {
    'rk_inbox.py': '44cc6bfd70151814e3bb4d891cc1d20199dfb11a',
    'assets/rk_app.js': 'c977185926bc242281a347d7e67bc842e12b5456',
}
MARKER = 'data-rk-inbox-upload="1"'
JS_MARKER = 'RK-INBOX-FEEDBACK-0310'


def sha_git(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def once(src: str, old: str, new: str, name: str) -> str:
    count = src.count(old)
    if count != 1:
        raise RuntimeError(f'{name}: oczekiwano jednej kotwicy, wykryto {count}. Bez zmian.')
    return src.replace(old, new, 1)


def fix_inbox(src: str) -> str:
    src = once(src,
        "<form method='post' action='/inbox/upload' enctype='multipart/form-data'>",
        "<form method='post' action='/inbox/upload' enctype='multipart/form-data' data-rk-inbox-upload=\"1\">",
        'formularz skrzynki')
    src = once(src,
        "<button class='btn primary'>Odczytaj i przygotuj propozycje</button></form>",
        "<button class='btn primary' type='submit'>Odczytaj i przygotuj propozycje</button>"
        "<p id='rk-inbox-upload-feedback' class='small muted' role='status' aria-live='polite' hidden></p></form>",
        'przycisk skrzynki')
    compile(src, 'rk_inbox.py', 'exec')
    return src


JS_FIX = r'''
// RK-INBOX-FEEDBACK-0310 — informacja zwrotna w czasie dłuższej lokalnej analizy OCR.
// Nie przechwytujemy formularza przez fetch: zwykły POST + przekierowanie nadal działa.
(() => {
  'use strict';
  const form = document.querySelector('form[data-rk-inbox-upload="1"]');
  if (!form) return;
  const fileInput = form.querySelector('input[type="file"][name="file"]');
  const submit = form.querySelector('button[type="submit"]');
  const info = document.getElementById('rk-inbox-upload-feedback');
  if (!fileInput || !submit || !info) return;
  const originalLabel = submit.textContent;
  let sending = false;
  let extendedNotice = null;
  function show(message, error = false) {
    info.hidden = false;
    info.textContent = message;
    info.setAttribute('role', error ? 'alert' : 'status');
  }
  function reset() {
    sending = false;
    submit.disabled = false;
    submit.textContent = originalLabel;
    if (extendedNotice !== null) { clearTimeout(extendedNotice); extendedNotice = null; }
    info.hidden = true;
    info.textContent = '';
    info.setAttribute('role', 'status');
  }
  form.addEventListener('submit', e => {
    if (sending) { e.preventDefault(); return; }
    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      e.preventDefault();
      show('Najpierw wybierz plik do odczytania.', true);
      return;
    }
    if (!file.size || file.size > 20 * 1024 * 1024) {
      e.preventDefault();
      show('Plik musi mieć od 1 bajta do 20 MB. Wybierz odpowiedni plik.', true);
      return;
    }
    sending = true;
    submit.disabled = true;
    submit.textContent = 'Trwa odczytywanie…';
    show('Przesyłanie pliku i lokalny odczyt. Skany PDF mogą wymagać więcej czasu. Po zakończeniu otworzy się ekran weryfikacji.');
    extendedNotice = setTimeout(() => {
      if (sending) show('Odczyt nadal trwa. OCR większych skanów jest czasochłonny; pozostaw okno otwarte. Jeśli program nie odpowiada, sprawdź lokalny dziennik błędów.');
    }, 25000);
    // Pozostaw domyślne działanie formularza; nie blokuj i nie duplikuj POST.
  });
  fileInput.addEventListener('invalid', () => show('Najpierw wybierz plik do odczytania.', true));
  fileInput.addEventListener('change', reset);
  window.addEventListener('pageshow', e => { if (e.persisted) reset(); });
})();
'''


def fix_js(src: str) -> str:
    if JS_MARKER in src:
        return src
    return src.rstrip('\n') + '\n' + JS_FIX


def apply(repo: Path, dry_run=False) -> str:
    repo = repo.resolve()
    ver_path = repo / 'app.py'
    if not ver_path.is_file():
        raise RuntimeError('Nie znaleziono app.py. Wskaż katalog źródeł repozytorium (nie EXE).')
    app = ver_path.read_text(encoding='utf-8')
    if 'VERSION = "0.3.10-dev1"' not in app:
        raise RuntimeError('Poprawka wymaga kodu 0.3.10-dev1. Najpierw aktywuj tę wersję.')
    paths = {name: repo / name for name in BASE_SHA}
    data = {}
    for name, path in paths.items():
        if not path.is_file(): raise RuntimeError(f'Brak pliku: {name}')
        raw = path.read_bytes()
        data[name] = raw.decode('utf-8')
    inbox = data['rk_inbox.py']; js = data['assets/rk_app.js']
    already = MARKER in inbox and JS_MARKER in js
    if already:
        return 'Poprawka już jest zainstalowana. Bez zmian.'
    if MARKER in inbox or JS_MARKER in js:
        raise RuntimeError('Wykryto niepełną poprawkę. Nie modyfikowano plików.')
    for name, path in paths.items():
        if sha_git(path.read_bytes()) != BASE_SHA[name]:
            raise RuntimeError(f'{name}: niezgodna wersja źródła. Bez zmian.')
    changes = {'rk_inbox.py': fix_inbox(inbox), 'assets/rk_app.js': fix_js(js)}
    if dry_run:
        return 'DRY RUN OK — oba pliki zgodne z RK 0.3.10; żaden plik nie został zmieniony.'
    backup = repo / '.rk_inbox_fix_backup_0310'
    if backup.exists():
        raise RuntimeError('Katalog kopii z tej aktualizacji już istnieje; przerwano bez nadpisywania.')
    backup.mkdir()
    done = []
    try:
        for name, path in paths.items():
            dest = backup / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        for name, new_content in changes.items():
            path = paths[name]
            fd, tmp = tempfile.mkstemp(prefix='.rk_inbox_', suffix='.tmp', dir=path.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
                    f.write(new_content); f.flush(); os.fsync(f.fileno())
                os.replace(tmp, path)
                done.append(name)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
    except Exception:
        for name in done:
            shutil.copy2(backup / name, paths[name])
        raise
    return 'Poprawka zainstalowana. Kopie plików w ' + str(backup)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('repo', nargs='?', default='.', help='Katalog repozytorium')
    p.add_argument('--dry-run', action='store_true')
    args=p.parse_args(argv)
    print(apply(Path(args.repo),args.dry_run))
    return 0

if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print('BŁĄD:', exc, file=sys.stderr)
        raise SystemExit(2)
