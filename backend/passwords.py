"""
Password hashing: bcrypt (current) with transparent verification of legacy SHA-256 hex.
Successful login with a legacy hash triggers an upgrade to bcrypt in the DB.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

import bcrypt

# SHA-256 hex digest length
_LEGACY_HEX_LEN = 64
_LEGACY_HEX = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def _bcrypt_bytes(password: str) -> bytes:
    b = password.encode("utf-8")
    return b[:72] if len(b) > 72 else b


def is_legacy_sha256_hex(stored: Optional[str]) -> bool:
    if not stored or not isinstance(stored, str):
        return False
    s = stored.strip()
    return len(s) == _LEGACY_HEX_LEN and bool(_LEGACY_HEX.match(s))


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_bcrypt_bytes(plain), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    if is_legacy_sha256_hex(stored):
        return hashlib.sha256(plain.encode("utf-8")).hexdigest() == stored.lower()
    try:
        return bcrypt.checkpw(_bcrypt_bytes(plain), stored.encode("ascii"))
    except (ValueError, TypeError):
        return False


def upgrade_hash_if_legacy(plain: str, stored: Optional[str]) -> Optional[str]:
    """If legacy hash verified, return new bcrypt hash; else None."""
    if not is_legacy_sha256_hex(stored):
        return None
    if not verify_password(plain, stored):
        return None
    return hash_password(plain)
