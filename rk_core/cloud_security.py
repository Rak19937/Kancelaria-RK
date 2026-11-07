"""Client-only encryption of Cloud snapshots (no secrets held by Cloud Bridge).

Payload: RKCLD2 + random salt(16) + nonce(12) + AES-256-GCM ciphertext/tag.
Passphrase is supplied anew by a person when pushing/pulling a snapshot. The
application does not save it in app_settings, audit logs or server responses.
"""
from __future__ import annotations

import os
import ipaddress
from urllib.parse import urlsplit

MAGIC = b'RKCLD2'
SALT_BYTES = 16
NONCE_BYTES = 12
KDF_ITERATIONS = 600_000

class CloudCryptoError(ValueError):
    pass


def validate_cloud_url(url: str) -> str:
    """Allow HTTPS remote hosts and HTTP only to literal local loopback addresses."""
    raw = str(url or '').strip().rstrip('/')
    parsed = urlsplit(raw)
    if not raw or parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise CloudCryptoError('Adres Cloud wymaga HTTPS (lokalnie dopuszczalny jest HTTP na 127.0.0.1/localhost).')
    if parsed.scheme == 'http':
        try:
            local = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            local = parsed.hostname.lower() == 'localhost'
        if not local:
            raise CloudCryptoError('Zdalny Cloud wymaga HTTPS. HTTP jest dozwolony tylko na localhost.')
    return raw


def _key(passphrase: str, salt: bytes) -> bytes:
    if not isinstance(passphrase,str) or len(passphrase) < 12:
        raise CloudCryptoError('Podaj hasło szyfrowania Cloud (co najmniej 12 znaków).')
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    kdf=PBKDF2HMAC(algorithm=hashes.SHA256(),length=32,salt=salt,iterations=KDF_ITERATIONS)
    return kdf.derive(passphrase.encode('utf-8'))


def encrypt_cloud_snapshot(plaintext: bytes, passphrase: str) -> bytes:
    if not isinstance(plaintext,bytes) or not plaintext.startswith(b'PK'):
        raise CloudCryptoError('Szyfrowany snapshot musi być archiwum ZIP.')
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt=os.urandom(SALT_BYTES);nonce=os.urandom(NONCE_BYTES)
    header=MAGIC+salt+nonce
    return header+AESGCM(_key(passphrase,salt)).encrypt(nonce,plaintext,header)


def decrypt_cloud_snapshot(payload: bytes, passphrase: str) -> bytes:
    if not isinstance(payload,bytes) or not payload.startswith(MAGIC):
        raise CloudCryptoError('Snapshot Cloud nie jest zaszyfrowany w formacie 0.4-dev2. Starszą kopię przywróć osobno po weryfikacji.')
    offset=len(MAGIC)
    if len(payload)<offset+SALT_BYTES+NONCE_BYTES+16:
        raise CloudCryptoError('Niekompletny snapshot Cloud.')
    salt=payload[offset:offset+SALT_BYTES]
    nonce=payload[offset+SALT_BYTES:offset+SALT_BYTES+NONCE_BYTES]
    header=payload[:offset+SALT_BYTES+NONCE_BYTES]
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        plaintext=AESGCM(_key(passphrase,salt)).decrypt(nonce,payload[len(header):],header)
    except CloudCryptoError:
        raise
    except Exception as exc:
        raise CloudCryptoError('Nieprawidłowe hasło szyfrowania lub uszkodzony snapshot Cloud.') from exc
    if not plaintext.startswith(b'PK'):
        raise CloudCryptoError('Odszyfrowany snapshot nie jest archiwum ZIP.')
    return plaintext
