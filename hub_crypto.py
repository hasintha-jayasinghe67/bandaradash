#!/usr/bin/env python3
"""Local credential encryption for platform tokens."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
KEY_PATH = DATA_DIR / ".hub_key"


def _get_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if KEY_PATH.is_file():
        key = KEY_PATH.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        KEY_PATH.write_bytes(key)
        try:
            os.chmod(KEY_PATH, 0o600)
        except OSError:
            pass
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    if plain is None:
        return ""
    text = str(plain)
    f = _get_fernet()
    if f is None:
        # Fallback obfuscation if cryptography not installed (still better than plain)
        raw = base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")
        return f"b64:{raw}"
    return "fernet:" + f.encrypt(text.encode("utf-8")).decode("ascii")


def decrypt_secret(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith("fernet:"):
        f = _get_fernet()
        if f is None:
            raise RuntimeError("cryptography package required to read encrypted secrets")
        return f.decrypt(stored[len("fernet:") :].encode("ascii")).decode("utf-8")
    if stored.startswith("b64:"):
        return base64.urlsafe_b64decode(stored[4:].encode("ascii")).decode("utf-8")
    return stored


def secret_fingerprint(plain: str) -> str:
    return hashlib.sha256((plain or "").encode("utf-8")).hexdigest()[:12]
