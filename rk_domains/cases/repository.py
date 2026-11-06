"""Odczyt sygnatur spraw — jedno zbiorcze zapytanie SQLite."""
from __future__ import annotations
import sqlite3

def load_external_signature_map(con: sqlite3.Connection, case_ids) -> dict[int, tuple[str,str]]:
    """Jedno zbiorcze zapytanie zamiast N+1 połączeń SQLite na listach spraw."""
    ids=[]
    seen=set()
    for raw in case_ids:
        try: cid=int(raw)
        except (TypeError,ValueError): continue
        if cid and cid not in seen:
            ids.append(cid); seen.add(cid)
    out: dict[int, tuple[str,str]] = {}
    for pos in range(0,len(ids),500):
        chunk=ids[pos:pos+500]
        if not chunk: continue
        ph=','.join('?' for _ in chunk)
        rows=con.execute(f"SELECT case_id,label,signature,id FROM case_external_signatures WHERE case_id IN ({ph}) AND TRIM(signature)<>'' ORDER BY case_id,id",chunk).fetchall()
        for r in rows:
            if r['case_id'] not in out:
                out[r['case_id']]=((r['label'] or 'Sygnatura innego organu').strip(),(r['signature'] or '').strip())
    return out
