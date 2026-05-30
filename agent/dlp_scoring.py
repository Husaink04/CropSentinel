"""
CropSentinel — DLP Weighted Risk Scoring Engine v2
===============================================

Replaces the simple count-based risk classification from v1 with a
context-aware, weighted scoring system that factors in:

  1. Pattern weights    — what type of sensitive data was found
  2. Destination        — where is the file going (USB, upload, local)
  3. Time context       — is this outside working hours?
  4. Behavioural signal — has this machine shown repeated DLP activity?

Final score → risk level:
    0     → none
    1-5   → low
    6-12  → medium
    13+   → high

Thread-safe: stateless scoring functions, no mutable shared state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("croppro.dlp.scoring")


# ═════════════════════════════════════════════════════════════════════════════
#  PATTERN WEIGHTS
# ═════════════════════════════════════════════════════════════════════════════

# Weight assigned to each finding type.
# These replace the old per-pattern weight (1-3) with more granular values.
# Key = pattern name from dlp_engine._BUILTIN_PATTERNS
# Missing patterns fall back to DEFAULT_WEIGHT.

PATTERN_WEIGHTS: Dict[str, int] = {
    # ── Credentials / Secrets (highest risk) ─────────────────────────────
    "api_key":            10,
    "aws_key":            10,
    "private_key":        10,
    "connection_string":   9,
    "jwt_token":           8,
    "password_in_text":    8,

    # ── Financial ────────────────────────────────────────────────────────
    "credit_card":         8,
    "iban":                6,
    "bank_account":        6,

    # ── PII (government IDs) ────────────────────────────────────────────
    "ssn":                 7,
    "aadhaar":             7,
    "pan_card":            5,

    # ── PII (contact) ───────────────────────────────────────────────────
    "email":               2,
    "phone":               2,

    # ── Network / infrastructure ─────────────────────────────────────────
    "ipv4_private":        1,
}

DEFAULT_WEIGHT = 3   # for custom:* and keyword:* patterns


# ═════════════════════════════════════════════════════════════════════════════
#  FILE TYPE SENSITIVITY (Fix 3)
# ═════════════════════════════════════════════════════════════════════════════

# Extensions that inherently carry higher risk (secrets, configs, databases)
HIGH_SENSITIVITY_EXTENSIONS = frozenset({
    ".env", ".pem", ".key", ".pfx", ".p12", ".sql", ".db", ".bak",
    ".conf", ".cfg", ".ini", ".properties", ".credentials",
})

# Standard data/code files
MEDIUM_SENSITIVITY_EXTENSIONS = frozenset({
    ".csv", ".json", ".xml", ".yml", ".yaml", ".xlsx", ".docx",
    ".py", ".js", ".ts", ".java", ".go", ".rb", ".php", ".cs",
})

# Low sensitivity — log files, temp, etc.
LOW_SENSITIVITY_EXTENSIONS = frozenset({
    ".log", ".tmp", ".txt", ".md", ".rst",
})

# File size thresholds for scoring adjustment
FILE_SIZE_LARGE = 10 * 1024 * 1024   # 10 MB — bulk data export risk


# ═════════════════════════════════════════════════════════════════════════════
#  CONTEXT MODIFIERS
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ContextModifiers:
    """Adjustments applied on top of the base content score."""

    destination_usb:          int = 5
    destination_upload:       int = 6
    destination_cloud_sync:   int = 3
    outside_working_hours:    int = 3
    repeated_detection:       int = 2   # same machine, multiple DLP alerts recently
    known_sensitive_copy:     int = 4   # file fingerprint matches known sensitive file
    # Fix 3: file context modifiers
    high_sensitivity_ext:     int = 3   # .env, .pem, .sql, etc.
    medium_sensitivity_ext:   int = 1   # .csv, .json, .py, etc.
    large_file_bonus:         int = 2   # files > 10 MB (bulk data export risk)
    # Fix 4: fingerprint-based repeated detection
    fingerprint_known:        int = 3   # file hash already in fingerprint store


# Default instance — importable as a constant
MODIFIERS = ContextModifiers()


# ═════════════════════════════════════════════════════════════════════════════
#  WORKING HOURS
# ═════════════════════════════════════════════════════════════════════════════

# Default 09:00–19:00 local time.  Overridable via server config.
WORK_HOUR_START = 9
WORK_HOUR_END   = 19


def is_outside_working_hours(
    ts: Optional[datetime] = None,
    start: int = WORK_HOUR_START,
    end: int = WORK_HOUR_END,
) -> bool:
    """
    Check if the given (or current) local time is outside working hours.
    Weekends (Sat=5, Sun=6) always count as outside.
    """
    now = ts or datetime.now()
    if now.weekday() >= 5:      # Saturday or Sunday
        return True
    return now.hour < start or now.hour >= end


# ═════════════════════════════════════════════════════════════════════════════
#  SCORING FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ScoringResult:
    """Full breakdown of a DLP risk score."""

    base_score: int             = 0
    context_bonus: int          = 0
    total_score: int            = 0
    risk_level: str             = "none"
    breakdown: Dict[str, int]   = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "base_score":    self.base_score,
            "context_bonus": self.context_bonus,
            "total_score":   self.total_score,
            "risk_level":    self.risk_level,
            "breakdown":     self.breakdown,
        }


def compute_base_score(findings: List[dict]) -> tuple[int, Dict[str, int]]:
    """
    Compute base risk score from DLP findings.

    Args:
        findings: list of {"type": "credit_card", "count": 2} dicts

    Returns:
        (total_score, breakdown_dict)
        breakdown: {"credit_card": 16, "email": 4, ...}
    """
    total = 0
    breakdown: Dict[str, int] = {}

    for f in findings:
        ptype = f.get("type", "")
        count = f.get("count", 0)
        if count <= 0:
            continue

        weight = PATTERN_WEIGHTS.get(ptype, DEFAULT_WEIGHT)

        # Diminishing returns: first match = full weight, subsequent matches
        # contribute 1 point each (up to 5 extra).  Prevents a file with
        # 50 email addresses from drowning out a single API key.
        score = weight + min(count - 1, 5)

        breakdown[ptype] = score
        total += score

    return total, breakdown


def compute_context_bonus(
    destination: str = "local",
    is_outside_hours: bool = False,
    repeated: bool = False,
    is_known_sensitive: bool = False,
    file_ext: str = "",
    file_size: int = 0,
    fingerprint_known: bool = False,
    modifiers: ContextModifiers = MODIFIERS,
) -> tuple[int, Dict[str, int]]:
    """
    Compute context-based risk bonus.

    Returns:
        (bonus_total, bonus_breakdown)
    """
    bonus = 0
    breakdown: Dict[str, int] = {}

    if destination == "usb":
        bonus += modifiers.destination_usb
        breakdown["destination_usb"] = modifiers.destination_usb
    elif destination == "upload":
        bonus += modifiers.destination_upload
        breakdown["destination_upload"] = modifiers.destination_upload
    elif destination == "cloud_sync":
        bonus += modifiers.destination_cloud_sync
        breakdown["destination_cloud_sync"] = modifiers.destination_cloud_sync

    if is_outside_hours:
        bonus += modifiers.outside_working_hours
        breakdown["outside_working_hours"] = modifiers.outside_working_hours

    if repeated:
        bonus += modifiers.repeated_detection
        breakdown["repeated_detection"] = modifiers.repeated_detection

    if is_known_sensitive:
        bonus += modifiers.known_sensitive_copy
        breakdown["known_sensitive_copy"] = modifiers.known_sensitive_copy

    # Fix 3: file type sensitivity
    ext = file_ext.lower()
    if ext in HIGH_SENSITIVITY_EXTENSIONS:
        bonus += modifiers.high_sensitivity_ext
        breakdown["high_sensitivity_ext"] = modifiers.high_sensitivity_ext
    elif ext in MEDIUM_SENSITIVITY_EXTENSIONS:
        bonus += modifiers.medium_sensitivity_ext
        breakdown["medium_sensitivity_ext"] = modifiers.medium_sensitivity_ext
    # LOW_SENSITIVITY_EXTENSIONS → no bonus (baseline)

    # Fix 3: large file bonus (bulk data export risk)
    if file_size > FILE_SIZE_LARGE:
        bonus += modifiers.large_file_bonus
        breakdown["large_file_bonus"] = modifiers.large_file_bonus

    # Fix 4: fingerprint already exists → repeated exfiltration signal
    if fingerprint_known:
        bonus += modifiers.fingerprint_known
        breakdown["fingerprint_known"] = modifiers.fingerprint_known

    return bonus, breakdown


def classify_risk(score: int) -> str:
    """Map total weighted score to risk level string."""
    if score <= 0:
        return "none"
    if score <= 5:
        return "low"
    if score <= 12:
        return "medium"
    return "high"


def score_dlp_event(
    findings: List[dict],
    destination: str = "local",
    is_outside_hours: bool = False,
    repeated: bool = False,
    is_known_sensitive: bool = False,
    file_ext: str = "",
    file_size: int = 0,
    fingerprint_known: bool = False,
    modifiers: ContextModifiers = MODIFIERS,
) -> ScoringResult:
    """
    Full scoring pipeline: base score + context bonus → risk level.

    This is the main entry point called by file_tracker after a DLP scan.
    """
    base, base_bd = compute_base_score(findings)
    bonus, bonus_bd = compute_context_bonus(
        destination=destination,
        is_outside_hours=is_outside_hours,
        repeated=repeated,
        is_known_sensitive=is_known_sensitive,
        file_ext=file_ext,
        file_size=file_size,
        fingerprint_known=fingerprint_known,
        modifiers=modifiers,
    )

    total = base + bonus
    risk = classify_risk(total)

    breakdown = {**base_bd, **bonus_bd}

    return ScoringResult(
        base_score=base,
        context_bonus=bonus,
        total_score=total,
        risk_level=risk,
        breakdown=breakdown,
    )
