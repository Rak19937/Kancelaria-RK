#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK KANCELARIA — warstwa SMART CASE / PRAWO.

Moduł celowo korzysta wyłącznie ze standardowej biblioteki Pythona i SQLite.
Nie podejmuje samodzielnie decyzji prawnych: generuje opisy, sugestie i powiązania,
które użytkownik może zweryfikować przed wykorzystaniem.
"""
from __future__ import annotations

import hashlib
import html as html_lib
from io import BytesIO
import json
import re
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Iterable

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


LAW_REGISTRY = {
    "KPC": {
        "short_title": "Kodeks postępowania cywilnego",
        "title": "Ustawa z dnia 17 listopada 1964 r. – Kodeks postępowania cywilnego",
        "publisher": "DU",
        "year": 2026,
        "position": 468,
        "display_address": "Dz.U. 2026 poz. 468",
        "source_date": "2026-03-27",
        "search_phrase": "Kodeks postępowania cywilnego",
        "procedural_area": "cywilne",
    },
    "KPK": {
        "short_title": "Kodeks postępowania karnego",
        "title": "Ustawa z dnia 6 czerwca 1997 r. – Kodeks postępowania karnego",
        "publisher": "DU",
        "year": 2026,
        "position": 490,
        "display_address": "Dz.U. 2026 poz. 490",
        "source_date": "2026-03-27",
        "search_phrase": "Kodeks postępowania karnego",
        "procedural_area": "karne",
    },
    "KPA": {
        "short_title": "Kodeks postępowania administracyjnego",
        "title": "Ustawa z dnia 14 czerwca 1960 r. – Kodeks postępowania administracyjnego",
        "publisher": "DU",
        "year": 2025,
        "position": 1691,
        "display_address": "Dz.U. 2025 poz. 1691",
        "source_date": "2025-11-07",
        "search_phrase": "Kodeks postępowania administracyjnego",
        "procedural_area": "administracyjne",
    },
    "PPSA": {
        "short_title": "Prawo o postępowaniu przed sądami administracyjnymi",
        "title": "Ustawa z dnia 30 sierpnia 2002 r. – Prawo o postępowaniu przed sądami administracyjnymi",
        "publisher": "DU",
        "year": 2024,
        "position": 935,
        "display_address": "Dz.U. 2024 poz. 935",
        "source_date": "2024-05-23",
        "search_phrase": "Prawo o postępowaniu przed sądami administracyjnymi",
        "procedural_area": "sądowoadministracyjne",
    },
}

RELATION_TYPES = [
    "wynika z",
    "powoduje",
    "odpowiedź na",
    "dotyczy",
    "wykonuje",
    "uruchamia termin",
    "powiązane z",
]

ALERT_TYPES = ["Termin procesowy", "Rozprawa", "Posiedzenie", "Monit", "Płatność", "Mediacja", "Zadanie", "Inne"]
ALERT_PRIORITIES = ["normal", "high", "critical"]
ACTIONABLE_ALERT_TYPES = {"Zadanie", "Monit", "Termin procesowy", "Płatność"}


class _PlainTextHTMLParser(HTMLParser):
    BREAK_TAGS = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "article", "section", "table", "ul", "ol", "blockquote",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in self.BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if data:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts).replace("\xa0", " ")
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n[ \t]+", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def ensure_smart_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS smart_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            relation_type TEXT NOT NULL DEFAULT 'powiązane z',
            note TEXT DEFAULT '',
            auto_created INTEGER NOT NULL DEFAULT 0,
            created_by TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(case_id,source_type,source_id,target_type,target_id,relation_type)
        );
        CREATE INDEX IF NOT EXISTS idx_smart_links_case ON smart_links(case_id,created_at);

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,
            alert_date TEXT NOT NULL,
            alert_type TEXT NOT NULL DEFAULT 'Inne',
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'open',
            source_type TEXT DEFAULT '',
            source_id INTEGER,
            assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            repeat_rule TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_date_status ON alerts(status,alert_date);
        CREATE INDEX IF NOT EXISTS idx_alerts_case ON alerts(case_id,alert_date);
        CREATE INDEX IF NOT EXISTS idx_alerts_source ON alerts(source_type,source_id);

        CREATE TABLE IF NOT EXISTS case_auto_tags (
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            tag TEXT NOT NULL COLLATE NOCASE,
            reason TEXT DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(case_id,tag)
        );

        CREATE TABLE IF NOT EXISTS case_generated_summary (
            case_id INTEGER PRIMARY KEY REFERENCES cases(id) ON DELETE CASCADE,
            description TEXT NOT NULL DEFAULT '',
            stage_summary TEXT NOT NULL DEFAULT '',
            next_action_summary TEXT NOT NULL DEFAULT '',
            fingerprint TEXT NOT NULL DEFAULT '',
            generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS law_acts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE COLLATE NOCASE,
            short_title TEXT NOT NULL,
            title TEXT NOT NULL,
            publisher TEXT NOT NULL DEFAULT 'DU',
            year INTEGER,
            position INTEGER,
            display_address TEXT DEFAULT '',
            source_date TEXT DEFAULT '',
            source_url TEXT DEFAULT '',
            change_date TEXT DEFAULT '',
            status TEXT DEFAULT '',
            local_text TEXT DEFAULT '',
            local_text_hash TEXT DEFAULT '',
            last_checked_at TEXT DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS law_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            act_id INTEGER NOT NULL REFERENCES law_acts(id) ON DELETE CASCADE,
            article_key TEXT NOT NULL,
            heading TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            UNIQUE(act_id,article_key)
        );
        CREATE INDEX IF NOT EXISTS idx_law_articles_act_sort ON law_articles(act_id,sort_order);

        CREATE TABLE IF NOT EXISTS law_case_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            act_id INTEGER NOT NULL REFERENCES law_acts(id) ON DELETE CASCADE,
            article_id INTEGER REFERENCES law_articles(id) ON DELETE CASCADE,
            article_key_text TEXT DEFAULT '',
            note TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(case_id,act_id,article_id)
        );
        CREATE INDEX IF NOT EXISTS idx_law_case_links_case ON law_case_links(case_id);

        CREATE TABLE IF NOT EXISTS deadline_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
            source_text TEXT NOT NULL DEFAULT '',
            suggested_title TEXT NOT NULL DEFAULT '',
            base_date TEXT DEFAULT '',
            days INTEGER,
            rule TEXT NOT NULL DEFAULT 'calendar',
            legal_basis TEXT DEFAULT '',
            confidence TEXT NOT NULL DEFAULT 'do weryfikacji',
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(document_id,source_text,suggested_title)
        );
        CREATE INDEX IF NOT EXISTS idx_deadline_suggestions_case ON deadline_suggestions(case_id,status);
        """
    )
    # Migracja DEV10/0.3 dla baz, w których law_case_links powstało przed polem
    # tekstowego numeru artykułu. Pozwala przypiąć np. art. 317 KPC nawet wtedy,
    # gdy pełny tekst aktu nie został jeszcze pobrany z ELI.
    cols = {r[1] for r in con.execute("PRAGMA table_info(law_case_links)").fetchall()}
    if "article_key_text" not in cols:
        con.execute("ALTER TABLE law_case_links ADD COLUMN article_key_text TEXT DEFAULT ''")
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS law_fts USING fts5(article_id UNINDEXED, act_code, article_key, heading, body)")
    except sqlite3.DatabaseError:
        pass
    seed_law_registry(con)


def seed_law_registry(con: sqlite3.Connection) -> None:
    for code, info in LAW_REGISTRY.items():
        source_url = f"https://api.sejm.gov.pl/eli/acts/{info['publisher']}/{info['year']}/{info['position']}/text.html"
        con.execute(
            """INSERT INTO law_acts(code,short_title,title,publisher,year,position,display_address,source_date,source_url)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET
                 short_title=excluded.short_title,
                 title=excluded.title,
                 source_url=CASE WHEN law_acts.local_text='' THEN excluded.source_url ELSE law_acts.source_url END""",
            (code, info["short_title"], info["title"], info["publisher"], info["year"], info["position"], info["display_address"], info["source_date"], source_url),
        )


def _http_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": "RK-KANCELARIA/0.3 (+local legal library)", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "RK-KANCELARIA/0.3 (+local legal library)", "Accept": "text/html, text/plain;q=0.9, */*;q=0.5"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(charset, "replace")



def _http_bytes(url: str, timeout: int = 45) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "RK-KANCELARIA/0.3 (+local legal library)",
                 "Accept": "application/pdf, application/octet-stream, */*;q=0.5"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _pdf_to_text(data: bytes) -> str:
    if PdfReader is None:
        raise RuntimeError("Brak modułu pypdf potrzebnego do odczytu tekstu PDF.")
    try:
        reader = PdfReader(BytesIO(data))
        parts = [(page.extract_text() or "") for page in reader.pages]
        text = "\n".join(parts).replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        if "Art." not in text:
            raise RuntimeError("PDF nie zawiera tekstu możliwego do odczytania.")
        return text
    except Exception as exc:
        raise RuntimeError(f"Nie udało się odczytać tekstu PDF: {exc}") from exc


def _date_sort_key(item: dict) -> tuple[str, int, int]:
    return (
        str(item.get("promulgation") or item.get("announcementDate") or ""),
        int(item.get("year") or 0),
        int(item.get("pos") or item.get("position") or 0),
    )


def find_latest_consolidated_act(code: str) -> dict:
    info = LAW_REGISTRY.get(code.upper())
    if not info:
        raise ValueError(f"Nieznany wbudowany kod aktu: {code}")
    phrase = info["search_phrase"]
    q = urllib.parse.urlencode({
        "publisher": "DU",
        "title": phrase,
        "dateFrom": "2020-01-01",
        "limit": 100,
    })
    data = _http_json(f"https://api.sejm.gov.pl/eli/acts/search?{q}")
    items = data.get("items", []) if isinstance(data, dict) else []
    # Preferujemy obwieszczenia publikujące tekst jednolity; w razie braku pozostawiamy obecny snapshot.
    candidates = []
    needle = phrase.lower()
    for item in items:
        title = str(item.get("title") or "")
        lo = title.lower()
        if needle in lo and ("jednolitego tekstu" in lo or "tekst jednolity" in lo):
            candidates.append(item)
    if not candidates:
        raise RuntimeError("ELI nie zwróciło nowszego tekstu jednolitego dla tego aktu.")
    return sorted(candidates, key=_date_sort_key, reverse=True)[0]


def _normalise_article_key(raw: str) -> str:
    raw = html_lib.unescape(raw or "").replace("\xa0", " ").strip()
    raw = re.sub(r"\s+", " ", raw)
    raw = raw.rstrip(".")
    return raw


def parse_articles_from_text(text: str) -> list[tuple[str, str, str]]:
    """Dzieli tekst aktu na artykuły. Zwraca (klucz, nagłówek, treść)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Obsługuje Art. 87¹, Art. 87[1], Art. 87a, Art. 1a itp.
    pattern = re.compile(r"(?m)^\s*Art\.\s*([0-9]+(?:[a-zA-Z]|\[[0-9]+\]|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)?)\.?\s*(?:\n|$)")
    matches = list(pattern.finditer(text))
    if not matches:
        # Część HTML po spłaszczeniu może trzymać treść w tym samym wierszu.
        pattern = re.compile(r"(?m)(?:^|\n)\s*Art\.\s*([0-9]+(?:[a-zA-Z]|\[[0-9]+\]|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)?)\.?\s+")
        matches = list(pattern.finditer(text))
    out: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        key = _normalise_article_key(m.group(1))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if len(block) < 5:
            continue
        out.append((key, f"Art. {key}.", block))
    return out



def import_law_text(con: sqlite3.Connection, code: str, plain: str, metadata: dict | None = None, source_url: str = "") -> tuple[int, int]:
    code = code.upper().strip()
    articles = parse_articles_from_text(plain)
    if not articles:
        raise RuntimeError("Nie udało się rozpoznać artykułów w tekście aktu.")
    act = con.execute("SELECT * FROM law_acts WHERE code=?", (code,)).fetchone()
    if not act:
        raise ValueError(f"Akt {code} nie istnieje w rejestrze.")
    h = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    md = metadata or {}
    year = int(md.get("year") or act["year"] or 0)
    pos = int(md.get("pos") or md.get("position") or act["position"] or 0)
    display = str(md.get("displayAddress") or md.get("display_address") or act["display_address"] or "")
    final_url = source_url or act["source_url"]
    con.execute(
        """UPDATE law_acts SET year=?,position=?,display_address=?,source_url=?,change_date=?,status=?,
           local_text=?,local_text_hash=?,last_checked_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
        (year, pos, display, final_url, str(md.get("changeDate") or ""), str(md.get("status") or ""), plain, h, act["id"]),
    )
    con.execute("DELETE FROM law_articles WHERE act_id=?", (act["id"],))
    try:
        con.execute("DELETE FROM law_fts WHERE act_code=?", (code,))
    except sqlite3.DatabaseError:
        pass
    count = 0
    for idx, (key, heading, body) in enumerate(articles, 1):
        cur = con.execute(
            "INSERT INTO law_articles(act_id,article_key,heading,body,sort_order) VALUES(?,?,?,?,?)",
            (act["id"], key, heading, body, idx),
        )
        try:
            con.execute("INSERT INTO law_fts(article_id,act_code,article_key,heading,body) VALUES(?,?,?,?,?)",
                        (cur.lastrowid, code, key, heading, body))
        except sqlite3.DatabaseError:
            pass
        count += 1
    return act["id"], count



def import_law_html(con: sqlite3.Connection, code: str, html_text: str, metadata: dict | None = None) -> tuple[int, int]:
    parser = _PlainTextHTMLParser()
    parser.feed(html_text)
    plain = parser.text()
    md = metadata or {}
    year = int(md.get("year") or 0)
    pos = int(md.get("pos") or md.get("position") or 0)
    url = f"https://api.sejm.gov.pl/eli/acts/DU/{year}/{pos}/text.html" if year and pos else ""
    return import_law_text(con, code, plain, md, url)


def update_law_from_eli(con: sqlite3.Connection, code: str) -> tuple[str, int]:
    """Pobiera tekst aktu z ELI w sposób odporny na różnice metadanych API.

    Najpierw próbujemy tekst HTML dla zapisanego/znalezionego roku i pozycji, bo ELI
    potrafi udostępniać poprawny ``text.html`` mimo braku lub innego kształtu flagi
    ``textHTML`` w metadanych. PDF jest dopiero bezpiecznym fallbackiem.
    """
    code = code.upper().strip()
    act = con.execute("SELECT * FROM law_acts WHERE code=?", (code,)).fetchone()
    if not act:
        raise ValueError(f"Nieznany akt: {code}")

    latest = {"year": act["year"], "pos": act["position"], "displayAddress": act["display_address"],
              "title": act["title"], "status": act["status"], "changeDate": act["change_date"]}
    # Wyszukiwanie nowszego tekstu jednolitego jest dodatkiem, a nie warunkiem działania biblioteki.
    try:
        found = find_latest_consolidated_act(code)
        if found:
            latest.update(found)
    except Exception:
        pass

    year = int(latest.get("year") or act["year"] or 0)
    pos = int(latest.get("pos") or latest.get("position") or act["position"] or 0)
    if not year or not pos:
        raise RuntimeError("Brak roku lub pozycji Dz.U. dla tego aktu.")

    try:
        meta = _http_json(f"https://api.sejm.gov.pl/eli/acts/DU/{year}/{pos}")
        if isinstance(meta, dict):
            latest = {**latest, **meta}
    except Exception:
        # Brak odpowiedzi metadanych nie blokuje pobrania samego tekstu.
        pass

    html_url = f"https://api.sejm.gov.pl/eli/acts/DU/{year}/{pos}/text.html"
    pdf_url = f"https://api.sejm.gov.pl/eli/acts/DU/{year}/{pos}/text.pdf"
    html_error = None
    try:
        html_text = _http_text(html_url)
        _, count = import_law_html(con, code, html_text, latest)
        if count:
            return str(latest.get("displayAddress") or f"Dz.U. {year} poz. {pos}"), count
        html_error = RuntimeError("ELI zwróciło HTML, ale nie udało się rozpoznać artykułów.")
    except Exception as exc:
        html_error = exc

    try:
        _, count = import_law_text(con, code, _pdf_to_text(_http_bytes(pdf_url)), latest, pdf_url)
        if count:
            return str(latest.get("displayAddress") or f"Dz.U. {year} poz. {pos}"), count
    except Exception as pdf_error:
        raise RuntimeError(
            "Nie udało się pobrać tekstu aktu z ELI. "
            f"HTML: {html_error}. PDF: {pdf_error}."
        ) from pdf_error

    raise RuntimeError("ELI zwróciło tekst aktu, ale nie udało się rozpoznać artykułów.")


def add_custom_eli_act(con: sqlite3.Connection, code: str, year: int, position: int, short_title: str, created_by: str = "") -> tuple[int, int]:
    code = code.upper().strip()[:24]
    if not code or not year or not position or not short_title.strip():
        raise ValueError("Kod, rok, pozycja i nazwa aktu są wymagane.")
    meta = _http_json(f"https://api.sejm.gov.pl/eli/acts/DU/{int(year)}/{int(position)}")
    title = str(meta.get("title") or short_title).strip()
    display = str(meta.get("displayAddress") or f"Dz.U. {year} poz. {position}")
    if meta.get("textHTML"):
        url = f"https://api.sejm.gov.pl/eli/acts/DU/{int(year)}/{int(position)}/text.html"
    else:
        url = f"https://api.sejm.gov.pl/eli/acts/DU/{int(year)}/{int(position)}/text.pdf"
    con.execute(
        """INSERT INTO law_acts(code,short_title,title,publisher,year,position,display_address,source_url,status,change_date,last_checked_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
           ON CONFLICT(code) DO UPDATE SET short_title=excluded.short_title,title=excluded.title,year=excluded.year,
           position=excluded.position,display_address=excluded.display_address,source_url=excluded.source_url,status=excluded.status,
           change_date=excluded.change_date,last_checked_at=CURRENT_TIMESTAMP""",
        (code, short_title.strip(), title, "DU", int(year), int(position), display, url,
         str(meta.get("status") or ""), str(meta.get("changeDate") or "")),
    )
    if meta.get("textHTML"):
        return import_law_html(con, code, _http_text(url), meta)
    if meta.get("textPDF"):
        return import_law_text(con, code, _pdf_to_text(_http_bytes(url)), meta, url)
    raise RuntimeError("ELI nie udostępnia tekstu tego aktu w HTML ani PDF.")

def _safe_date(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "")[:10])
    except (TypeError, ValueError):
        return None


def derive_case_auto_tags(con: sqlite3.Connection, case_id: int, today: date | None = None) -> list[tuple[str, str]]:
    today = today or date.today()
    c = con.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not c:
        return []
    blobs = [str(c[k] or "") for k in ("title", "category", "subject", "next_step", "waiting_for", "notes")]
    blobs += [str(r[0] or "") for r in con.execute("SELECT title FROM process_events WHERE case_id=? ORDER BY id DESC LIMIT 25", (case_id,)).fetchall()]
    blobs += [str(r[0] or "") for r in con.execute("SELECT title FROM documents WHERE case_id=? ORDER BY id DESC LIMIT 25", (case_id,)).fetchall()]
    text = " ".join(blobs).lower()
    tags: dict[str, str] = {}

    def add(tag: str, reason: str):
        tags[tag] = reason

    category_rules = [
        (("aliment",), "alimenty"),
        (("rozwód", "rozwod"), "rozwód"),
        (("zachowek",), "zachowek"),
        (("bezumown",), "bezumowne korzystanie"),
        (("egzekuc", "komorn"), "egzekucja"),
        (("mediac",), "mediacja"),
        (("biegł", "biegly", "opinia bieg"), "biegły"),
        (("apelac",), "apelacja"),
        (("zażalen", "zazalen"), "zażalenie"),
        (("administracyj", "kpa"), "administracyjne"),
        (("karne", "kpk", "prokur"), "karne"),
    ]
    for needles, tag in category_rules:
        if any(n in text for n in needles):
            add(tag, "wynika z opisu, dokumentów lub historii sprawy")
    if str(c["status"]) == "closed":
        add("zakończona", "status sprawy")
    else:
        add("aktywna", "status sprawy")
    if str(c["waiting_for"] or "").strip():
        add("oczekuje", f"czekamy na: {c['waiting_for']}")
    next_date = _safe_date(str(c["next_date"] or ""))
    if next_date:
        delta = (next_date - today).days
        if 0 <= delta <= 7:
            add("pilne", f"najbliższa data za {delta} dni")
        elif delta < 0:
            add("po terminie", "najbliższa data już minęła")
    open_deadline = con.execute(
        "SELECT due_date FROM tasks WHERE case_id=? AND status<>'done' AND due_date<>'' ORDER BY due_date LIMIT 1",
        (case_id,),
    ).fetchone()
    if open_deadline:
        d = _safe_date(open_deadline[0])
        if d and (d - today).days <= 7:
            add("pilne", "otwarty termin w ciągu 7 dni")
    con.execute("DELETE FROM case_auto_tags WHERE case_id=?", (case_id,))
    for tag, reason in sorted(tags.items(), key=lambda x: x[0].lower()):
        con.execute("INSERT INTO case_auto_tags(case_id,tag,reason,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP)", (case_id, tag, reason))
    return list(tags.items())


def case_parties(con: sqlite3.Connection, case_id: int) -> list[tuple[str, str]]:
    rows = con.execute("SELECT role,name FROM parties WHERE case_id=? ORDER BY id", (case_id,)).fetchall()
    out = [(str(r[0] or "").strip(), str(r[1] or "").strip()) for r in rows if str(r[1] or "").strip()]
    # Strukturalne podmioty mają pierwszeństwo, jeśli istnieją.
    structured = con.execute(
        """SELECT ce.role,e.display_name FROM case_entities ce JOIN entities e ON e.id=ce.entity_id
           WHERE ce.case_id=? ORDER BY ce.id""",
        (case_id,),
    ).fetchall()
    if structured:
        out = [(str(r[0] or "").strip(), str(r[1] or "").strip()) for r in structured if str(r[1] or "").strip()]
    return out


def _party_sentence(parties: list[tuple[str, str]]) -> str:
    if not parties:
        return ""
    shown = [f"{role}: {name}" if role else name for role, name in parties[:4]]
    extra = len(parties) - len(shown)
    return "; ".join(shown) + (f"; +{extra} innych" if extra > 0 else "")



def _detect_stage(con: sqlite3.Connection, c: sqlite3.Row) -> tuple[str, str]:
    """Krótki, użytkowy opis etapu zamiast technicznej klasyfikacji."""
    cid = int(c["id"])
    if str(c["status"] or "") == "closed":
        return "Zakończona", "Zakończona."

    today = date.today().isoformat()
    upcoming = con.execute(
        """SELECT event_date,event_type,title FROM process_events
           WHERE case_id=? AND event_date<>'' AND event_date>=?
           ORDER BY event_date,id LIMIT 1""",
        (cid, today),
    ).fetchone()
    if upcoming:
        typ = str(upcoming["event_type"] or "").strip()
        title = str(upcoming["title"] or "").strip()
        low = f"{typ} {title}".lower()
        if "rozpraw" in low:
            return "Przed rozprawą", f"Rozprawa: {upcoming['event_date']}."
        if "posiedzen" in low:
            return "Przed posiedzeniem", f"Posiedzenie: {upcoming['event_date']}."
        if "mediac" in low:
            return "Mediacja", f"Mediacja: {upcoming['event_date']}."
        return "W toku", f"Najbliższe wydarzenie: {upcoming['event_date']}."

    next_date = str(c["next_date"] or "").strip()
    next_step = str(c["next_step"] or "").strip()
    if next_date and next_date >= today:
        label = next_step or "Najbliższa czynność"
        return "W toku", f"{label.rstrip('.')}: {next_date}."

    process = con.execute(
        """SELECT event_date,event_type,title,description FROM process_events
           WHERE case_id=? ORDER BY COALESCE(NULLIF(event_date,''),'0000-00-00') DESC,id DESC LIMIT 6""",
        (cid,),
    ).fetchall()
    combined = " ".join(
        (str(r["event_type"] or "") + " " + str(r["title"] or "") + " " + str(r["description"] or ""))
        for r in process
    ).lower()
    if "egzekuc" in combined or "komorn" in combined:
        return "Egzekucja", "Egzekucja."
    if "apelac" in combined or "ii instanc" in combined:
        return "II instancja", "II instancja."
    if "wyrok" in combined or "orzeczen" in combined:
        return "Po orzeczeniu", "Po orzeczeniu."
    if "biegł" in combined or "opinia" in combined:
        return "Dowody", "Postępowanie dowodowe."
    if "mediac" in combined:
        return "Mediacja", "Mediacja / próba ugodowa."
    if process:
        return "W toku", "W toku."
    if con.execute("SELECT 1 FROM documents WHERE case_id=? LIMIT 1", (cid,)).fetchone():
        return "W toku", "W toku."
    return "Start", "Początek sprawy."


def generate_case_summary(con: sqlite3.Connection, case_id: int, force: bool = False) -> dict[str, str]:
    """Generuje krótkie teksty do prostego widoku sprawy."""
    c = con.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not c:
        raise ValueError("Nie znaleziono sprawy")
    process_count = con.execute("SELECT COUNT(*) FROM process_events WHERE case_id=?", (case_id,)).fetchone()[0]
    docs_count = con.execute("SELECT COUNT(*) FROM documents WHERE case_id=?", (case_id,)).fetchone()[0]
    tasks_open = con.execute("SELECT COUNT(*) FROM tasks WHERE case_id=? AND status<>'done'", (case_id,)).fetchone()[0]
    latest_doc = con.execute(
        """SELECT title FROM documents WHERE case_id=? AND COALESCE(parent_document_id,0)=0
           ORDER BY COALESCE(NULLIF(received_date,''),NULLIF(doc_date,''),created_at) DESC,id DESC LIMIT 1""",
        (case_id,),
    ).fetchone()
    fp_obj = {
        "case": {k: str(c[k] or "") for k in ("signature", "internal_signature", "title", "category", "subject", "status", "next_step", "next_date", "waiting_for", "updated_at")},
        "process_count": process_count,
        "docs_count": docs_count,
        "tasks_open": tasks_open,
        "latest_doc": str(latest_doc[0] if latest_doc else ""),
    }
    fingerprint = hashlib.sha256(json.dumps(fp_obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    cached = con.execute("SELECT * FROM case_generated_summary WHERE case_id=?", (case_id,)).fetchone()
    if cached and cached["fingerprint"] == fingerprint and not force:
        return {"description": cached["description"], "stage": cached["stage_summary"], "next": cached["next_action_summary"]}

    description = str(c["subject"] or c["title"] or "").strip().rstrip(".")
    description = (description + ".") if description else "Brak krótkiego opisu sprawy."
    _, stage_summary = _detect_stage(con, c)

    next_parts: list[str] = []
    next_step = str(c["next_step"] or "").strip()
    next_date = str(c["next_date"] or "").strip()
    if next_step and next_date:
        next_parts.append(f"{next_step.rstrip('.')} — {next_date}.")
    elif next_step:
        next_parts.append(f"{next_step.rstrip('.')}.")
    elif next_date:
        next_parts.append(f"Najbliższa data — {next_date}.")

    earliest_task = con.execute(
        """SELECT title,due_date FROM tasks
           WHERE case_id=? AND status<>'done'
           ORDER BY CASE WHEN due_date='' THEN 1 ELSE 0 END,due_date,id LIMIT 1""",
        (case_id,),
    ).fetchone()
    if earliest_task:
        task_text = str(earliest_task["title"] or "").strip()
        if earliest_task["due_date"]:
            task_text += f" — do {earliest_task['due_date']}"
        next_parts.append(task_text.rstrip(".") + ".")
    waiting = str(c["waiting_for"] or "").strip()
    if waiting:
        next_parts.append(f"Czekamy na: {waiting.rstrip('.')}.")

    next_summary = " ".join(next_parts[:2]) if next_parts else "Brak otwartych zadań."
    con.execute(
        """INSERT INTO case_generated_summary(case_id,description,stage_summary,next_action_summary,fingerprint,generated_at)
           VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
           ON CONFLICT(case_id) DO UPDATE SET description=excluded.description,stage_summary=excluded.stage_summary,
           next_action_summary=excluded.next_action_summary,fingerprint=excluded.fingerprint,generated_at=CURRENT_TIMESTAMP""",
        (case_id, description, stage_summary, next_summary, fingerprint),
    )
    return {"description": description, "stage": stage_summary, "next": next_summary}


def build_unified_timeline(con: sqlite3.Connection, case_id: int, limit: int = 100) -> list[dict]:
    """Historia sprawy bez zadań i alertów, aby nie dublować tej samej czynności."""
    items: list[dict] = []
    today = date.today().isoformat()

    for r in con.execute(
        "SELECT id,event_date,event_type,title,description,created_at FROM process_events WHERE case_id=?",
        (case_id,),
    ).fetchall():
        d = r["event_date"] or (r["created_at"] or "")[:10]
        if d and d > today:
            continue
        items.append({"date": d, "kind": "Proces", "type": r["event_type"], "title": r["title"],
                      "description": r["description"], "source_type": "process_event", "source_id": r["id"]})

    process_keys = {(str(x.get("date") or ""), re.sub(r"\W+", "", str(x.get("title") or "").lower())) for x in items}
    for r in con.execute(
        "SELECT id,event_date,event_type,title,description,created_at FROM events WHERE case_id=?",
        (case_id,),
    ).fetchall():
        d = r["event_date"] or (r["created_at"] or "")[:10]
        if d and d > today:
            continue
        key = (str(d or ""), re.sub(r"\W+", "", str(r["title"] or "").lower()))
        if key in process_keys:
            continue
        items.append({"date": d, "kind": "Czynność", "type": r["event_type"], "title": r["title"],
                      "description": r["description"], "source_type": "event", "source_id": r["id"]})

    for r in con.execute(
        """SELECT d.id,d.doc_date,d.received_date,d.delivered_date,d.doc_type,d.title,d.description,d.created_at,
                  (SELECT COUNT(*) FROM documents a WHERE a.parent_document_id=d.id) attachment_count
           FROM documents d WHERE d.case_id=? AND COALESCE(d.parent_document_id,0)=0""",
        (case_id,),
    ).fetchall():
        d = r["received_date"] or r["doc_date"] or (r["created_at"] or "")[:10]
        extras = []
        if r["received_date"]: extras.append(f"wpływ: {r['received_date']}")
        if r["delivered_date"]: extras.append(f"doręczenie: {r['delivered_date']}")
        if int(r["attachment_count"] or 0): extras.append(f"załączniki: {int(r['attachment_count'])}")
        desc = str(r["description"] or "").strip()
        if extras:
            desc = (desc + (" · " if desc else "") + ", ".join(extras)).strip()
        items.append({"date": d, "kind": "Dokument", "type": r["doc_type"], "title": r["title"],
                      "description": desc, "source_type": "document", "source_id": r["id"],
                      "attachment_count": int(r["attachment_count"] or 0)})

    items.sort(key=lambda x: (str(x.get("date") or ""), int(x.get("source_id") or 0)), reverse=True)
    return items[:limit]

def auto_create_structural_links(con: sqlite3.Connection, case_id: int) -> int:
    """Tworzy wyłącznie relacje wynikające jednoznacznie ze struktury danych."""
    count = 0
    docs = con.execute("SELECT id,linked_task_id FROM documents WHERE case_id=? AND linked_task_id IS NOT NULL", (case_id,)).fetchall()
    for d in docs:
        try:
            con.execute(
                "INSERT OR IGNORE INTO smart_links(case_id,source_type,source_id,target_type,target_id,relation_type,note,auto_created) VALUES(?,?,?,?,?,?,?,1)",
                (case_id, "document", d["id"], "task", d["linked_task_id"], "powiązane z", "Powiązanie zapisane przy dokumencie"),
            )
            count += con.execute("SELECT changes()").fetchone()[0]
        except sqlite3.DatabaseError:
            pass
    pe = con.execute("SELECT id,document_id FROM process_events WHERE case_id=? AND document_id IS NOT NULL", (case_id,)).fetchall()
    for x in pe:
        con.execute(
            "INSERT OR IGNORE INTO smart_links(case_id,source_type,source_id,target_type,target_id,relation_type,note,auto_created) VALUES(?,?,?,?,?,?,?,1)",
            (case_id, "document", x["document_id"], "process_event", x["id"], "powoduje", "Zdarzenie procesowe powiązane z dokumentem"),
        )
        count += con.execute("SELECT changes()").fetchone()[0]
    return count



def _task_alert_type(row: sqlite3.Row) -> str:
    task_type = str(row["task_type"] or "Zadanie").strip() if "task_type" in row.keys() else "Zadanie"
    if task_type in ALERT_TYPES:
        return task_type
    if ("deadline_base_date" in row.keys()) and str(row["deadline_base_date"] or "").strip():
        return "Termin procesowy"
    return "Zadanie"


def sync_task_alert(con: sqlite3.Connection, task_id: int, created_by: str = "") -> int | None:
    """Jedno zadanie z terminem = jeden powiązany alert w kalendarzu."""
    task = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        return None
    existing = con.execute(
        "SELECT * FROM alerts WHERE source_type='task' AND source_id=? ORDER BY id LIMIT 1",
        (task_id,),
    ).fetchone()
    due = str(task["due_date"] or "").strip()
    # Migracja DEV1/DEV2: jeżeli taki sam wpis kalendarza istniał wcześniej osobno,
    # przejmujemy go zamiast tworzyć drugi rekord.
    if not existing and due:
        existing = con.execute(
            """SELECT * FROM alerts WHERE case_id=? AND alert_date=? AND title=?
               AND (source_type IS NULL OR source_type='' OR source_id IS NULL)
               ORDER BY CASE WHEN alert_type=? THEN 0 ELSE 1 END,id LIMIT 1""",
            (task["case_id"], due, task["title"], _task_alert_type(task)),
        ).fetchone()
        if existing:
            con.execute("UPDATE alerts SET source_type='task',source_id=? WHERE id=?", (task_id, existing["id"]))
    if not due:
        if existing:
            con.execute("UPDATE alerts SET status='done',updated_at=CURRENT_TIMESTAMP WHERE id=?", (existing["id"],))
            return int(existing["id"])
        return None

    typ = _task_alert_type(task)
    status = "done" if str(task["status"] or "") == "done" else "open"
    priority = "high" if str(task["priority"] or "") == "high" else "normal"
    assigned = task["assigned_user_id"] if "assigned_user_id" in task.keys() else None
    desc = str(task["notes"] or "").strip()
    if existing:
        con.execute(
            """UPDATE alerts SET case_id=?,alert_date=?,alert_type=?,title=?,description=?,priority=?,status=?,
               assigned_user_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (task["case_id"], due, typ, task["title"], desc, priority, status, assigned, existing["id"]),
        )
        return int(existing["id"])
    cur = con.execute(
        """INSERT INTO alerts(case_id,alert_date,alert_type,title,description,priority,status,source_type,source_id,
                              assigned_user_id,created_by)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (task["case_id"], due, typ, task["title"], desc, priority, status, "task", task_id, assigned, created_by),
    )
    return int(cur.lastrowid)


def sync_alert_task(con: sqlite3.Connection, alert_id: int, created_by: str = "") -> int | None:
    """Monit/termin/płatność dodane w kalendarzu automatycznie stają się zadaniem."""
    alert = con.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    if not alert or str(alert["alert_type"] or "") not in ACTIONABLE_ALERT_TYPES or not alert["case_id"]:
        return None
    if str(alert["source_type"] or "") == "task" and alert["source_id"]:
        tid = int(alert["source_id"])
        if con.execute("SELECT 1 FROM tasks WHERE id=?", (tid,)).fetchone():
            return tid
    # Nie dubluj wpisów utworzonych wcześniej osobno jako „zadanie” i „monit”.
    match = con.execute(
        """SELECT id,task_type FROM tasks WHERE case_id=? AND title=? AND due_date=?
           ORDER BY CASE WHEN status='done' THEN 1 ELSE 0 END,id LIMIT 1""",
        (alert["case_id"], alert["title"], alert["alert_date"]),
    ).fetchone()
    if match:
        tid=int(match["id"])
        if str(match["task_type"] or "Zadanie") == "Zadanie" and str(alert["alert_type"] or "") != "Zadanie":
            con.execute("UPDATE tasks SET task_type=? WHERE id=?", (alert["alert_type"], tid))
        con.execute("UPDATE alerts SET source_type='task',source_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (tid, alert_id))
        return tid
    cur = con.execute(
        """INSERT INTO tasks(case_id,title,due_date,status,priority,assigned_user_id,depends_on,notes,task_type,
                             created_by,updated_by)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (alert["case_id"], alert["title"], alert["alert_date"],
         "done" if alert["status"] == "done" else "open",
         "high" if alert["priority"] in ("high", "critical") else "normal",
         alert["assigned_user_id"], "", alert["description"] or "", alert["alert_type"], created_by, created_by),
    )
    tid = int(cur.lastrowid)
    con.execute("UPDATE alerts SET source_type='task',source_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (tid, alert_id))
    return tid


def reconcile_task_alerts(con: sqlite3.Connection, created_by: str = "migracja") -> tuple[int, int]:
    """Idempotentnie scala stare osobne monity/alerty z zadaniami."""
    alert_count=0; task_count=0
    alerts=con.execute(
        """SELECT id FROM alerts WHERE case_id IS NOT NULL AND alert_type IN ('Zadanie','Monit','Termin procesowy','Płatność')
           ORDER BY id"""
    ).fetchall()
    for row in alerts:
        tid=sync_alert_task(con,int(row["id"]),created_by)
        if tid:
            sync_task_alert(con,tid,created_by)
            alert_count+=1
    tasks=con.execute("SELECT id FROM tasks ORDER BY id").fetchall()
    for row in tasks:
        sync_task_alert(con,int(row["id"]),created_by)
        task_count+=1
    return alert_count,task_count


NUMBER_WORDS = {
    "jeden": 1, "jednego": 1, "jedną": 1,
    "dwa": 2, "dwóch": 2, "trzy": 3, "cztery": 4, "pięć": 5, "piec": 5,
    "siedem": 7, "dziesięć": 10, "dziesiec": 10, "czternaście": 14, "czternascie": 14,
    "dwadzieścia jeden": 21, "dwadzieścia": 20, "trzydzieści": 30, "trzydziesci": 30,
}


def extract_explicit_deadline_suggestions(con: sqlite3.Connection, document_id: int) -> list[dict]:
    d = con.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if not d:
        return []
    text = str(d["extracted_text"] or "")
    if not text:
        return []
    # Tylko terminy jawnie zapisane w dokumencie. Nie wnioskujemy terminu z samego rodzaju pisma.
    patterns = [
        re.compile(r"(?i)(w\s+terminie\s+(\d{1,3})\s+dni(?:a|owym|owym)?[^\n\.]{0,120})"),
        re.compile(r"(?i)(w\s+ciągu\s+(\d{1,3})\s+dni[^\n\.]{0,120})"),
        re.compile(r"(?i)(nie\s+później\s+niż\s+w\s+terminie\s+(\d{1,3})\s+dni[^\n\.]{0,120})"),
    ]
    found: list[dict] = []
    seen = set()
    base = str(d["delivered_date"] or d["received_date"] or d["doc_date"] or "")
    for pat in patterns:
        for m in pat.finditer(text):
            phrase = re.sub(r"\s+", " ", m.group(1)).strip()[:260]
            days = int(m.group(2))
            key = (phrase.lower(), days)
            if key in seen:
                continue
            seen.add(key)
            title = f"Zweryfikować i wykonać termin wskazany w dokumencie ({days} dni)"
            con.execute(
                """INSERT OR IGNORE INTO deadline_suggestions(case_id,document_id,source_text,suggested_title,base_date,days,rule,legal_basis,confidence,status)
                   VALUES(?,?,?,?,?,?,'calendar','','do weryfikacji','open')""",
                (d["case_id"], document_id, phrase, title, base, days),
            )
            found.append({"source_text": phrase, "days": days, "base_date": base, "title": title})
    return found


def upcoming_alerts(con: sqlite3.Connection, user_id: int | None = None, days: int = 14) -> list[sqlite3.Row]:
    end = (date.today() + timedelta(days=days)).isoformat()
    today = date.today().isoformat()
    if user_id:
        return con.execute(
            """SELECT a.*,c.title case_title,c.signature,c.internal_signature FROM alerts a
               LEFT JOIN cases c ON c.id=a.case_id
               WHERE a.status='open' AND a.alert_date<=? AND (a.assigned_user_id IS NULL OR a.assigned_user_id=?)
               ORDER BY a.alert_date,a.priority DESC,a.id""",
            (end, user_id),
        ).fetchall()
    return con.execute(
        """SELECT a.*,c.title case_title,c.signature,c.internal_signature FROM alerts a
           LEFT JOIN cases c ON c.id=a.case_id WHERE a.status='open' AND a.alert_date<=?
           ORDER BY a.alert_date,a.priority DESC,a.id""",
        (end,),
    ).fetchall()


def search_law(con: sqlite3.Connection, query: str, code: str = "", limit: int = 80) -> list[sqlite3.Row]:
    query = (query or "").strip()
    code = (code or "").strip().upper()
    if not query:
        if code:
            return con.execute(
                """SELECT la.*,a.code,a.short_title FROM law_articles la JOIN law_acts a ON a.id=la.act_id
                   WHERE a.code=? ORDER BY la.sort_order LIMIT ?""",
                (code, limit),
            ).fetchall()
        return []
    # Najpierw dokładny numer artykułu.
    article_q = re.sub(r"(?i)^art\.?\s*", "", query).strip().rstrip(".")
    if re.fullmatch(r"[0-9]+(?:[a-zA-Z]|\[[0-9]+\]|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)?", article_q):
        if code:
            return con.execute(
                """SELECT la.*,a.code,a.short_title FROM law_articles la JOIN law_acts a ON a.id=la.act_id
                   WHERE a.code=? AND la.article_key=? ORDER BY la.sort_order LIMIT ?""",
                (code, article_q, limit),
            ).fetchall()
        return con.execute(
            """SELECT la.*,a.code,a.short_title FROM law_articles la JOIN law_acts a ON a.id=la.act_id
               WHERE la.article_key=? ORDER BY a.code,la.sort_order LIMIT ?""",
            (article_q, limit),
        ).fetchall()
    try:
        if code:
            return con.execute(
                """SELECT la.*,a.code,a.short_title FROM law_fts f
                   JOIN law_articles la ON la.id=f.article_id JOIN law_acts a ON a.id=la.act_id
                   WHERE law_fts MATCH ? AND f.act_code=? LIMIT ?""",
                (query, code, limit),
            ).fetchall()
        return con.execute(
            """SELECT la.*,a.code,a.short_title FROM law_fts f
               JOIN law_articles la ON la.id=f.article_id JOIN law_acts a ON a.id=la.act_id
               WHERE law_fts MATCH ? LIMIT ?""",
            (query, limit),
        ).fetchall()
    except sqlite3.DatabaseError:
        like = f"%{query}%"
        if code:
            return con.execute(
                """SELECT la.*,a.code,a.short_title FROM law_articles la JOIN law_acts a ON a.id=la.act_id
                   WHERE a.code=? AND (la.heading LIKE ? OR la.body LIKE ?) ORDER BY la.sort_order LIMIT ?""",
                (code, like, like, limit),
            ).fetchall()
        return con.execute(
            """SELECT la.*,a.code,a.short_title FROM law_articles la JOIN law_acts a ON a.id=la.act_id
               WHERE la.heading LIKE ? OR la.body LIKE ? ORDER BY a.code,la.sort_order LIMIT ?""",
            (like, like, limit),
        ).fetchall()
