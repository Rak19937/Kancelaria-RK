"""Zapytania wyszukiwarki nawigacyjnej (kompatybilna trasa /navigate)."""


def find_navigation_matches(con, phrase, max_len=160):
    q = str(phrase or '').strip()[:max_len]
    if not q:
        return [], [], []
    like = '%' + q + '%'
    cases = con.execute('''SELECT id,title,signature,client FROM cases
        WHERE title LIKE ? OR signature LIKE ? OR internal_signature LIKE ? OR client LIKE ?
        ORDER BY title LIMIT 50''', (like,like,like,like)).fetchall()
    tasks = con.execute('''SELECT t.id,t.title,c.title case_title FROM tasks t
        JOIN cases c ON c.id=t.case_id WHERE t.title LIKE ? ORDER BY t.due_date,t.id LIMIT 30''', (like,)).fetchall()
    docs = con.execute('''SELECT d.id,d.title,c.title case_title FROM documents d
        JOIN cases c ON c.id=d.case_id WHERE d.title LIKE ? OR d.original_name LIKE ?
        ORDER BY COALESCE(NULLIF(d.doc_date,''),NULLIF(d.received_date,''),SUBSTR(d.created_at,1,10)) DESC LIMIT 30''', (like,like)).fetchall()
    return cases, tasks, docs
