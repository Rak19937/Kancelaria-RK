"""Obsługa formularzy multipart; żadnej zależności od serwera aplikacji."""
from __future__ import annotations
from email.parser import BytesParser
from email.policy import default as email_policy

def parse_multipart(headers, body: bytes):
    ctype = headers.get("Content-Type", "")
    synthetic = (f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n").encode() + body
    msg = BytesParser(policy=email_policy).parsebytes(synthetic)
    fields: dict[str, str] = {}
    files: dict[str, object] = {}
    if not msg.is_multipart():
        return fields, files
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if not name:
            continue
        if filename:
            item = (filename, payload, part.get_content_type())
            # Pola zakończone [] mogą zawierać wiele plików (np. załączniki do pisma).
            if name.endswith("[]"):
                files.setdefault(name, [])
                files[name].append(item)
            else:
                files[name] = item
        else:
            charset = part.get_content_charset() or "utf-8"
            try: fields[name] = payload.decode(charset)
            except Exception: fields[name] = payload.decode("utf-8", "replace")
    return fields, files
