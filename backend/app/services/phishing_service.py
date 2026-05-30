"""Phishing policy resolution, evaluation, and incident orchestration."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from math import log2
from urllib.parse import urlparse

from app.monitoring import set_sentry_tags
from database import db, set_tenant_context, utcnow

logger = logging.getLogger("croppro.phishing")

DEFAULT_THREAT_DOMAINS = {
    "login-microsoftonline-security.com",
    "okta-authenticate-secure.com",
    "github-verify-login.com",
    "dropbox-shared-docs-login.com",
}

LOCAL_BLOCK_REASONS = {
    "blocklisted_domain": 100,
    "known_malicious_domain": 85,
    "ip_literal_host": 25,
    "punycode_host": 20,
    "high_subdomain_depth": 10,
}

DEFAULT_POLICY = {
    "phishing_enabled": True,
    "rollout_mode": "warn_only",
    "intel_mode": "intel_plus_heuristics",
    "protected_channels": ["browser", "download", "desktop_link_open", "email_client_open"],
    "severity_thresholds": {"medium": 55, "high": 75, "critical": 90},
    "allowlists": {"domains": [], "apps": [], "users": [], "paths": []},
    "suspicious_tlds": ["zip", "click", "work", "country", "gq", "tk", "ru"],
    "brand_watchlist": ["microsoft", "google", "apple", "okta", "adobe", "dropbox", "slack", "paypal", "amazon", "github", "office365", "outlook", "bank"],
    "download_risk_rules": {"dangerous_extensions": ["exe", "msi", "bat", "cmd", "ps1", "scr", "vbs", "js", "jar", "iso", "zip"], "warn_unknown_downloads": True},
    "evidence_controls": {"capture_title": True, "store_masked_indicators": True, "store_url": True},
}

SEVERITY_RANK = {"low": 1, "medium": 2, "warning": 2, "high": 3, "critical": 4}


def _json_loads(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _policy_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _normalize_policy(row: dict) -> dict:
    item = dict(row)
    for key, default in (
        ("protected_channels", DEFAULT_POLICY["protected_channels"]),
        ("severity_thresholds", DEFAULT_POLICY["severity_thresholds"]),
        ("allowlists", DEFAULT_POLICY["allowlists"]),
        ("suspicious_tlds", DEFAULT_POLICY["suspicious_tlds"]),
        ("brand_watchlist", DEFAULT_POLICY["brand_watchlist"]),
        ("download_risk_rules", DEFAULT_POLICY["download_risk_rules"]),
        ("evidence_controls", DEFAULT_POLICY["evidence_controls"]),
        ("config", {}),
    ):
        item[key] = _json_loads(item.get(key), default)
    return item


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    total = len(value)
    return round(-sum((count / total) * log2(count / total) for count in counts.values()), 3)


class PhishingService:
    @staticmethod
    def _machine_prefix(machine_id: str) -> str:
        machine_id = str(machine_id or "")
        return machine_id[:8] if machine_id else ""

    def ensure_seeded(self, tenant_id: int) -> None:
        baseline = next((p for p in db.list_phishing_policies(1, scope="platform_baseline")), None)
        if not baseline:
            db.create_phishing_policy(
                {
                    "scope": "platform_baseline",
                    "name": "Platform Baseline Phishing Policy",
                    "description": "Mandatory baseline phishing detection and warning policy.",
                    "status": "published",
                    "priority": 1000,
                    "version": 1,
                    "rollout_mode": "warn_only",
                    "intel_mode": "intel_plus_heuristics",
                    "is_baseline": True,
                    "is_mandatory": True,
                    "published_at": utcnow(),
                    "published_by": "system",
                    **DEFAULT_POLICY,
                },
                tenant_id=1,
            )
        if tenant_id != 1:
            existing = next((p for p in db.list_phishing_policies(tenant_id, scope="tenant_override")), None)
            if not existing:
                db.create_phishing_policy(
                    {
                        "scope": "tenant_override",
                        "name": "Tenant Phishing Override",
                        "description": "Tenant-level phishing policy generated from system defaults.",
                        "status": "published",
                        "priority": 100,
                        "version": 1,
                        "rollout_mode": "warn_only",
                        "intel_mode": "intel_plus_heuristics",
                        "published_at": utcnow(),
                        "published_by": "system",
                        **DEFAULT_POLICY,
                    },
                    tenant_id=tenant_id,
                )

    def get_effective_policy(self, tenant_id: int) -> dict:
        self.ensure_seeded(tenant_id)
        baseline = [_normalize_policy(p) for p in db.list_phishing_policies(1, scope="platform_baseline") if p.get("status") == "published"]
        tenant_policies = [_normalize_policy(p) for p in db.list_phishing_policies(tenant_id, scope="tenant_override") if p.get("status") == "published"]
        # list_phishing_policies returns newest rows first, so choose index 0.
        chosen = (baseline[0] if baseline else {}) | (tenant_policies[0] if tenant_policies else {})
        allowlists = {"domains": [], "apps": [], "users": [], "paths": []}
        for source in baseline + tenant_policies:
            src_allow = source.get("allowlists") or {}
            for key in allowlists:
                allowlists[key].extend(src_allow.get(key, []) or [])
        for row in db.list_phishing_allowlist_exceptions(tenant_id=tenant_id):
            domain = (row.get("domain") or "").strip().lower()
            if domain:
                allowlists["domains"].append(domain)
        blocklists = {"domains": [], "url_patterns": []}
        for row in db.list_phishing_blocklist_exceptions(tenant_id=tenant_id):
            domain = (row.get("domain") or "").strip().lower()
            if domain:
                blocklists["domains"].append(domain)
            url_pattern = (row.get("url_pattern") or "").strip().lower()
            if url_pattern:
                blocklists["url_patterns"].append(url_pattern)
        payload = {
            "tenant_id": tenant_id,
            "phishing_enabled": bool(chosen.get("phishing_enabled", True)),
            "rollout_mode": chosen.get("rollout_mode", "warn_only"),
            "intel_mode": chosen.get("intel_mode", "intel_plus_heuristics"),
            "protected_channels": chosen.get("protected_channels") or DEFAULT_POLICY["protected_channels"],
            "severity_thresholds": chosen.get("severity_thresholds") or DEFAULT_POLICY["severity_thresholds"],
            "allowlists": {k: sorted({str(v).strip().lower() for v in vals if str(v).strip()}) for k, vals in allowlists.items()},
            "blocklists": {k: sorted({str(v).strip().lower() for v in vals if str(v).strip()}) for k, vals in blocklists.items()},
            "suspicious_tlds": list(chosen.get("suspicious_tlds") or DEFAULT_POLICY["suspicious_tlds"]),
            "brand_watchlist": list(chosen.get("brand_watchlist") or DEFAULT_POLICY["brand_watchlist"]),
            "download_risk_rules": chosen.get("download_risk_rules") or DEFAULT_POLICY["download_risk_rules"],
            "evidence_controls": chosen.get("evidence_controls") or DEFAULT_POLICY["evidence_controls"],
            "policies": baseline + tenant_policies,
            "threat_intel_domains": sorted(DEFAULT_THREAT_DOMAINS),
        }
        payload["policy_version"] = max((int(p.get("version", 1) or 1) for p in baseline + tenant_policies), default=1)
        payload["policy_hash"] = _policy_hash(payload)
        return payload

    def list_policies(self, tenant_id: int) -> list[dict]:
        self.ensure_seeded(tenant_id)
        return [_normalize_policy(p) for p in db.list_phishing_policies(tenant_id)]

    def extract_url_features(self, url: str, page_title: str = "") -> dict:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = (parsed.netloc or parsed.path or "").lower().strip()
        title = str(page_title or "").lower()
        subdomain_depth = max(0, len(host.split(".")) - 2) if "." in host else 0
        suspicious_keywords = [term for term in ("login", "signin", "verify", "secure", "auth", "password", "update") if term in url.lower()]
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
            "has_login_title": any(term in title for term in ("sign in", "login", "verify", "password", "authenticate")),
        }

    def _domain_matches_allowlist(self, policy: dict, domain: str) -> bool:
        return domain in set(policy.get("allowlists", {}).get("domains", []))

    def _domain_matches_blocklist(self, policy: dict, domain: str, url: str) -> tuple[bool, str]:
        if domain in set(policy.get("blocklists", {}).get("domains", [])):
            return True, "blocklisted_domain"
        low_url = str(url or "").lower()
        for pattern in policy.get("blocklists", {}).get("url_patterns", []):
            if pattern and pattern in low_url:
                return True, "blocklisted_url_pattern"
        return False, ""

    def publish_policy(self, tenant_id: int, policy_id: int, actor: str) -> dict:
        policy = db.get_phishing_policy(policy_id, tenant_id=tenant_id)
        if not policy:
            raise ValueError("Policy not found")
        db.update_phishing_policy(
            policy_id,
            {
                "status": "published",
                "version": int(policy.get("version", 0) or 0) + 1,
                "published_at": utcnow(),
                "published_by": actor,
            },
            tenant_id=tenant_id,
        )
        return self.get_effective_policy(tenant_id)

    def evaluate_event(self, tenant_id: int, event: dict, effective_policy: dict | None = None) -> dict:
        policy = effective_policy or self.get_effective_policy(tenant_id)
        domain = str(event.get("domain") or urlparse(event.get("url") or "").netloc or "").lower().strip()
        title = str(event.get("page_title") or "").lower()
        url = str(event.get("url") or "").lower()
        app_name = str(event.get("app_name") or "").lower()
        actor = str(event.get("actor_username") or "").lower()
        local_features = dict(event.get("local_features") or {})
        extracted = self.extract_url_features(url, title)
        merged_features = {**extracted, **local_features}
        reason_codes = []
        score = 0

        if self._domain_matches_allowlist(policy, domain):
            return {
                "matched": False,
                "policy_version": policy["policy_version"],
                "policy_hash": policy["policy_hash"],
                "rule_id": "allowlist",
                "risk_score": 0,
                "confidence": 0,
                "severity": "low",
                "action_taken": "monitor",
                "action_result": "allowlisted",
                "reason_codes": ["allowlisted_domain"],
                "warning_shown": False,
                "unsupported_reason": "",
                "evidence": [],
                "features": merged_features,
                "verdict": "clean",
                "reason": "allowlisted_domain",
            }

        blocklisted, block_reason = self._domain_matches_blocklist(policy, domain, url)
        if blocklisted:
            score += LOCAL_BLOCK_REASONS.get(block_reason, 90)
            reason_codes.append(block_reason)

        if domain in DEFAULT_THREAT_DOMAINS:
            score += 85
            reason_codes.append("known_malicious_domain")

        tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
        if tld and tld in set(policy.get("suspicious_tlds", [])):
            score += 20
            reason_codes.append("suspicious_tld")

        brand_watchlist = policy.get("brand_watchlist", [])
        for brand in brand_watchlist:
            if brand in domain and not re.search(rf"(^|\.){re.escape(brand)}(\.|$)", domain):
                score += 35
                reason_codes.append("lookalike_brand_domain")
                break

        if merged_features.get("has_ip_host"):
            score += 25
            reason_codes.append("ip_literal_host")
        if merged_features.get("has_punycode"):
            score += 20
            reason_codes.append("punycode_host")
        if int(merged_features.get("subdomain_depth", 0) or 0) >= 3:
            score += 10
            reason_codes.append("high_subdomain_depth")
        if float(merged_features.get("entropy", 0.0) or 0.0) >= 3.6:
            score += 10
            reason_codes.append("high_host_entropy")
        if len(merged_features.get("suspicious_keywords", []) or []) >= 2:
            score += 10
            reason_codes.append("multiple_suspicious_keywords")
        if not merged_features.get("uses_https", True):
            score += 10
            reason_codes.append("no_https")

        if any(term in title for term in ("sign in", "login", "verify", "password", "authenticate")):
            score += 15
            reason_codes.append("credential_harvest_title")
        if any(term in url for term in ("signin", "login", "verify", "auth", "password")):
            score += 10
            reason_codes.append("credential_harvest_url")
        if "suspicious_tld" in reason_codes and (
            "credential_harvest_title" in reason_codes or "credential_harvest_url" in reason_codes
        ):
            score += 15
            reason_codes.append("suspicious_login_combination")

        if app_name and app_name not in {"chrome", "msedge", "edge", "firefox", "safari", "browser"}:
            score += 5
            reason_codes.append("non_browser_open_surface")
        if actor and actor in set(policy.get("allowlists", {}).get("users", [])):
            score = max(0, score - 20)
        initial_agent_verdict = str(event.get("initial_agent_verdict") or "").lower()
        if initial_agent_verdict == "malicious":
            score += 20
            reason_codes.append("agent_malicious_verdict")
        elif initial_agent_verdict == "suspicious":
            score += 10
            reason_codes.append("agent_suspicious_verdict")

        thresholds = policy.get("severity_thresholds", DEFAULT_POLICY["severity_thresholds"])
        severity = "low"
        if score >= thresholds.get("critical", 90):
            severity = "critical"
        elif score >= thresholds.get("high", 75):
            severity = "high"
        elif score >= thresholds.get("medium", 55):
            severity = "medium"

        confidence = round(min(0.99, max(0.1, score / 100.0)), 2) if score else 0.0
        matched = score >= thresholds.get("medium", 55)
        action_taken = "monitor"
        action_result = "observed"
        warning_shown = False
        if matched and policy.get("rollout_mode") == "warn_only":
            action_taken = "warn_user"
            action_result = "warning_requested"
            warning_shown = True
        elif matched and policy.get("rollout_mode") in {"soft_block", "hard_block"}:
            action_taken = "block"
            action_result = "block_requested"
        evidence = []
        if matched:
            evidence.append(
                {
                    "domain": domain,
                    "title": event.get("page_title", "")[:180],
                    "app_name": event.get("app_name", ""),
                    "reason_codes": reason_codes,
                    "features": merged_features,
                }
            )
        verdict = "clean"
        if severity in {"critical", "high"}:
            verdict = "malicious"
        elif severity == "medium":
            verdict = "suspicious"
        return {
            "matched": matched,
            "policy_version": policy["policy_version"],
            "policy_hash": policy["policy_hash"],
            "rule_id": "phishing_heuristics_v1",
            "risk_score": score,
            "confidence": confidence,
            "severity": severity,
            "action_taken": action_taken,
            "action_result": action_result,
            "reason_codes": reason_codes,
            "warning_shown": warning_shown,
            "unsupported_reason": "" if event.get("channel") in set(policy.get("protected_channels", [])) else "channel_detect_only",
            "evidence": evidence,
            "features": merged_features,
            "verdict": verdict,
            "reason": ", ".join(reason_codes[:4]) if reason_codes else "no_match",
        }

    def ingest_event(self, tenant_id: int, data: dict) -> dict:
        self.ensure_seeded(tenant_id)
        event = dict(data)
        event.setdefault("event_type", "browser_visit")
        event.setdefault("channel", "browser")
        policy = self.get_effective_policy(tenant_id)
        evaluation = self.evaluate_event(tenant_id, event, policy)
        event.update(
            {
                "policy_version": evaluation["policy_version"],
                "policy_hash": evaluation["policy_hash"],
                "rule_id": evaluation["rule_id"],
                "risk_score": evaluation["risk_score"],
                "confidence": evaluation["confidence"],
                "severity": evaluation["severity"],
                "action_taken": evaluation["action_taken"],
                "action_result": evaluation["action_result"],
                "reason_codes": evaluation["reason_codes"],
                "evidence": evaluation["evidence"],
                "unsupported_reason": evaluation["unsupported_reason"],
            }
        )
        event_id = db.insert_phishing_event(event, tenant_id=tenant_id)
        incident = None
        if evaluation["matched"]:
            incident = self._upsert_incident(tenant_id, event, evaluation)
            if incident:
                db.update_phishing_event_incident(event_id, incident["id"], tenant_id=tenant_id)
        logger.info(
            "phishing_decision tenant_id=%s machine_id_prefix=%s domain=%s severity=%s matched=%s action_taken=%s action_result=%s warning_shown=%s reason_codes=%s unsupported_reason=%s",
            tenant_id,
            self._machine_prefix(event.get("machine_id", "")),
            event.get("domain", ""),
            evaluation["severity"],
            evaluation["matched"],
            evaluation["action_taken"],
            evaluation["action_result"],
            evaluation["warning_shown"],
            ",".join(evaluation.get("reason_codes", [])),
            evaluation.get("unsupported_reason", ""),
        )
        set_sentry_tags(
            {
                "phishing_policy_version": evaluation["policy_version"],
                "phishing_channel": event.get("channel", "browser"),
                "phishing_action_taken": evaluation["action_taken"],
                "phishing_action_result": evaluation["action_result"],
            }
        )
        return {"event_id": event_id, "incident": incident, "event": event, "evaluation": evaluation}

    def check_url(self, tenant_id: int, payload: dict) -> dict:
        self.ensure_seeded(tenant_id)
        event = {
            "machine_id": payload.get("machine_id", ""),
            "actor_username": payload.get("user_id", ""),
            "url": payload.get("url", ""),
            "domain": str(urlparse(payload.get("url", "")).netloc or "").lower().strip(),
            "page_title": payload.get("page_title", ""),
            "app_name": payload.get("app_name", ""),
            "process_name": payload.get("process_name", ""),
            "channel": payload.get("channel", "browser"),
            "event_type": "url_check",
            "initial_agent_verdict": payload.get("initial_agent_verdict", "clean"),
            "local_features": payload.get("local_features", {}) or {},
            "timestamp": utcnow(),
        }
        evaluation = self.evaluate_event(tenant_id, event)
        final_action = evaluation["action_taken"]
        if evaluation["verdict"] == "clean":
            final_action = "allow"
        return {
            "verdict": evaluation["verdict"],
            "action": final_action,
            "reason": evaluation["reason"],
            "severity": evaluation["severity"],
            "risk_score": evaluation["risk_score"],
            "confidence": evaluation["confidence"],
            "reason_codes": evaluation["reason_codes"],
            "features": evaluation["features"],
            "policy_version": evaluation["policy_version"],
            "policy_hash": evaluation["policy_hash"],
        }

    def report_feedback(self, tenant_id: int, payload: dict) -> dict:
        incident_id = payload.get("incident_id")
        note = (payload.get("note") or "").strip()
        feedback = (payload.get("feedback") or "").strip()
        verdict = (payload.get("verdict") or "").strip()
        stored = False
        if incident_id:
            incident = db.get_phishing_incident(int(incident_id), tenant_id=tenant_id)
            if incident:
                message = " | ".join(part for part in [feedback, verdict, note] if part)
                if message:
                    db.add_phishing_incident_note(int(incident_id), message, payload.get("machine_id", "agent"), tenant_id=tenant_id)
                db.add_phishing_incident_timeline(
                    int(incident_id),
                    "agent_feedback",
                    payload.get("machine_id", "agent"),
                    {"feedback": feedback, "verdict": verdict, "url": payload.get("url", ""), "domain": payload.get("domain", "")},
                    tenant_id=tenant_id,
                )
                stored = True
        return {"status": "ok", "stored": stored}

    def create_blocklist_exception(self, tenant_id: int, payload: dict) -> int:
        return db.create_phishing_blocklist_exception(payload, tenant_id=tenant_id)

    def _upsert_incident(self, tenant_id: int, event: dict, evaluation: dict) -> dict:
        incident = db.find_recent_matching_phishing_incident(
            tenant_id=tenant_id,
            domain=event.get("domain", ""),
            machine_id=event.get("machine_id", ""),
            actor_username=event.get("actor_username", ""),
            channel=event.get("channel", "browser"),
        )
        title = f"Phishing {evaluation['severity'].upper()} - {event.get('domain') or 'unknown domain'}"
        summary = f"{event.get('page_title') or event.get('url') or event.get('domain')} on {event.get('app_name') or event.get('channel')}"
        metadata = {
            "reason_codes": evaluation["reason_codes"],
            "action_taken": evaluation["action_taken"],
            "action_result": evaluation["action_result"],
            "policy_version": evaluation["policy_version"],
            "evidence": evaluation["evidence"],
        }
        if incident:
            db.update_phishing_incident(
                incident["id"],
                {
                    "last_seen": event.get("timestamp") or utcnow(),
                    "event_count": int(incident.get("event_count", 1) or 1) + 1,
                    "severity": self._max_severity(incident.get("severity", "medium"), evaluation["severity"]),
                    "confidence": max(float(incident.get("confidence", 0) or 0), float(evaluation["confidence"] or 0)),
                    "summary": summary,
                    "warning_shown": bool(incident.get("warning_shown", False) or evaluation["warning_shown"]),
                    "metadata": {**_json_loads(incident.get("metadata"), {}), **metadata},
                },
                tenant_id=tenant_id,
            )
            db.add_phishing_incident_timeline(incident["id"], "event_grouped", "system", metadata, tenant_id=tenant_id)
            updated = db.get_phishing_incident(incident["id"], tenant_id=tenant_id) or incident
            updated["_new_alert"] = False
            return updated

        incident_id = db.create_phishing_incident(
            {
                "state": "open",
                "severity": evaluation["severity"],
                "confidence": evaluation["confidence"],
                "title": title,
                "summary": summary,
                "machine_id": event.get("machine_id", ""),
                "actor_username": event.get("actor_username", ""),
                "app_name": event.get("app_name", ""),
                "process_name": event.get("process_name", ""),
                "channel": event.get("channel", "browser"),
                "domain": event.get("domain", ""),
                "url": event.get("url", ""),
                "destination_label": event.get("destination_label", ""),
                "rule_id": evaluation["rule_id"],
                "warning_shown": evaluation["warning_shown"],
                "first_seen": event.get("timestamp") or utcnow(),
                "last_seen": event.get("timestamp") or utcnow(),
                "metadata": metadata,
            },
            tenant_id=tenant_id,
        )
        db.add_phishing_incident_timeline(incident_id, "incident_created", "system", metadata, tenant_id=tenant_id)
        created = db.get_phishing_incident(incident_id, tenant_id=tenant_id) or {"id": incident_id}
        created["_new_alert"] = True
        return created

    def _max_severity(self, current: str, incoming: str) -> str:
        return incoming if SEVERITY_RANK.get(incoming, 0) >= SEVERITY_RANK.get(current, 0) else current

    def list_incidents(self, tenant_id: int, state: str = "", severity: str = "", assignee: str = "", limit: int = 50, offset: int = 0) -> dict:
        items = []
        for row in db.list_phishing_incidents(tenant_id=tenant_id, state=state, severity=severity, assignee=assignee, limit=limit, offset=offset):
            item = dict(row)
            item["metadata"] = _json_loads(item.get("metadata"), {})
            items.append(item)
        return {"items": items, "total": db.count_phishing_incidents(tenant_id=tenant_id, state=state, severity=severity, assignee=assignee)}

    def incident_stats(self, tenant_id: int) -> dict:
        items = db.list_phishing_incidents(tenant_id=tenant_id, limit=200, offset=0)
        by_state = {}
        by_channel = {}
        warned = 0
        domains = {}
        for item in items:
            by_state[item.get("state", "open")] = by_state.get(item.get("state", "open"), 0) + 1
            by_channel[item.get("channel", "browser")] = by_channel.get(item.get("channel", "browser"), 0) + 1
            if item.get("warning_shown"):
                warned += 1
            domain = item.get("domain", "")
            if domain:
                domains[domain] = domains.get(domain, 0) + 1
        top_domains = sorted(domains.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {"total": len(items), "by_state": by_state, "by_channel": by_channel, "warned_users": warned, "top_domains": [{"domain": d, "count": c} for d, c in top_domains]}

    def get_incident_detail(self, tenant_id: int, incident_id: int) -> dict | None:
        item = db.get_phishing_incident(incident_id, tenant_id=tenant_id)
        if not item:
            return None
        item["metadata"] = _json_loads(item.get("metadata"), {})
        item["notes"] = db.list_phishing_incident_notes(incident_id, tenant_id=tenant_id)
        item["timeline"] = db.list_phishing_incident_timeline(incident_id, tenant_id=tenant_id)
        return item

    def get_machine_diagnostics(self, tenant_id: int, machine_id: str) -> dict:
        latest = db.get_latest_phishing_event_for_machine(machine_id, tenant_id=tenant_id)
        policy = self.get_effective_policy(tenant_id)
        return {
            "machine_id": machine_id,
            "effective_policy_version": policy["policy_version"],
            "effective_policy_hash": policy["policy_hash"],
            "effective_rollout_mode": policy["rollout_mode"],
            "protected_channels": policy["protected_channels"],
            "latest_event": latest,
            "unsupported_capabilities": ["desktop_link_open", "email_client_open"],
        }

    def create_allowlist_exception(self, tenant_id: int, payload: dict) -> int:
        return db.create_phishing_allowlist_exception(payload, tenant_id=tenant_id)

    def platform_baseline(self) -> dict:
        self.ensure_seeded(1)
        policies = [_normalize_policy(p) for p in db.list_phishing_policies(1, scope="platform_baseline")]
        return {"policies": policies}


phishing_service = PhishingService()
