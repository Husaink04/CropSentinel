"""Local phishing detection and backend-assisted verdicting for the agent."""

from __future__ import annotations

import logging
import re
import threading
import time
from math import log2
from typing import Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger("croppro.agent.phishing")

DEFAULT_POLICY = {
    "phishing_enabled": True,
    "rollout_mode": "warn_only",
    "intel_mode": "intel_plus_heuristics",
    "protected_channels": ["browser", "download", "desktop_link_open", "email_client_open"],
    "severity_thresholds": {"medium": 55, "high": 75, "critical": 90},
    "allowlists": {"domains": [], "apps": [], "users": [], "paths": []},
    "blocklists": {"domains": [], "url_patterns": []},
    "suspicious_tlds": ["zip", "click", "work", "country", "gq", "tk", "ru"],
    "brand_watchlist": ["microsoft", "google", "apple", "okta", "adobe", "dropbox", "slack", "paypal", "amazon", "github", "office365", "outlook", "bank"],
}

KNOWN_BAD_DOMAINS = {
    "login-microsoftonline-security.com",
    "okta-authenticate-secure.com",
    "github-verify-login.com",
    "dropbox-shared-docs-login.com",
}


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    total = len(value)
    return round(-sum((count / total) * log2(count / total) for count in counts.values()), 3)


class PhishingProtection:
    def __init__(self, machine_id: str, actor_username: str, post_json_fn: Callable[[str, dict], dict] | None = None):
        self.machine_id = machine_id
        self.actor_username = actor_username
        self.policy = dict(DEFAULT_POLICY)
        self.policy_version = 1
        self.policy_hash = ""
        self._post_json = post_json_fn
        self._recent_backend_checks: dict[str, tuple[float, dict]] = {}

    def update_policy(self, policy: dict | None, version: int | None = None, policy_hash: str = ""):
        incoming = dict(DEFAULT_POLICY)
        incoming.update(policy or {})
        self.policy = incoming
        self.policy_version = int(version or incoming.get("policy_version") or 1)
        self.policy_hash = str(policy_hash or incoming.get("policy_hash") or "")

    def extract_url_features(self, url: str, title: str = "") -> dict[str, Any]:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = str(parsed.netloc or parsed.path or "").lower().strip()
        suspicious_keywords = [term for term in ("login", "signin", "verify", "secure", "auth", "password", "update") if term in url.lower()]
        subdomain_depth = max(0, len(host.split(".")) - 2) if "." in host else 0
        return {
            "host": host,
            "url_length": len(url or ""),
            "host_length": len(host),
            "path_length": len(parsed.path or ""),
            "subdomain_depth": subdomain_depth,
            "dot_count": host.count("."),
            "special_char_count": sum(1 for char in url if not char.isalnum()),
            "has_ip_host": bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host)),
            "has_punycode": "xn--" in host,
            "uses_https": parsed.scheme.lower() == "https",
            "entropy": _shannon_entropy(host),
            "suspicious_keywords": suspicious_keywords,
            "has_login_title": any(term in str(title or "").lower() for term in ("sign in", "login", "verify", "password", "authenticate")),
        }

    def _local_verdict(self, entry: dict, app_name: str = "", process_name: str = "") -> dict[str, Any] | None:
        if not self.policy.get("phishing_enabled", True):
            return None
        if "browser" not in set(self.policy.get("protected_channels", ["browser"])):
            return None
        domain = str(entry.get("domain") or urlparse(entry.get("url") or "").netloc or "").lower().strip()
        if not domain:
            return None
        allow_domains = {str(v).lower().strip() for v in (self.policy.get("allowlists", {}) or {}).get("domains", [])}
        if domain in allow_domains:
            return None

        url = str(entry.get("url") or "")
        title = str(entry.get("title") or "")
        features = self.extract_url_features(url, title)
        reason_codes: list[str] = []
        score = 0

        if domain in set((self.policy.get("blocklists", {}) or {}).get("domains", [])):
            score += 100
            reason_codes.append("blocklisted_domain")
        for pattern in (self.policy.get("blocklists", {}) or {}).get("url_patterns", []):
            pattern = str(pattern).strip().lower()
            if pattern and pattern in url.lower():
                score += 100
                reason_codes.append("blocklisted_url_pattern")
                break
        if domain in KNOWN_BAD_DOMAINS:
            score += 85
            reason_codes.append("known_malicious_domain")

        tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
        if tld in set(self.policy.get("suspicious_tlds", [])):
            score += 20
            reason_codes.append("suspicious_tld")

        for brand in self.policy.get("brand_watchlist", []):
            brand = str(brand).lower()
            if brand in domain and f".{brand}." not in f".{domain}." and not domain.startswith(f"{brand}."):
                score += 35
                reason_codes.append("lookalike_brand_domain")
                break

        if features["has_ip_host"]:
            score += 25
            reason_codes.append("ip_literal_host")
        if features["has_punycode"]:
            score += 20
            reason_codes.append("punycode_host")
        if int(features["subdomain_depth"]) >= 3:
            score += 10
            reason_codes.append("high_subdomain_depth")
        if float(features["entropy"]) >= 3.6:
            score += 10
            reason_codes.append("high_host_entropy")
        if len(features["suspicious_keywords"]) >= 2:
            score += 10
            reason_codes.append("multiple_suspicious_keywords")
        if not features["uses_https"]:
            score += 10
            reason_codes.append("no_https")
        if features["has_login_title"]:
            score += 15
            reason_codes.append("credential_harvest_title")
        if any(term in url.lower() for term in ("signin", "login", "verify", "auth", "password")):
            score += 10
            reason_codes.append("credential_harvest_url")
        if app_name and app_name.lower() not in {"chrome", "msedge", "edge", "firefox", "safari", "browser"}:
            score += 5
            reason_codes.append("non_browser_open_surface")

        thresholds = self.policy.get("severity_thresholds", DEFAULT_POLICY["severity_thresholds"])
        severity = "low"
        verdict = "clean"
        if score >= thresholds.get("critical", 90):
            severity = "critical"
            verdict = "malicious"
        elif score >= thresholds.get("high", 75):
            severity = "high"
            verdict = "malicious"
        elif score >= thresholds.get("medium", 55):
            severity = "medium"
            verdict = "suspicious"
        return {
            "domain": domain,
            "url": url,
            "title": title,
            "score": score,
            "severity": severity,
            "verdict": verdict,
            "reason_codes": reason_codes,
            "features": features,
            "app_name": app_name or entry.get("browser", ""),
            "process_name": process_name or entry.get("browser", ""),
        }

    def _backend_check(self, local: dict[str, Any]) -> dict | None:
        if not self._post_json:
            return None
        cache_key = f"{local['domain']}|{local['verdict']}"
        cached = self._recent_backend_checks.get(cache_key)
        now = time.time()
        if cached and now - cached[0] < 60:
            return cached[1]
        payload = {
            "machine_id": self.machine_id,
            "url": local["url"],
            "user_id": self.actor_username,
            "app_name": local["app_name"],
            "process_name": local["process_name"],
            "page_title": local["title"],
            "channel": "browser",
            "initial_agent_verdict": local["verdict"],
            "local_features": local["features"],
        }
        try:
            result = self._post_json("/api/phishing/check", payload)
        except Exception as exc:
            logger.debug("Backend phishing check failed for domain=%s err=%s", local["domain"], exc)
            return None
        if isinstance(result, dict):
            self._recent_backend_checks[cache_key] = (now, result)
            return result
        return None

    def evaluate_browser_entry(self, entry: dict, app_name: str = "", process_name: str = "") -> dict | None:
        local = self._local_verdict(entry, app_name=app_name, process_name=process_name)
        if not local:
            return None

        final_verdict = local["verdict"]
        severity = local["severity"]
        risk_score = local["score"]
        confidence = round(min(0.99, max(0.1, risk_score / 100.0)), 2) if risk_score else 0.0
        reason_codes = list(local["reason_codes"])
        action_taken = "monitor"
        action_result = "observed"
        unsupported_reason = ""

        if local["verdict"] in {"suspicious", "malicious"}:
            backend = self._backend_check(local)
            if backend:
                final_verdict = str(backend.get("verdict") or final_verdict)
                severity = str(backend.get("severity") or severity)
                risk_score = int(backend.get("risk_score", risk_score) or risk_score)
                confidence = float(backend.get("confidence", confidence) or confidence)
                reason_codes = list(backend.get("reason_codes") or reason_codes)
                action_taken = str(backend.get("action") or action_taken)
                action_result = "backend_verdict"
            elif self.policy.get("rollout_mode") == "warn_only":
                action_taken = "warn_user"
                action_result = "warning_requested"

        if final_verdict == "clean":
            return None
        if action_taken == "allow":
            return None
        if action_taken == "block":
            unsupported_reason = "post_navigation_detection_only"
        elif action_taken == "warn_user":
            action_result = "warning_requested"

        warning_text = self._warning_text(local["domain"], severity, reason_codes)
        return {
            "machine_id": self.machine_id,
            "timestamp": entry.get("timestamp"),
            "event_type": "browser_visit",
            "channel": "browser",
            "url": entry.get("url", ""),
            "domain": local["domain"],
            "page_title": entry.get("title", ""),
            "app_name": local["app_name"],
            "process_name": local["process_name"],
            "actor_username": self.actor_username,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "rule_id": "phishing_heuristics_v2",
            "risk_score": risk_score,
            "confidence": confidence,
            "severity": severity,
            "action_taken": action_taken,
            "action_result": action_result,
            "reason_codes": reason_codes,
            "evidence": [{"domain": local["domain"], "title": entry.get("title", ""), "reason_codes": reason_codes, "features": local["features"]}],
            "unsupported_reason": unsupported_reason,
            "local_features": local["features"],
            "_warning_text": warning_text,
        }

    def warn_user(self, event: dict) -> None:
        if not event or event.get("action_taken") not in {"warn_user", "block"}:
            return
        message = str(event.get("_warning_text") or self._warning_text(event.get("domain", ""), event.get("severity", "medium"), event.get("reason_codes", [])))
        try:
            from ctypes import windll

            threading.Thread(
                target=lambda: windll.user32.MessageBoxW(0, message, "CropSentinel phishing warning", 0x30),
                daemon=True,
            ).start()
            logger.warning("Phishing warning shown for domain=%s severity=%s action=%s", event.get("domain", ""), event.get("severity", "medium"), event.get("action_taken", "warn_user"))
        except Exception as exc:
            logger.warning("Phishing warning fallback domain=%s error=%s", event.get("domain", ""), exc)

    def _warning_text(self, domain: str, severity: str, reason_codes: list[str]) -> str:
        reasons = ", ".join(reason_codes[:3]) if reason_codes else "suspicious activity"
        return (
            f"CropSentinel detected a {severity} phishing risk.\n\n"
            f"Domain: {domain}\n"
            f"Reason: {reasons}\n\n"
            "Do not enter credentials or download files.\n"
            "Close the page and contact your administrator if this was unexpected."
        )
