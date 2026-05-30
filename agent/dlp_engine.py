"""
CropSentinel — Data Loss Prevention Engine v2.0
============================================

Context-aware DLP scanner for the CropSentinel agent.

v2 additions over v1:
  - File fingerprinting (SHA-256) — track sensitive files across copies/renames
  - Weighted risk scoring — replaces count-based logic with per-pattern weights
    and context modifiers (destination, time, behaviour)
  - Destination awareness — USB, upload, cloud sync detection built into the
    scan pipeline
  - Enriched event payloads — file_hash, destination, risk_score, breakdown

Usage:
    from dlp_engine import DLPEngine

    engine = DLPEngine()
    result = engine.scan(file_content_string)
    # result = {"risk": "high", "findings": [...], "total_weight": 15}

    # v2 full pipeline
    result = engine.scan_file_v2(
        file_path="/home/user/Documents/secrets.csv",
        destination="usb",
        device="E:",
        is_repeated=False,
    )
    # result = {
    #     "risk_level": "high",
    #     "risk_score": 21,
    #     "file_hash": "abc123...",
    #     "is_known_sensitive": True,
    #     "destination": "usb",
    #     "device": "E:",
    #     "findings": [...],
    #     "scoring": { "base_score": 16, "context_bonus": 5, "breakdown": {...} },
    #     "fingerprint": { "source": "copied", "first_seen": "..." },
    # }

Extensible:
    engine.add_keywords(["PROJECT_ALPHA", "merger"])
    engine.set_custom_patterns({"aws_secret": r"..."})
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Pattern

from enterprise_labels import derive_enterprise_label

logger = logging.getLogger("croppro.dlp")

# ═════════════════════════════════════════════════════════════════════════════
#  BUILT-IN DETECTION PATTERNS
# ═════════════════════════════════════════════════════════════════════════════

# Each tuple: (pattern_name, compiled_regex, risk_weight)
# risk_weight is the v1 weight (kept for backward compat); v2 scoring uses
# dlp_scoring.PATTERN_WEIGHTS which override these per-pattern.

_BUILTIN_PATTERNS: List[tuple] = [
    # ── PII ───────────────────────────────────────────────────────────────
    (
        "email",
        re.compile(
            r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,7}\b"
        ),
        1,
    ),
    (
        "phone",
        re.compile(
            r"(?<!\d)"
            r"(?:"
            r"\+?\d{1,3}[\s\-]?"
            r"(?:\(\d{2,4}\)|\d{2,4})"
            r"[\s\-]?\d{3,4}[\s\-]?\d{3,4}"
            r"|"
            r"\(\d{3}\)\s?\d{3}[\-\s]?\d{4}"
            r"|"
            r"\d{3}[\-\.]\d{3}[\-\.]\d{4}"
            r")"
            r"(?!\d)"
        ),
        1,
    ),
    (
        "ssn",
        re.compile(
            r"\b\d{3}[\-\s]\d{2}[\-\s]\d{4}\b"
        ),
        3,
    ),
    (
        "aadhaar",
        re.compile(
            r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}\b"
        ),
        3,
    ),
    (
        "pan_card",
        re.compile(
            r"\b[A-Z]{5}\d{4}[A-Z]\b"
        ),
        2,
    ),

    # ── Financial ─────────────────────────────────────────────────────────
    (
        "credit_card",
        re.compile(
            r"\b(?:"
            r"4\d{3}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"
            r"|5[1-5]\d{2}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"
            r"|3[47]\d{2}[\s\-]?\d{6}[\s\-]?\d{5}"
            r"|6(?:011|5\d{2})[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}"
            r")\b"
        ),
        3,
    ),
    (
        "iban",
        re.compile(
            r"\b[A-Z]{2}\d{2}[\s]?[A-Z0-9]{4}[\s]?(?:\d{4}[\s]?){2,7}\d{1,4}\b"
        ),
        2,
    ),
    (
        "bank_account",
        re.compile(
            r"(?i)(?:account|acct|a/c)[\s#:.\-]*\d{8,18}"
        ),
        2,
    ),

    # ── Credentials / Secrets ─────────────────────────────────────────────
    (
        "api_key",
        re.compile(
            r"(?i)"
            r"(?:api[_\-]?key|apikey|access[_\-]?key|secret[_\-]?key|auth[_\-]?token)"
            r"[\s]*[=:]\s*['\"]?"
            r"([A-Za-z0-9\-_\.]{16,128})"
        ),
        3,
    ),
    (
        "aws_key",
        re.compile(
            r"(?:AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}"
        ),
        3,
    ),
    (
        "private_key",
        re.compile(
            r"-----BEGIN\s(?:RSA\s|EC\s|DSA\s|OPENSSH\s)?PRIVATE\sKEY-----"
        ),
        3,
    ),
    (
        "password_in_text",
        re.compile(
            r"(?i)"
            r"(?:password|passwd|pwd|pass)\s{0,5}[=:]\s{0,5}['\"]?"
            r"([^\s'\"]{6,64})"
        ),
        3,
    ),
    (
        "jwt_token",
        re.compile(
            r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
        ),
        3,
    ),
    (
        "connection_string",
        re.compile(
            r"(?i)"
            r"(?:postgresql|mysql|mongodb|redis|amqp|mssql|sqlite)"
            r"://[^\s'\"]{10,256}"
        ),
        3,
    ),

    # ── Source Code / IP ──────────────────────────────────────────────────
    (
        "ipv4_private",
        re.compile(
            r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)"
            r"\.\d{1,3}\.\d{1,3}\b"
        ),
        1,
    ),
]


# ═════════════════════════════════════════════════════════════════════════════
#  RISK CLASSIFICATION (v1 compat — v2 uses dlp_scoring.classify_risk)
# ═════════════════════════════════════════════════════════════════════════════

def _classify_risk(total_weight: int) -> str:
    if total_weight == 0:
        return "none"
    if total_weight <= 2:
        return "low"
    if total_weight <= 6:
        return "medium"
    return "high"


# ═════════════════════════════════════════════════════════════════════════════
#  FILE TYPE FILTERING
# ═════════════════════════════════════════════════════════════════════════════

BINARY_EXTENSIONS = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".o", ".obj", ".bin", ".dat",
    ".pyc", ".pyo", ".class", ".jar", ".war",
    ".iso", ".img", ".vmdk", ".vdi",
    ".mp4", ".mkv", ".avi", ".mov", ".mp3", ".wav", ".flac",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg",
    ".pdf",
    ".woff", ".woff2", ".ttf", ".eot",
})

MAX_SCAN_SIZE = 1 * 1024 * 1024
MAX_SCAN_CHARS = 500_000


# ═════════════════════════════════════════════════════════════════════════════
#  DLP ENGINE
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Finding:
    """Single finding from a DLP scan."""
    pattern_type: str
    count: int
    weight: int

    def to_dict(self) -> dict:
        return {"type": self.pattern_type, "count": self.count}


class DLPEngine:
    """
    Context-aware DLP scanner (v2).

    Thread-safe: all state is read-only after construction (patterns are
    compiled once).  The scan() method can be called from any thread.

    v2 additions:
      - scan_file_v2() — full pipeline with fingerprinting, scoring, destination
      - Fingerprint store integration (lazy-loaded)
      - Weighted scoring via dlp_scoring module
    """

    def __init__(
        self,
        enabled: bool = True,
        custom_keywords: Optional[List[str]] = None,
        custom_patterns: Optional[Dict[str, str]] = None,
        risk_thresholds: Optional[Dict[str, int]] = None,
    ):
        self.enabled = enabled

        self._patterns: List[tuple] = list(_BUILTIN_PATTERNS)

        if custom_keywords:
            self.add_keywords(custom_keywords)
        if custom_patterns:
            self.set_custom_patterns(custom_patterns)

        self._thresholds = risk_thresholds or {
            "low": 1,
            "medium": 3,
            "high": 7,
        }

        # v2 subsystems (lazy-loaded to keep startup fast)
        self._fingerprint_store = None
        self._scoring_loaded = False

    # ── v1 API (unchanged for backward compat) ────────────────────────────

    def scan(self, content: str) -> dict:
        """
        Scan text content for sensitive data patterns.

        Returns:
            {"risk": "none|low|medium|high",
             "findings": [{"type": ..., "count": ...}, ...],
             "total_weight": int}
        """
        if not self.enabled or not content:
            return {"risk": "none", "findings": [], "total_weight": 0}

        text = content[:MAX_SCAN_CHARS]

        findings: List[Finding] = []
        total_weight = 0

        for name, pattern, weight in self._patterns:
            try:
                matches = pattern.findall(text)
                count = len(matches)
                if count > 0:
                    findings.append(Finding(name, count, weight))
                    total_weight += weight * min(count, 10)
            except re.error:
                logger.debug(f"DLP regex error for pattern '{name}'")

        risk = self._classify(total_weight)

        return {
            "risk": risk,
            "findings": [f.to_dict() for f in findings],
            "total_weight": total_weight,
        }

    def scan_bytes(self, data: bytes, encoding: str = "utf-8") -> dict:
        if not self.enabled or not data:
            return {"risk": "none", "findings": [], "total_weight": 0}
        try:
            text = data.decode(encoding, errors="ignore")
        except Exception:
            return {"risk": "none", "findings": [], "total_weight": 0}
        return self.scan(text)

    def should_scan_file(self, file_path: str, file_size: int = 0) -> bool:
        if not self.enabled:
            return False
        if file_size > MAX_SCAN_SIZE:
            return False
        ext = os.path.splitext(file_path)[1].lower()
        if ext in BINARY_EXTENSIONS:
            return False
        return True

    # ── v2 API — Full Context-Aware Pipeline ──────────────────────────────

    def scan_file_v2(
        self,
        file_path: str,
        content: str,
        destination: str = "local",
        device: str = "",
        is_repeated: bool = False,
        file_size: int = 0,
        file_ext: str = "",
        file_hash: str = "",
    ) -> Optional[dict]:
        """
        Full v2 DLP scan pipeline:

        1. Run regex patterns on content → findings
        2. Compute file SHA-256 fingerprint
        3. Check fingerprint store → is_known_sensitive
        4. Compute weighted risk score with context
        5. Record fingerprint if sensitive
        6. Return enriched event or None (if no risk)

        Args:
            file_path:    full path to the file being scanned
            content:      text content (already read, up to MAX_SCAN_CHARS)
            destination:  "usb" | "upload" | "cloud_sync" | "local"
            device:       device label (e.g. "E:" or "drive.google.com")
            is_repeated:  True if this machine has had multiple DLP alerts recently

        Returns:
            dict with enriched DLP event data, or None if risk == "none"
        """
        if not self.enabled or not content:
            return None

        # Step 1: Run regex scan
        scan_result = self.scan(content)
        findings = scan_result["findings"]
        label_summary = derive_enterprise_label(
            findings,
            risk=scan_result.get("risk", "none"),
            risk_score=int(scan_result.get("total_weight", 0) or 0),
            inspect_status="inspected",
        )

        # Step 2: Compute file hash
        file_hash = file_hash or self._compute_hash(content)

        # Step 3: Check fingerprint store
        fp_store = self._get_fingerprint_store()
        is_known = False
        fp_known_hash = False  # Fix 4: hash already in store (any path)
        fp_info = None
        if fp_store:
            existing = fp_store.lookup(file_hash)
            if existing:
                fp_known_hash = True
                # Mark "known sensitive copy" only when this hash was first
                # seen at a *different* path (i.e., genuinely a copy)
                if existing.file_path != file_path:
                    is_known = True
                    fp_info = {
                        "source": existing.source,
                        "first_seen": existing.first_seen,
                        "original_path": existing.file_path,
                    }

        # If no findings from regex BUT the file is a known sensitive copy,
        # still flag it (the content hasn't changed, it's been copied)
        if not findings and not is_known:
            return None

        # Step 4: Weighted risk scoring (Fix 3, 4 — file context + fingerprint signal)
        scoring = self._score_v2(
            findings=findings,
            destination=destination,
            is_repeated=is_repeated,
            is_known_sensitive=is_known,
            file_size=file_size,
            file_ext=file_ext,
            fingerprint_known=fp_known_hash,
        )

        # If score is zero and not a known sensitive file, skip
        if scoring["total_score"] <= 0 and not is_known:
            return None

        risk_level = scoring["risk_level"]
        risk_score = scoring["total_score"]

        # Step 5: Record fingerprint for sensitive files
        if fp_store and (findings or is_known):
            file_name = os.path.basename(file_path)
            fp_store.record(
                file_hash=file_hash,
                file_path=file_path,
                file_name=file_name,
                risk_level=risk_level,
                risk_score=risk_score,
                findings=findings,
            )

        # Step 6: Build enriched event
        result = {
            "file_hash":          file_hash,
            "is_known_sensitive": is_known,
            "destination":        destination,
            "device":             device,
            "risk_level":         risk_level,
            "risk_score":         risk_score,
            "findings":           findings,
            "scoring":            scoring,
            "label_summary":      label_summary,
        }

        if fp_info:
            result["fingerprint"] = fp_info

        return result

    # ── Configuration ─────────────────────────────────────────────────────

    def add_keywords(self, keywords: List[str]):
        for kw in keywords:
            if not kw or len(kw) < 2:
                continue
            try:
                pat = re.compile(r"(?i)\b" + re.escape(kw) + r"\b")
                self._patterns.append(("keyword:" + kw.lower(), pat, 2))
            except re.error:
                logger.warning(f"DLP: invalid keyword pattern '{kw}'")

    def set_custom_patterns(self, patterns: Dict[str, str]):
        for name, regex_str in patterns.items():
            try:
                pat = re.compile(regex_str)
                self._patterns.append((f"custom:{name}", pat, 2))
            except re.error as e:
                logger.warning(f"DLP: invalid custom pattern '{name}': {e}")

    def update_config(
        self,
        enabled: Optional[bool] = None,
        keywords: Optional[List[str]] = None,
        custom_patterns: Optional[Dict[str, str]] = None,
        risk_thresholds: Optional[Dict[str, int]] = None,
    ):
        if enabled is not None:
            self.enabled = enabled
        if risk_thresholds:
            self._thresholds.update(risk_thresholds)
        if keywords is not None:
            self._patterns = [
                p for p in self._patterns if not p[0].startswith("keyword:")
            ]
            self.add_keywords(keywords)
        if custom_patterns is not None:
            self._patterns = [
                p for p in self._patterns if not p[0].startswith("custom:")
            ]
            self.set_custom_patterns(custom_patterns)

    # ── Internal ──────────────────────────────────────────────────────────

    def _classify(self, total_weight: int) -> str:
        """v1 classification (used by scan() for backward compat)."""
        if total_weight == 0:
            return "none"
        if total_weight < self._thresholds.get("medium", 3):
            return "low"
        if total_weight < self._thresholds.get("high", 7):
            return "medium"
        return "high"

    def _compute_hash(self, content: str) -> str:
        """SHA-256 of the content string."""
        import hashlib
        return hashlib.sha256(
            content.encode("utf-8", errors="ignore")
        ).hexdigest()

    def _get_fingerprint_store(self):
        """Lazy-load the fingerprint store."""
        if self._fingerprint_store is None:
            try:
                from dlp_fingerprint import FingerprintStore
                self._fingerprint_store = FingerprintStore()
                logger.info("DLP fingerprint store loaded")
            except Exception as e:
                logger.debug(f"Fingerprint store not available: {e}")
                self._fingerprint_store = False   # sentinel
        return self._fingerprint_store if self._fingerprint_store is not False else None

    def _score_v2(
        self,
        findings: list,
        destination: str,
        is_repeated: bool,
        is_known_sensitive: bool,
        file_size: int = 0,
        file_ext: str = "",
        fingerprint_known: bool = False,
    ) -> dict:
        """Run the v2 weighted scoring engine."""
        try:
            from dlp_scoring import (
                score_dlp_event,
                is_outside_working_hours,
            )
            result = score_dlp_event(
                findings=findings,
                destination=destination,
                is_outside_hours=is_outside_working_hours(),
                repeated=is_repeated,
                is_known_sensitive=is_known_sensitive,
                file_size=file_size,
                file_ext=file_ext,
                fingerprint_known=fingerprint_known,
            )
            return result.to_dict()
        except ImportError:
            # Fallback to v1 scoring if dlp_scoring not available
            logger.debug("dlp_scoring not available, falling back to v1")
            total = sum(
                f.get("count", 0) * 2 for f in findings
            )
            from dlp_scoring import classify_risk
            return {
                "base_score": total,
                "context_bonus": 0,
                "total_score": total,
                "risk_level": _classify_risk(total),
                "breakdown": {},
            }

    def cleanup_fingerprints(self):
        """Run periodic cleanup of the fingerprint store."""
        store = self._get_fingerprint_store()
        if store:
            store.cleanup()
