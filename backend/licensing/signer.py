"""
CropSentinel Licensing — Signer
===========================

Creates a signed license file from a license payload dict.

A CropSentinel license file is plain JSON with two top-level keys:

    {
      "payload": { ... license details ... },
      "signature": "<base64 Ed25519 signature over canonical payload JSON>"
    }

The payload is serialized with sort_keys=True and separators=(",", ":")
to produce a deterministic byte sequence. The signature is computed over
those exact bytes. Verification must use the same canonicalization, or
the check will fail.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


# ── Canonicalization ─────────────────────────────────────────────────────────

def canonical_json_bytes(payload: dict) -> bytes:
    """
    Return a deterministic UTF-8 encoding of the payload.
    Sorted keys, no whitespace — critical for signature reproducibility.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


# ── License payload model ───────────────────────────────────────────────────

@dataclass
class LicensePayload:
    """All fields that go into a CropSentinel license file payload."""

    license_id: str                  # e.g. "CP-2026-0001"
    customer: str                    # e.g. "Acme Corp LLC"
    tier: str                        # "starter" | "professional" | "enterprise" | "msp"
    max_seats: int                   # maximum concurrent active agents
    features: List[str]              # enabled feature flags
    issued_at: str                   # ISO-8601 UTC timestamp
    expires_at: str                  # ISO-8601 UTC timestamp
    grace_days: int = 14             # days after expiry CropSentinel stays functional
    max_tenants: int = 1             # how many tenants this install may host (MSP > 1)
    hardware_binding: str = ""       # optional machine fingerprint hash
    notes: str = ""                  # free-form notes (visible to customer)
    schema_version: int = 2          # payload schema version for forward compat

    def to_dict(self) -> dict:
        return asdict(self)


def build_payload(
    license_id: str,
    customer: str,
    tier: str,
    max_seats: int,
    features: List[str],
    valid_days: int = 365,
    grace_days: int = 14,
    max_tenants: int = 1,
    hardware_binding: str = "",
    notes: str = "",
) -> LicensePayload:
    """
    Helper: build a LicensePayload with issued_at=now and
    expires_at=now+valid_days.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expiry = now + timedelta(days=valid_days)
    return LicensePayload(
        license_id=license_id,
        customer=customer,
        tier=tier,
        max_seats=max_seats,
        features=features,
        issued_at=now.isoformat(),
        expires_at=expiry.isoformat(),
        grace_days=grace_days,
        max_tenants=max_tenants,
        hardware_binding=hardware_binding,
        notes=notes,
    )


# ── Signing ──────────────────────────────────────────────────────────────────

def sign_license(
    payload: LicensePayload, private_key: Ed25519PrivateKey,
) -> dict:
    """
    Produce the full license dict (payload + base64 signature).
    """
    payload_bytes = canonical_json_bytes(payload.to_dict())
    signature = private_key.sign(payload_bytes)
    return {
        "payload": payload.to_dict(),
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def write_license_file(license_dict: dict, path: Path) -> None:
    """Write the signed license dict to a .key file (pretty JSON, human-readable)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(license_dict, indent=2, sort_keys=True),
        encoding="utf-8",
    )
