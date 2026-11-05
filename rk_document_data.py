"""Dane do panelu kontekstowego dokumentu; HTML pozostaje w rk_ux.py."""


def list_open_case_tasks(con, case_id, limit=8):
    return con.execute('''SELECT id,title,due_date,status,priority FROM tasks
        WHERE case_id=? AND status='open'
        ORDER BY CASE WHEN due_date IS NULL OR due_date='' THEN 1 ELSE 0 END,
                 due_date, CASE WHEN priority='high' THEN 0 ELSE 1 END,id LIMIT ?''',
        (int(case_id),int(limit))).fetchall()
