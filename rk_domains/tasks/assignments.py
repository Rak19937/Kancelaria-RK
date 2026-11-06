"""Przypisywanie użytkowników do zadań: SQL bez warstwy HTTP i HTML."""
from __future__ import annotations

def selected_ids(fields, con, prefix='assign_user_'):
    """Formularz zawiera osobne klucze checkboxów (read_post nie zachowuje tablic)."""
    ids = []
    for key, value in fields.items():
        if not key.startswith(prefix) or str(value) not in ('1', 'on', 'yes'):
            continue
        raw = key[len(prefix):]
        if raw.isascii() and raw.isdigit():
            ids.append(int(raw))
    ids = sorted(set(ids))
    if ids:
        q = ','.join('?' for _ in ids)
        valid = {x[0] for x in con.execute(f'SELECT id FROM users WHERE is_active=1 AND id IN ({q})', ids)}
        if valid != set(ids):
            raise ValueError('Wskazano nieaktywnego lub nieistniejącego użytkownika.')
    return ids

def set_task_assignees(con, task_id, ids):
    row=con.execute('SELECT case_id FROM tasks WHERE id=?',(task_id,)).fetchone()
    if not row:
        raise ValueError('Nie znaleziono zadania.')
    ids=sorted(set(int(x) for x in ids))
    con.execute('DELETE FROM task_assignees WHERE task_id=?',(task_id,))
    con.executemany('INSERT INTO task_assignees(task_id,user_id) VALUES(?,?)',[(task_id,i) for i in ids])
    con.execute('UPDATE tasks SET assigned_user_id=? WHERE id=?',(ids[0] if ids else None,task_id))

def task_assignees_map(con, task_ids):
    ids=sorted({int(x) for x in task_ids})
    if not ids:return {}
    placeholders=','.join('?' for _ in ids)
    rows=con.execute(f'''SELECT ta.task_id, GROUP_CONCAT(u.author_name, ', ') display
            FROM task_assignees ta JOIN users u ON u.id=ta.user_id
            WHERE ta.task_id IN ({placeholders}) GROUP BY ta.task_id''',ids).fetchall()
    return {r['task_id']:r['display'] for r in rows}
