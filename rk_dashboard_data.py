"""Odczyty pulpitu przeniesione z handlera HTTP; bez mutowania SQLite."""


def dashboard_snapshot(con, today, week_end, user_id, signature_loader, status_labels):
    counts_by_status = {r['status']: r['cnt'] for r in con.execute(
        'SELECT status,COUNT(*) cnt FROM cases GROUP BY status').fetchall()}
    counts = {status: counts_by_status.get(status, 0) for status in status_labels}
    task_stats = con.execute('''SELECT
        SUM(CASE WHEN t.due_date=? THEN 1 ELSE 0 END) due_today,
        SUM(CASE WHEN t.due_date<>'' AND t.due_date<? THEN 1 ELSE 0 END) overdue,
        SUM(CASE WHEN t.due_date>? AND t.due_date<=? THEN 1 ELSE 0 END) next7,
        SUM(CASE WHEN t.priority='high' THEN 1 ELSE 0 END) high_priority
        FROM tasks t JOIN cases c ON c.id=t.case_id
        WHERE t.status='open' AND c.status<>'closed' ''', (today,today,today,week_end)).fetchone()
    dated = con.execute('''SELECT t.*,c.title case_title,c.signature,c.internal_signature FROM tasks t
        JOIN cases c ON c.id=t.case_id WHERE t.status='open' AND c.status<>'closed' AND t.due_date<>''
        ORDER BY t.due_date,CASE t.priority WHEN 'high' THEN 0 ELSE 1 END,t.id LIMIT 15''').fetchall()
    undated = con.execute('''SELECT t.*,c.title case_title,c.signature,c.internal_signature FROM tasks t
        JOIN cases c ON c.id=t.case_id WHERE t.status='open' AND c.status<>'closed' AND t.due_date=''
        ORDER BY CASE t.priority WHEN 'high' THEN 0 ELSE 1 END,t.id LIMIT 10''').fetchall()
    upcoming = con.execute("SELECT * FROM cases WHERE status<>'closed' AND next_date<>'' AND next_date>=? ORDER BY next_date LIMIT 8", (today,)).fetchall()
    recent_events = con.execute("SELECT e.*, c.title case_title, c.signature FROM events e JOIN cases c ON c.id=e.case_id WHERE c.status<>'closed' ORDER BY e.event_date DESC, e.id DESC LIMIT 8").fetchall()
    pinned = con.execute("""SELECT c.* FROM user_case_pins p JOIN cases c ON c.id=p.case_id
        WHERE p.user_id=? AND c.status<>'closed' ORDER BY c.next_date='',c.next_date,c.title LIMIT 12""", (user_id,)).fetchall() if user_id else []
    recent_cases = con.execute("""SELECT c.*,r.opened_at FROM user_case_recent r JOIN cases c ON c.id=r.case_id
        WHERE r.user_id=? ORDER BY r.opened_at DESC LIMIT 8""", (user_id,)).fetchall() if user_id else []
    sig_ids = [r['id'] for r in pinned] + [r['id'] for r in recent_cases] + [r['case_id'] for r in dated] + [r['case_id'] for r in undated] + [r['id'] for r in upcoming]
    return {
        'counts': counts,
        'due_today': int(task_stats['due_today'] or 0),
        'overdue_count': int(task_stats['overdue'] or 0),
        'next7_count': int(task_stats['next7'] or 0),
        'high_count': int(task_stats['high_priority'] or 0),
        'dated': dated, 'undated': undated, 'upcoming': upcoming,
        'recent_events': recent_events, 'pinned': pinned, 'recent_cases': recent_cases,
        'sig_map': signature_loader(con, sig_ids),
    }
