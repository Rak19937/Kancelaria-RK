"""CSRF double-submit derived from the unguessable per-session token.

The session cookie is HttpOnly. Token rendered into protected same-origin HTML
forms can be sent as a form field or as an X-RK-CSRF header by local JS.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from urllib.parse import urlsplit

FIELD = '_rk_csrf'
HEADER = 'X-RK-CSRF'


def csrf_for_session(session_token: str) -> str:
    if not session_token:
        return ''
    return hashlib.sha256(('rk-csrf-0.4-dev2:' + session_token).encode()).hexdigest()


def csrf_valid(session_token: str, fields: dict, headers) -> bool:
    expected = csrf_for_session(session_token)
    supplied = (fields.get(FIELD) or headers.get(HEADER) or '')
    return bool(expected and isinstance(supplied,str) and hmac.compare_digest(expected,supplied))


def csrf_html(content: str, token: str) -> str:
    if not token or not content:
        return content
    meta = f'<meta name="rk-csrf-token" content="{token}"><script src="/assets/rk_csrf.js" defer></script>'
    if '</head>' in content:
        content=content.replace('</head>',meta+'</head>',1)
    else:
        content=meta+content
    def inject(match):
        form=match.group(0)
        if not re.search(r'\bmethod\s*=\s*([\'\"]?)post\1(?:\s|>)', form, re.IGNORECASE):
            return form
        return form+f'<input type="hidden" name="{FIELD}" value="{token}">'
    return re.sub(r'<form\b[^>]*>',inject,content,flags=re.IGNORECASE)


def same_origin_request(headers) -> bool:
    """Reject cross-site POSTs; honor Host rather than untrusted proxy headers."""
    source=headers.get('Origin') or headers.get('Referer') or ''
    if not source:
        return True  # Non-browser clients still need a valid CSRF token.
    if source == 'null':
        return False
    try:
        src=urlsplit(source)
        host=urlsplit('//'+headers.get('Host',''))
        if src.scheme not in ('http','https') or not src.hostname or not host.hostname:
            return False
        src_port=src.port or (443 if src.scheme=='https' else 80)
        host_port=host.port or (443 if src.scheme=='https' else 80)
        return src.hostname.casefold()==host.hostname.casefold() and src_port==host_port
    except (ValueError,TypeError):
        return False
