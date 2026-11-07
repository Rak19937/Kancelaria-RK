"""Schemat SQLite: oryginalna inicjalizacja i migracje, bez importu app.py."""
from __future__ import annotations
import sqlite3
import os

def initialize_database(db, *, schema_version, ensure_smart_schema, ensure_inbox_schema, ensure_document_hub_schema, ensure_action_center_schema, ensure_correspondence_schema, ensure_workspace_plus_schema, ensure_case_categories_schema, ensure_caseflow_schema, reconcile_task_alerts, seed_demo) -> None:
    with db() as con:
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signature TEXT DEFAULT '',
                internal_signature TEXT DEFAULT '',
                client TEXT DEFAULT '',
                title TEXT NOT NULL,
                court TEXT DEFAULT '',
                department TEXT DEFAULT '',
                category TEXT DEFAULT '',
                subject TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                next_step TEXT DEFAULT '',
                next_date TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS parties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                role TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                event_date TEXT DEFAULT '',
                event_type TEXT DEFAULT 'Czynność',
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS process_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                event_date TEXT DEFAULT '',
                event_type TEXT DEFAULT 'Inna czynność',
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                court TEXT DEFAULT '',
                signature TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'done',
                document_id INTEGER,
                next_date TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                due_date TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                priority TEXT NOT NULL DEFAULT 'normal',
                depends_on TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                doc_date TEXT DEFAULT '',
                received_date TEXT DEFAULT '',
                doc_type TEXT DEFAULT 'Inne',
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                stored_name TEXT DEFAULT '',
                original_name TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS case_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                target_case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL DEFAULT 'related',
                note TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (source_case_id <> target_case_id)
            );
            CREATE TABLE IF NOT EXISTS case_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                note TEXT NOT NULL,
                author TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS case_external_signatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                signature TEXT NOT NULL,
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE
            );
            CREATE TABLE IF NOT EXISTS case_tags (
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY(case_id, tag_id)
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                author_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                function TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_case_pins (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(user_id,case_id)
            );
            CREATE TABLE IF NOT EXISTS user_case_recent (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(user_id,case_id)
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id INTEGER,
                action TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS recycle_bin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id INTEGER,
                case_id INTEGER,
                label TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL,
                deleted_by TEXT NOT NULL DEFAULT '',
                deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS immutable_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id INTEGER,
                action TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                user_id INTEGER,
                remote_addr TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL DEFAULT 'person',
                display_name TEXT NOT NULL,
                first_name TEXT DEFAULT '',
                last_name TEXT DEFAULT '',
                company_name TEXT DEFAULT '',
                pesel TEXT DEFAULT '',
                nip TEXT DEFAULT '',
                krs TEXT DEFAULT '',
                email TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                address TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS case_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE RESTRICT,
                role TEXT NOT NULL DEFAULT 'Uczestnik',
                notes TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS checklist_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS checklist_template_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL REFERENCES checklist_templates(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS case_checklist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                is_done INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                template_id INTEGER,
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS writing_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                doc_type TEXT DEFAULT 'Pismo procesowe',
                status TEXT NOT NULL DEFAULT 'Roboczy',
                due_date TEXT DEFAULT '',
                content TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                stored_name TEXT DEFAULT '',
                original_name TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_cases_signature ON cases(signature);
            CREATE INDEX IF NOT EXISTS idx_cases_title ON cases(title);
            CREATE INDEX IF NOT EXISTS idx_events_case ON events(case_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_case ON tasks(case_id);
            CREATE INDEX IF NOT EXISTS idx_process_events_case ON process_events(case_id,event_date);
            CREATE INDEX IF NOT EXISTS idx_docs_case ON documents(case_id);
            CREATE INDEX IF NOT EXISTS idx_parties_case ON parties(case_id);
            CREATE INDEX IF NOT EXISTS idx_notes_case ON case_notes(case_id);
            CREATE INDEX IF NOT EXISTS idx_extsig_case ON case_external_signatures(case_id);
            CREATE INDEX IF NOT EXISTS idx_extsig_signature ON case_external_signatures(signature);
            CREATE INDEX IF NOT EXISTS idx_extsig_label ON case_external_signatures(label);
            CREATE INDEX IF NOT EXISTS idx_rel_source ON case_relations(source_case_id);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON case_relations(target_case_id);
            CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
            CREATE INDEX IF NOT EXISTS idx_case_tags_case ON case_tags(case_id);
            CREATE INDEX IF NOT EXISTS idx_case_tags_tag ON case_tags(tag_id);
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_expires ON user_sessions(expires_at);
            CREATE INDEX IF NOT EXISTS idx_writing_projects_case ON writing_projects(case_id);
            CREATE INDEX IF NOT EXISTS idx_writing_projects_status ON writing_projects(status);
            """
        )

        def ensure_columns(table: str, columns: dict[str, str]):
            existing = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
            for col, ddl in columns.items():
                if col not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

        ensure_columns("cases", {
            "internal_signature": "TEXT DEFAULT ''",
            "client": "TEXT DEFAULT ''",
            "created_by": "TEXT DEFAULT ''",
            "updated_by": "TEXT DEFAULT ''",
            "waiting_for": "TEXT DEFAULT ''",
            "lead_user_id": "INTEGER",
        })
        ensure_columns("parties", {"created_by": "TEXT DEFAULT ''", "updated_by": "TEXT DEFAULT ''", "created_at": "TEXT DEFAULT ''"})
        ensure_columns("events", {"created_by": "TEXT DEFAULT ''", "updated_by": "TEXT DEFAULT ''"})
        ensure_columns("process_events", {
            "event_date": "TEXT DEFAULT ''", "event_type": "TEXT DEFAULT 'Inna czynność'",
            "title": "TEXT DEFAULT ''", "description": "TEXT DEFAULT ''", "court": "TEXT DEFAULT ''",
            "signature": "TEXT DEFAULT ''", "status": "TEXT NOT NULL DEFAULT 'done'", "document_id": "INTEGER",
            "next_date": "TEXT DEFAULT ''", "created_by": "TEXT DEFAULT ''", "updated_by": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''", "updated_at": "TEXT DEFAULT ''"
        })
        ensure_columns("tasks", {
            "created_by": "TEXT DEFAULT ''", "updated_by": "TEXT DEFAULT ''", "assigned_user_id": "INTEGER",
            "deadline_base_date": "TEXT DEFAULT ''", "deadline_days": "INTEGER", "deadline_rule": "TEXT DEFAULT ''",
            "deadline_source": "TEXT DEFAULT ''", "deadline_manual": "INTEGER NOT NULL DEFAULT 0",
            "completed_at": "TEXT DEFAULT ''", "completed_by": "TEXT DEFAULT ''",
            "task_type": "TEXT DEFAULT 'Zadanie'"
        })
        ensure_columns("documents", {
            "received_date": "TEXT DEFAULT ''", "delivered_date": "TEXT DEFAULT ''",
            "sender": "TEXT DEFAULT ''", "document_author": "TEXT DEFAULT ''", "tags": "TEXT DEFAULT ''",
            "linked_task_id": "INTEGER", "created_by": "TEXT DEFAULT ''", "updated_by": "TEXT DEFAULT ''",
            "file_hash": "TEXT DEFAULT ''", "extracted_text": "TEXT DEFAULT ''", "indexed_at": "TEXT DEFAULT ''",
            "doc_status": "TEXT DEFAULT 'Aktywny'", "ocr_used": "INTEGER NOT NULL DEFAULT 0",
            "ocr_status": "TEXT DEFAULT ''", "ocr_language": "TEXT DEFAULT ''",
            "parent_document_id": "INTEGER", "attachment_order": "INTEGER NOT NULL DEFAULT 0"
        })
        ensure_columns("cases", {"closed_edit_unlocked": "INTEGER NOT NULL DEFAULT 0"})
        ensure_columns("parties", {"entity_id": "INTEGER"})
        ensure_columns("case_relations", {"note": "TEXT DEFAULT ''", "created_by": "TEXT DEFAULT ''", "updated_by": "TEXT DEFAULT ''"})
        ensure_columns("case_notes", {"author": "TEXT DEFAULT ''", "created_at": "TEXT DEFAULT ''"})
        ensure_columns("users", {"function": "TEXT NOT NULL DEFAULT ''"})
        ensure_columns("case_checklist_items", {"completed_at": "TEXT DEFAULT ''", "completed_by": "TEXT DEFAULT ''"})

        con.execute("""CREATE TABLE IF NOT EXISTS saved_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id,name)
        )""")

        con.execute("""CREATE TABLE IF NOT EXISTS draft_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            doc_type TEXT NOT NULL DEFAULT 'Pismo procesowe',
            content TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_by TEXT DEFAULT '',
            updated_by TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS draft_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES writing_projects(id) ON DELETE CASCADE,
            version_no INTEGER NOT NULL,
            title TEXT NOT NULL,
            doc_type TEXT DEFAULT '',
            status TEXT DEFAULT '',
            due_date TEXT DEFAULT '',
            content TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            stored_name TEXT DEFAULT '',
            original_name TEXT DEFAULT '',
            change_note TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id,version_no)
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS system_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_type TEXT NOT NULL,
            result TEXT NOT NULL,
            details TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_draft_versions_project ON draft_versions(project_id,version_no DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_documents_linked_task ON documents(linked_task_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_documents_delivered ON documents(delivered_date)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_documents_parent ON documents(parent_document_id,attachment_order,id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type,status,due_date)")

        # HOTFIX 0.12.13: wersja 0.13 używała w audit_log nazw actor/details,
        # podczas gdy stabilna gałąź 0.12 używa author/description. Ponieważ DATA_DIR
        # jest wspólny dla wersji, po powrocie z 0.13 część spraw z historią zmian
        # kończyła się błędem sqlite3.Row: "No item with that key".
        ensure_columns("audit_log", {
            "case_id": "INTEGER",
            "entity_type": "TEXT NOT NULL DEFAULT ''",
            "entity_id": "INTEGER",
            "action": "TEXT NOT NULL DEFAULT ''",
            "description": "TEXT NOT NULL DEFAULT ''",
            "author": "TEXT NOT NULL DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        })
        audit_cols = {r[1] for r in con.execute("PRAGMA table_info(audit_log)").fetchall()}
        if "details" in audit_cols:
            con.execute("UPDATE audit_log SET description=COALESCE(NULLIF(description,''),details,'') WHERE COALESCE(description,'')='' AND COALESCE(details,'')<>''")
        if "actor" in audit_cols:
            con.execute("UPDATE audit_log SET author=COALESCE(NULLIF(author,''),actor,'') WHERE COALESCE(author,'')='' AND COALESCE(actor,'')<>''")

        # Usuń wyłącznie historyczne triggery pozostawione przez eksperymentalną 0.13.
        # Stabilna gałąź zapisuje audyt jawnie w kodzie i nie potrzebuje tych triggerów;
        # ich pozostawienie powodowałoby podwójne wpisy historii.
        for legacy_trigger in (
            "audit_cases_u", "audit_tasks_i", "audit_tasks_u", "audit_tasks_d",
            "audit_docs_i", "audit_docs_u", "audit_events_i", "audit_notes_i"
        ):
            con.execute(f"DROP TRIGGER IF EXISTS {legacy_trigger}")
        con.execute("CREATE INDEX IF NOT EXISTS idx_cases_internal_signature ON cases(internal_signature)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_cases_client ON cases(client)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_cases_lead_user ON cases(lead_user_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_tasks_assigned_user ON tasks(assigned_user_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_recent_user ON user_case_recent(user_id, opened_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(case_id, created_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_trash_deleted ON recycle_bin(deleted_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_immutable_audit_case ON immutable_audit(case_id, created_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(display_name)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_entities_pesel ON entities(pesel)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_entities_nip ON entities(nip)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_entities_krs ON entities(krs)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_case_entities_case ON case_entities(case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_case_entities_entity ON case_entities(entity_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_checklist_case ON case_checklist_items(case_id,sort_order)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_doc_hash ON documents(file_hash)")
        try:
            con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(document_id UNINDEXED, case_id UNINDEXED, title, filename, body)")
        except sqlite3.DatabaseError:
            pass

        con.execute("CREATE INDEX IF NOT EXISTS idx_cases_status_nextdate ON cases(status,next_date)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_cases_nextdate ON cases(next_date,id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_due_case ON tasks(status,due_date,case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_date_case ON events(event_date,case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_process_events_date_case ON process_events(event_date,case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_process_events_nextdate_case ON process_events(next_date,case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_docs_status_case ON documents(doc_status,case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_writing_projects_status_due ON writing_projects(status,due_date,updated_at)")

        # Warstwa 0.3: czytelny widok sprawy, alerty, relacje i lokalna biblioteka prawa.
        # CREATE IF NOT EXISTS + INSERT OR IGNORE zachowują pełną zgodność z danymi DEV9.
        ensure_smart_schema(con)
        ensure_inbox_schema(con)
        ensure_document_hub_schema(con)
        ensure_action_center_schema(con)
        ensure_correspondence_schema(con)
        ensure_workspace_plus_schema(con)
        ensure_case_categories_schema(con)
        ensure_caseflow_schema(con)
        # Scala stare osobne monity/alerty i zadania. Operacja jest idempotentna.
        reconcile_task_alerts(con)

        # Jawny numer wersji schematu przygotowuje bezpieczne migracje.
        con.execute(f"PRAGMA user_version={schema_version}")

        # 0.15.x automatycznie wstawiała do każdej pustej instalacji prywatny zestaw
        # danych demonstracyjnych. W 0.2 demo jest wyłącznie jawnie opt-in.
        count = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        seed_requested = os.getenv("RK_KANCELARIA_SEED_DEMO", "0").strip().lower() in {"1", "true", "yes", "tak"}
        if count == 0 and seed_requested:
            seed_demo(con)
