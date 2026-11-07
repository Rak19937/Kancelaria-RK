"""Pojedyncza definicja nawigacji RK KANCELARIA (warstwa prezentacji).

Nie wykonuje SQL i nie zmienia uprawnień. Wszelkie linki zachowują
historyczne adresy URL, a elementy administracyjne są warunkowane rolą.
"""

NAV_SECTIONS = (
    ('PRACA', (
        ('/', '⌂', 'Pulpit', 'dashboard'),
        ('/today', '◷', 'Dzisiaj', 'today'),
        ('/calendar', '▦', 'Kalendarz kancelarii', 'calendar'),
        ('/my-calendar', '▣', 'Mój kalendarz', 'mycalendar'),
        ('/worktime', '◷', 'Czas pracy i rozliczenia', 'worktime'),
        ('/stages', '▤', 'Etapy postępowań', 'stages'),
        ('/vault', '◇', 'Sejf dokumentów', 'vault'),
        ('/cases', '§', 'Sprawy', 'cases'),
        ('/case-categories', '▧', 'Kategorie spraw', 'case-categories'),
        ('/cases?mine=1', '◎', 'Moje sprawy', 'my_cases'),
        ('/tasks', '✓', 'Zadania', 'tasks'),
        ('/documents', '▤', 'Dokumenty — teczki', 'documents'),
        ('/evidence', '⚖', 'Centrum dowodowe', 'evidence'),
        ('/powers', '§', 'Pełnomocnictwa', 'powers'),
        ('/inbox', '✉', 'Skrzynka wpływu', 'inbox'),
        ('/workflow', '☑', 'Centrum decyzji', 'workflow'),
        ('/correspondence', '✉', 'Korespondencja', 'correspondence'),
        ('/drafts', '✎', 'Pisma', 'drafts'),
    )),
    ('WIĘCEJ', (
        ('/cases/closed', '□', 'Sprawy zakończone', 'closed_cases'),
        ('/entities', '♙', 'Kartoteka podmiotów', 'entities'),
        ('/checklists', '☑', 'Checklisty', 'checklists'),
        ('/views', '☆', 'Moje widoki', 'views'),
        ('/tags', '#', 'Tagi', 'tags'),
        ('/law', '¶', 'Prawo', 'law'),
        ('/search', '⌕', 'Wyszukiwarka', 'search'),
    )),
    ('SYSTEM', (
        ('/history', '↺', 'Historia zmian', 'history'),
        ('/trash', '⌫', 'Kosz', 'trash'),
        ('/backups', '⛁', 'Kopie bezpieczeństwa', 'backups'),
        ('/about', 'ⓘ', 'O programie', 'about'),
    )),
)
ADMIN_ITEMS = (
    ('/audit', '≡', 'Dziennik audytowy', 'audit'),
    ('/security', '◇', 'Bezpieczeństwo', 'security'),
    ('/recovery', '↥', 'Recovery', 'recovery'),
    ('/cloud', '☁', 'Cloud / PWA', 'cloud'),
    ('/calendar-sync', '▦', 'Google / Outlook', 'calendar-sync'),
    ('/court-portal', '⚖', 'Portal Informacyjny', 'court-portal'),
    ('/admin/users', '♟', 'Użytkownicy', 'users'),
)


def render_sidebar_navigation(active, user, esc):
    """HTML menu bez odczytów bazy; `esc` to istniejący escapujący helper."""
    parts = []
    for section, original_items in NAV_SECTIONS:
        items = list(original_items)
        if section == 'SYSTEM' and user and user['role'] == 'admin':
            items.extend(ADMIN_ITEMS)
        links = ''.join(
            f'<a class="nav-link {"active" if active == key else ""}" href="{esc(href)}">'
            f'<span class="nav-icon">{esc(icon)}</span><span>{esc(label)}</span></a>'
            for href, icon, label, key in items
        )
        if section in ('SYSTEM', 'WIĘCEJ'):
            opened = ' open' if any(active == item[3] for item in items) else ''
            title = 'USTAWIENIA I SYSTEM' if section == 'SYSTEM' else section
            parts.append(
                f'<details class="nav-system"{opened}><summary><span>{esc(title)}</span>'
                f'<span class="nav-system-arrow">›</span></summary>'
                f'<div class="nav-system-links">{links}</div></details>'
            )
        else:
            parts.append(f'<div class="nav-section"><div class="nav-section-title">{esc(section)}</div>{links}</div>')
    return ''.join(parts)
