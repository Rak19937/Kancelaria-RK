#!/usr/bin/env python3
from __future__ import annotations

import os
import http.cookiejar
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def get(url: str) -> tuple[int, str, dict[str, str]]:
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, res.read().decode("utf-8", "replace"), dict(res.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers)


def main() -> int:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    css = (ROOT / "assets" / "rk_app.css").read_text(encoding="utf-8")
    assert ".calendar-grid" in css and "repeat(7,minmax(0,1fr))" in css
    assert ".case-workspace-sticky" in css
    assert ".module-tabs" in css
    assert '("/drafts", "✎", "Pisma", "drafts")' in source
    assert '("/draft/templates", "▣", "Szablony pism"' not in source
    assert "class='calendar-board'" in source
    assert not (ROOT / "rk_app.css").exists(), "CSS w katalogu głównym znów dubluje assets"
    assert not (ROOT / "rk_app.js").exists(), "JS w katalogu głównym znów dubluje assets"

    with tempfile.TemporaryDirectory(prefix="rk_dev4_") as tmp:
        env = os.environ.copy()
        env.update({
            "SPRAWNIK_DATA_DIR": tmp,
            "SPRAWNIK_PORT": "18765",
            "SPRAWNIK_OPEN_BROWSER": "0",
            "SPRAWNIK_AUTO_SHUTDOWN": "0",
        })
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "app.py")],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            base = "http://127.0.0.1:18765"
            for _ in range(60):
                try:
                    status, _, _ = get(base + "/assets/rk_app.css")
                    if status == 200:
                        break
                except OSError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Serwer testowy nie wystartował")

            status, served_css, headers = get(base + "/assets/rk_app.css")
            assert status == 200
            assert ".calendar-grid" in served_css
            assert headers.get("ETag"), "Brak ETag dla zasobów statycznych"

            req = urllib.request.Request(base + "/assets/rk_app.css", headers={"If-None-Match": headers["ETag"]})
            try:
                urllib.request.urlopen(req, timeout=5)
                raise AssertionError("Oczekiwano odpowiedzi 304")
            except urllib.error.HTTPError as exc:
                assert exc.code == 304

            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            setup_data = urllib.parse.urlencode({
                "username": "admin",
                "author_name": "Test",
                "function": "Test",
                "password": "testowe123",
                "password2": "testowe123",
            }).encode()
            opener.open(urllib.request.Request(base + "/setup", data=setup_data), timeout=10).read()

            calendar_html = opener.open(base + "/calendar", timeout=10).read().decode("utf-8")
            assert "class='calendar-board'" in calendar_html
            assert "class='calendar-grid'" in calendar_html

            projects_html = opener.open(base + "/drafts", timeout=10).read().decode("utf-8")
            templates_html = opener.open(base + "/drafts?view=templates", timeout=10).read().decode("utf-8")
            assert "<h1>Pisma</h1>" in projects_html and "Projekty</a>" in projects_html
            assert "<h1>Pisma</h1>" in templates_html and "Szablony</a>" in templates_html
            assert "Szablony pism</span>" not in projects_html
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if proc.returncode not in (0, 1, -15):
            err = proc.stderr.read() if proc.stderr else ""
            raise AssertionError(f"Serwer zakończył się kodem {proc.returncode}: {err}")

    print("TEST_UI_PERFORMANCE_DEV4: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
