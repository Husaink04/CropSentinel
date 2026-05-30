"""
CropSentinel Licensing — Verifier
=============================

Loads a license.key file, verifies its Ed25519 signature against the
embedded public key, and exposes a LicenseInfo object the rest of the
backend can query (feature flags, seat limit, expiry, etc).

STARTUP FLOW
------------
    from licensing.verifier import load_and_verify_license
    license_info = load_and_verify_license()   # raises LicenseError on failure
    app.state.license = license_info

After that, any request handler can do:
    if not app.state.license.has_feature("dlp_v2"):
        raise HTTPException(402, "DLP v2 not in your license")
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .keys import load_public_key
from .signer import canonical_json_bytes

logger = logging.getLogger("croppro.licensing")


# Default file locations — overridable via environment variables
DEFAULT_LICENSE_PATH = Path(
    os.getenv("CROPPRO_LICENSE_PATH", "license.key")
).resolve()
DEFAULT_PUBLIC_KEY_PATH = Path(
    os.getenv("CROPPRO_LICENSE_PUBKEY_PATH",
              str(Path(__file__).parent / "public_key.pem"))
).resolve()


# ── Exceptions ───────────────────────────────────────────────────────────────

class LicenseError(Exception):
    """Base class for any license-related failure."""


class LicenseMissingError(LicenseError):
    """License file does not exist on disk."""


class LicenseInvalidError(LicenseError):
    """License file is malformed or tampered (bad signature, bad JSON)."""


class LicenseExpiredError(LicenseError):
    """License has passed both its expiry date and its grace period."""


# ── LicenseInfo runtime object ───────────────────────────────────────────────

@dataclass
class LicenseInfo:
    """Parsed license — what the rest of the backend actually queries."""

    license_id:   str
    customer:     str
    tier:         str
    max_seats:    int
    features:     List[str]
    issued_at:    datetime
    expires_at:   datetime
    grace_days:   int
    max_tenants:  int
    hardware_binding: str
    notes:        str
    schema_version: int

    # ── Convenience ──────────────────────────────────────────────────────

    def has_feature(self, name: str) -> bool:
        return name in self.features

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return now > self.expires_at

    def is_in_grace(self, now: Optional[datetime] = None) -> bool:
        """True if past expiry but within the grace window."""
        now = now or datetime.now(timezone.utc)
        if now <= self.expires_at:
            return False
        from datetime import timedelta
        cutoff = self.expires_at + timedelta(days=self.grace_days)
        return now <= cutoff

    def days_remaining(self, now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        return (self.expires_at - now).days

    def to_public_dict(self) -> dict:
        """Safe dict to expose via /api/license/info (no secrets)."""
        return {
            "license_id":   self.license_id,
            "customer":     self.customer,
            "tier":         self.tier,
            "max_seats":    self.max_seats,
            "max_tenants":  self.max_tenants,
            "features":     list(self.features),
            "issued_at":    self.issued_at.isoformat(),
            "expires_at":   self.expires_at.isoformat(),
            "grace_days":   self.grace_days,
            "days_remaining": self.days_remaining(),
            "is_expired":   self.is_expired(),
            "is_in_grace":  self.is_in_grace(),
            "notes":        self.notes,
        }


# ── Loader / verifier ────────────────────────────────────────────────────────

def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 string into a timezone-aware datetime."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_and_verify_license(
    license_path: Path = DEFAULT_LICENSE_PATH,
    public_key_path: Path = DEFAULT_PUBLIC_KEY_PATH,
    allow_expired_in_grace: bool = True,
) -> LicenseInfo:
    """
    Load a license file, verify its signature, and return a LicenseInfo.

    Raises one of LicenseMissingError / LicenseInvalidError / LicenseExpiredError
    if anything is wrong.
    """
    # ── 1. File existence ───────────────────────────────────────────────
    if not license_path.exists():
        raise LicenseMissingError(
            f"License file not found at {license_path}. "
            f"Set CROPPRO_LICENSE_PATH or place license.key next to the backend."
        )
    if not public_key_path.exists():
        raise LicenseInvalidError(
            f"Public key not found at {public_key_path}. "
            f"This is a build error — the public key must ship with CropSentinel."
        )

    # ── 2. Parse JSON ───────────────────────────────────────────────────
    try:
        raw = json.loads(license_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise LicenseInvalidError(f"License file is not valid JSON: {e}")

    if not isinstance(raw, dict) or "payload" not in raw or "signature" not in raw:
        raise LicenseInvalidError(
            "License file missing 'payload' or 'signature' top-level keys."
        )

    payload = raw["payload"]
    signature_b64 = raw["signature"]

    if not isinstance(payload, dict):
        raise LicenseInvalidError("License 'payload' must be an object.")
    if not isinstance(signature_b64, str):
        raise LicenseInvalidError("License 'signature' must be a string.")

    # ── 3. Verify signature ─────────────────────────────────────────────
    try:
        public_key = load_public_key(public_key_path)
    except Exception as e:
        raise LicenseInvalidError(f"Failed to load public key: {e}")

    try:
        signature = base64.b64decode(signature_b64.encode("ascii"))
    except Exception:
        raise LicenseInvalidError("Signature is not valid base64.")

    payload_bytes = canonical_json_bytes(payload)

    try:
        public_key.verify(signature, payload_bytes)
    except InvalidSignature:
        raise LicenseInvalidError(
            "License signature is INVALID. The file may have been tampered "
            "with, or it was signed with a different key."
        )

    # ── 4. Validate required fields and build LicenseInfo ───────────────
    required = [
        "license_id", "customer", "tier", "max_seats", "features",
        "issued_at", "expires_at", "grace_days",
    ]
    missing = [k for k in required if k not in payload]
    if missing:
        raise LicenseInvalidError(f"License payload missing fields: {missing}")

    try:
        info = LicenseInfo(
            license_id    = str(payload["license_id"]),
            customer      = str(payload["customer"]),
            tier          = str(payload["tier"]),
            max_seats     = int(payload["max_seats"]),
            features      = list(payload["features"]),
            issued_at     = _parse_iso(payload["issued_at"]),
            expires_at    = _parse_iso(payload["expires_at"]),
            grace_days    = int(payload["grace_days"]),
            max_tenants   = int(payload.get("max_tenants", 1)),
            hardware_binding = str(payload.get("hardware_binding", "")),
            notes         = str(payload.get("notes", "")),
            schema_version = int(payload.get("schema_version", 1)),
        )
    except (ValueError, TypeError) as e:
        raise LicenseInvalidError(f"License payload has malformed field: {e}")

    # ── 5. Expiry check ─────────────────────────────────────────────────
    if info.is_expired():
        if info.is_in_grace() and allow_expired_in_grace:
            logger.warning(
                f"License {info.license_id} expired on {info.expires_at.date()} "
                f"but is in grace period ({info.grace_days} days). "
                f"Renew immediately."
            )
        else:
            raise LicenseExpiredError(
                f"License {info.license_id} expired on {info.expires_at.date()} "
                f"and is past the {info.grace_days}-day grace period."
            )

    logger.info(
        f"License OK: {info.license_id} ({info.tier}) for '{info.customer}', "
        f"{info.max_seats} seats, {info.days_remaining()} days remaining, "
        f"features={info.features}"
    )
    return info
