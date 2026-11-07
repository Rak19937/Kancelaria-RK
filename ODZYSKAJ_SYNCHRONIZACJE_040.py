#!/usr/bin/env python3
"""Uruchom tylko po zamknięciu obu aplikacji; najpierw sprawdź backup."""
from __future__ import annotations
import argparse
from pathlib import Path
from rk_core.sync_atomic import pending_sync_journal,recover_interrupted


def main():
    p=argparse.ArgumentParser()
    p.add_argument('data_dir',type=Path,help='Katalog Data instalacji, w którym wystąpiła awaria')
    p.add_argument('--restore',action='store_true',help='Potwierdź przywrócenie stanu sprzed synchronizacji')
    a=p.parse_args()
    journal=pending_sync_journal(a.data_dir)
    if not journal:
        print('Brak niedokończonej synchronizacji.');return
    print('Znaleziono dziennik:',journal)
    print('Zamknij RK KANCELARIA i wykonaj osobną kopię katalogu Data.')
    if not a.restore:
        print('Nic nie zmieniono. Po kontroli uruchom ponownie z --restore.');return
    print(recover_interrupted(a.data_dir))

if __name__=='__main__':main()
