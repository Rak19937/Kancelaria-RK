"""Centralny rejestr prostych tras; bez obchodzenia autoryzacji.

Dyspozytory są wywoływane dopiero po dotychczasowych require_auth(),
kontroli read-only, odczycie POST i wewnątrz dotychczasowych try/except.
Trasy parametryczne i wyjątkowe pozostają w app.py do dalszej refaktoryzacji.
"""

# Ścieżka -> (metoda Handler, zestaw argumentów).
GET_ROUTES = {
    '/': ('dashboard', ''),
    '/today': ('today_page', 'q'),
    '/calendar': ('calendar_page', 'q'),
    '/my-calendar': ('my_calendar_page', 'q'),
    '/quick-add': ('quick_add_page', 'q'),
    '/deadline': ('deadline_page', 'q'),
    '/cases': ('cases', 'q_closed_false'),
    '/case-categories': ('category_catalog_page', ''),
    '/evidence': ('caseflow_evidence', 'q'),
    '/navigate': ('caseflow_navigate', 'q'),
    '/cases/closed': ('cases', 'q_closed_true'),
    '/case/new': ('case_new', ''),
    '/entities': ('entities_page', 'q'),
    '/entity/new': ('entity_new_page', ''),
    '/checklists': ('checklists_page', ''),
    '/audit': ('immutable_audit_page', 'q'),
    '/security': ('security_page', ''),
    '/recovery': ('recovery_page', ''),
    '/cloud': ('cloud_page', ''),
    '/case/import': ('case_import_page', ''),
    '/trash': ('trash_page', 'q'),
    '/history': ('history_page', 'q'),
    '/about': ('about_page', ''),
    '/backups': ('backups_page', ''),
    '/tasks': ('tasks_page', 'q'),
    '/views': ('saved_views_page', ''),
    '/documents': ('documents_page', 'q'),
    '/powers': ('powers_page', 'q'),
    '/inbox': ('inbox_page', ''),
    '/workflow': ('action_center_page', ''),
    '/correspondence': ('correspondence_page', 'q'),
    '/correspondence/new': ('correspondence_form', 'q'),
    '/tags': ('tags_page', 'q'),
    '/search': ('search_page', 'q'),
    '/backup': ('backup', ''),
    '/backup/snapshot': ('full_snapshot_download', ''),
}

POST_ROUTES = {
    '/logout': ('logout_submit', ''),
    '/account/update': ('account_update', 'f'),
    '/account/password': ('account_password', 'f'),
    '/admin/user/create': ('user_create', 'f'),
    '/entity/create': ('entity_create', 'f'),
    '/checklist/template/create': ('checklist_template_create', 'f'),
    '/admin/reindex-documents': ('reindex_documents', 'f'),
    '/security/ocr/install': ('ocr_install_start', 'f'),
    '/security/key': ('security_key_update', 'f'),
    '/backup/encrypted': ('encrypted_backup', 'f'),
    '/backup/snapshot/download': ('full_snapshot_download_encrypted', 'f'),
    '/backup/manual': ('manual_backup_now', 'f'),
    '/recovery/check': ('recovery_check', 'f'),
    '/recovery/test-restore': ('recovery_test_restore', 'f'),
    '/recovery/snapshot-import': ('full_snapshot_import', 'ff'),
    '/cloud/config': ('cloud_config_update', 'f'),
    '/cloud/check': ('cloud_check', 'f'),
    '/cloud/push': ('cloud_push', 'f'),
    '/cloud/pull': ('cloud_pull', 'f'),
    '/backups/restore': ('backup_restore_schedule', 'f'),
    '/data/import-installed': ('data_import_installed', 'f'),
}


def _invoke(handler, item, qs=None, fields=None, files=None):
    name, arg_type = item
    method = getattr(handler, name)
    if arg_type == '': method()
    elif arg_type == 'q': method(qs)
    elif arg_type == 'f': method(fields)
    elif arg_type == 'ff': method(fields, files)
    elif arg_type == 'q_closed_false': method(qs, closed_only=False)
    elif arg_type == 'q_closed_true': method(qs, closed_only=True)
    else: raise AssertionError('Nieznany kontrakt trasy: ' + arg_type)
    return True


def dispatch_static_get(handler, path, qs):
    item = GET_ROUTES.get(path)
    return _invoke(handler, item, qs=qs) if item is not None else False


def dispatch_static_post(handler, path, fields, files):
    item = POST_ROUTES.get(path)
    return _invoke(handler, item, fields=fields, files=files) if item is not None else False
