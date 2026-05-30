"""
CropSentinel Licensing — Key management
===================================

Helpers for generating, loading, and saving Ed25519 keypairs used to
sign and verify CropSentinel license files.

Ed25519 is a modern digital signature algorithm:
  - Tiny keys (32 bytes)
  - Fast signing and verification
  - Strong security (roughly equivalent to 3072-bit RSA)
  - Standardized (RFC 8032), widely supported

USAGE
-----
We generate ONE keypair in our lifetime as a company:
  - private_key  → stays on a secure offline machine (never committed to git)
  - public_key   → embedded in backend/licensing/public_key.pem and SHIPPED
                   inside CropSentinel so every deployment can verify licenses

We use `tools/generate_keypair.py` once to create both files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


# ── Generation ───────────────────────────────────────────────────────────────

def generate_keypair() -> Tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Create a fresh Ed25519 keypair."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


# ── Save ─────────────────────────────────────────────────────────────────────

def save_private_key(private_key: Ed25519PrivateKey, path: Path) -> None:
    """Write the private key to a PEM file (unencrypted — keep the file safe)."""
    pem_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pem_bytes)
    # Best-effort: restrict perms on Unix
    try:
        import os
        import stat
        os.chmod(str(path), stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


def save_public_key(public_key: Ed25519PublicKey, path: Path) -> None:
    """Write the public key to a PEM file (safe to share / commit)."""
    pem_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pem_bytes)


# ── Load ─────────────────────────────────────────────────────────────────────

def load_private_key(path: Path) -> Ed25519PrivateKey:
    """Load a private key from a PEM file."""
    pem_bytes = path.read_bytes()
    key = serialization.load_pem_private_key(pem_bytes, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"Expected Ed25519 private key, got {type(key).__name__}")
    return key


def load_public_key(path: Path) -> Ed25519PublicKey:
    """Load a public key from a PEM file."""
    pem_bytes = path.read_bytes()
    key = serialization.load_pem_public_key(pem_bytes)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError(f"Expected Ed25519 public key, got {type(key).__name__}")
    return key
