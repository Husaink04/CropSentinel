"""Enterprise DLP policy, simulation, and incident orchestration."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.db.core import get_tenant_id as current_tenant_id
from app.monitoring import set_sentry_tags
from app.repos.settings_repo import settings_repo
from database import clear_tenant_context, db, set_tenant_context, utcnow

logger = logging.getLogger("croppro.dlp.enterprise")

DEFAULT_BUILTIN_CLASSIFIERS = [
    {"name": "pii_email", "category": "pii", "classifier_type": "builtin", "severity": "low", "config": {"builtin_name": "email"}},
    {"name": "pii_phone", "category": "pii", "classifier_type": "builtin", "severity": "low", "config": {"builtin_name": "phone"}},
    {"name": "pii_ssn", "category": "pii", "classifier_type": "builtin", "severity": "high", "config": {"builtin_name": "ssn"}},
    {"name": "finance_credit_card", "category": "finance", "classifier_type": "builtin", "severity": "high", "config": {"builtin_name": "credit_card"}},
    {"name": "credentials_api_key", "category": "credentials", "classifier_type": "builtin", "severity": "critical", "config": {"builtin_name": "api_key"}},
    {"name": "credentials_private_key", "category": "credentials", "classifier_type": "builtin", "severity": "critical", "config": {"builtin_name": "private_key"}},
    {"name": "credentials_password", "category": "credentials", "classifier_type": "builtin", "severity": "high", "config": {"builtin_name": "password_in_text"}},
    {"name": "credentials_connection_string", "category": "credentials", "classifier_type": "builtin", "severity": "high", "config": {"builtin_name": "connection_string"}},
]

DEFAULT_BASELINE_RULES = [
    {
        "name": "Block sensitive data to USB",
        "description": "High-confidence block for sensitive data copied to removable media.",
        "channels": ["file", "usb"],
        "destination_scope": ["usb"],
        "severity": "high",
        "confidence": 0.9,
        "action": "block_transfer",
        "mandatory": True,
        "classifier_names": ["pii_ssn", "finance_credit_card", "credentials_api_key", "credentials_private_key", "credentials_connection_string"],
    },
    {
        "name": "Warn on risky uploads",
        "description": "Warn and log when sensitive data is uploaded to cloud or web destinations.",
        "channels": ["file", "upload", "cloud_sync"],
        "destination_scope": ["upload", "cloud_sync"],
        "severity": "medium",
        "confidence": 0.8,
        "action": "warn_user",
        "mandatory": True,
        "classifier_names": ["pii_email", "pii_phone", "pii_ssn", "finance_credit_card", "credentials_api_key", "credentials_private_key"],
    },
    {
        "name": "Monitor local sensitive activity",
        "description": "Monitor-only local access to sensitive content for triage.",
        "channels": ["file", "print", "clipboard"],
        "destination_scope": ["any"],
        "severity": "medium",
        "confidence": 0.7,
        "action": "monitor",
        "mandatory": True,
        "classifier_names": ["pii_email", "pii_phone", "pii_ssn", "finance_credit_card", "credentials_password"],
    },
]

SEVERITY_RANK = {"low": 1, "medium": 2, "warning": 2, "high": 3, "critical": 4}
ROLLOUT_RANK = {"off": 0, "audit_only": 1, "monitor_only": 2, "soft_block": 3, "hard_block": 4}
DEFAULT_HISTORY_WINDOW_DAYS = 90
INCIDENT_STATE_MAP = {
    "open": "new",
    "in_review": "investigating",
    "resolved": "closed",
}
INCIDENT_DISPOSITIONS = {
    "contained": "contained",
    "approved_business_use": "approved_business_use",
    "false_positive": "false_positive",
    "escalated": "escalated",
    "closed": "closed",
}
USER_RISK_LEVELS = [
    {"min": 30, "label": "critical", "tone": "danger"},
    {"min": 18, "label": "high", "tone": "warning"},
    {"min": 8, "label": "watch", "tone": "info"},
    {"min": 0, "label": "low", "tone": "success"},
]
USER_RISK_LEVEL_RANK = {"low": 0, "watch": 1, "high": 2, "critical": 3}
HIGH_RISK_LEVELS = {"high", "critical"}
WARNING_RESULTS = {"warning_shown", "warned"}


def _json_loads(value: Any, default: Any):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


@lru_cache(maxsize=1)
def _load_agent_dlp_engine():
    module_path = Path(__file__).resolve().parents[3] / "agent" / "dlp_engine.py"
    spec = importlib.util.spec_from_file_location("croppro_agent_dlp_engine", module_path)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _policy_checksum(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _normalize_classifier(row: dict) -> dict:
    item = dict(row)
    item["config"] = _json_loads(item.get("config"), {})
    return item


def _normalize_rule(row: dict) -> dict:
    item = dict(row)
    item["classifier_ids"] = _json_loads(item.get("classifier_ids"), [])
    item["channels"] = _json_loads(item.get("channels"), ["file"])
    item["destination_scope"] = _json_loads(item.get("destination_scope"), ["any"])
    item["config"] = _json_loads(item.get("config"), {})
    return item


def _normalize_policy(row: dict) -> dict:
    item = dict(row)
    item["config"] = _json_loads(item.get("config"), {})
    return item


class DlpService:
    @staticmethod
    def _machine_prefix(machine_id: str) -> str:
        machine_id = str(machine_id or "")
        return machine_id[:8] if machine_id else ""

    @contextmanager
    def _tenant_scope(self, tenant_id: int):
        previous_tenant_id = current_tenant_id()
        set_tenant_context(int(tenant_id))
        try:
            yield
        finally:
            set_tenant_context(int(previous_tenant_id or 1))

    def ensure_seeded(self, tenant_id: int) -> None:
        with self._tenant_scope(1):
            self._ensure_platform_baseline()
        if tenant_id != 1:
            with self._tenant_scope(tenant_id):
                self._ensure_tenant_generated_policy(tenant_id)

    def _ensure_platform_baseline(self) -> None:
        baseline = next((p for p in db.list_dlp_policies(1, scope="platform_baseline")), None)
        if not baseline:
            baseline_id = db.create_dlp_policy(
                {
                    "scope": "platform_baseline",
                    "name": "Platform Baseline Policy",
                    "description": "Mandatory baseline DLP controls for all tenants.",
                    "mode": "detect_then_block",
                    "status": "published",
                    "priority": 1000,
                    "version": 1,
                    "rollout_mode": "monitor_only",
                    "is_baseline": True,
                    "is_mandatory": True,
                    "config": {"source": "system_seed"},
                    "published_at": utcnow(),
                    "published_by": "system",
                },
                tenant_id=1,
            )
            baseline = db.get_dlp_policy(baseline_id, tenant_id=1) or next(
                (p for p in db.list_dlp_policies(1, scope="platform_baseline")),
                None,
            )
        if not baseline:
            raise RuntimeError("Failed to seed platform baseline DLP policy")
        baseline_id = int(baseline["id"])
        classifier_ids = []
        for classifier in DEFAULT_BUILTIN_CLASSIFIERS:
            existing = db.get_dlp_classifier_by_name(classifier["name"], tenant_id=1)
            cid = existing["id"] if existing else db.create_dlp_classifier(
                {
                    **classifier,
                    "scope": "platform_baseline",
                    "builtin": True,
                    "enabled": True,
                },
                tenant_id=1,
            )
            classifier_ids.append((classifier["name"], cid))
        classifier_map = dict(classifier_ids)
        existing_rules = {row.get("name") for row in db.list_dlp_rules(baseline_id, tenant_id=1)}
        for rule in DEFAULT_BASELINE_RULES:
            if rule["name"] in existing_rules:
                continue
            db.create_dlp_rule(
                {
                    "policy_id": baseline_id,
                    "name": rule["name"],
                    "description": rule["description"],
                    "classifier_ids": [classifier_map[name] for name in rule["classifier_names"] if name in classifier_map],
                    "channels": rule["channels"],
                    "destination_scope": rule["destination_scope"],
                    "severity": rule["severity"],
                    "confidence": rule["confidence"],
                    "action": rule["action"],
                    "mandatory": rule["mandatory"],
                    "enabled": True,
                    "config": {"source": "system_seed"},
                },
                tenant_id=1,
            )

    def _ensure_tenant_generated_policy(self, tenant_id: int) -> None:
        if tenant_id == 1:
            return
        existing = next((p for p in db.list_dlp_policies(tenant_id, scope="tenant_override")), None)
        if existing:
            return
        settings = settings_repo.get()
        policy_id = db.create_dlp_policy(
            {
                "scope": "tenant_override",
                "name": "Generated Tenant Override",
                "description": "Generated from legacy DLP settings migration.",
                "mode": "detect_then_block",
                "status": "published",
                "priority": 100,
                "version": 1,
                "rollout_mode": "monitor_only",
                "config": {"source": "legacy_settings"},
                "published_at": utcnow(),
                "published_by": "system",
            },
            tenant_id=tenant_id,
        )
        classifier_ids = []
        for keyword in settings.get("dlp_keywords", []) or []:
            name = f"keyword_{str(keyword).strip().lower()}"
            existing_classifier = db.get_dlp_classifier_by_name(name, tenant_id=tenant_id)
            classifier_id = existing_classifier["id"] if existing_classifier else db.create_dlp_classifier(
                {
                    "name": name,
                    "scope": "tenant",
                    "category": "custom",
                    "classifier_type": "keyword",
                    "builtin": False,
                    "enabled": True,
                    "severity": "medium",
                    "config": {"keyword": keyword},
                },
                tenant_id=tenant_id,
            )
            classifier_ids.append(classifier_id)
        for name, pattern in (settings.get("dlp_custom_patterns", {}) or {}).items():
            classifier_name = f"custom_{name}"
            existing_classifier = db.get_dlp_classifier_by_name(classifier_name, tenant_id=tenant_id)
            classifier_id = existing_classifier["id"] if existing_classifier else db.create_dlp_classifier(
                {
                    "name": classifier_name,
                    "scope": "tenant",
                    "category": "custom",
                    "classifier_type": "regex",
                    "builtin": False,
                    "enabled": True,
                    "severity": "medium",
                    "config": {"pattern": pattern},
                },
                tenant_id=tenant_id,
            )
            classifier_ids.append(classifier_id)
        if classifier_ids:
            db.create_dlp_rule(
                {
                    "policy_id": policy_id,
                    "name": "Legacy custom DLP detectors",
                    "description": "Tenant-level generated rule based on previous keyword/regex settings.",
                    "classifier_ids": classifier_ids,
                    "channels": ["file", "upload", "cloud_sync", "usb"],
                    "destination_scope": ["any"],
                    "severity": "medium",
                    "confidence": 0.75,
                    "action": "monitor",
                    "mandatory": False,
                    "enabled": True,
                    "config": {"source": "legacy_settings"},
                },
                tenant_id=tenant_id,
            )

    def get_effective_policy(self, tenant_id: int) -> dict:
        self.ensure_seeded(tenant_id)
        with self._tenant_scope(tenant_id):
            baseline = [_normalize_policy(p) for p in db.list_dlp_policies(1, scope="platform_baseline") if p.get("status") == "published"]
            tenant_policies = [_normalize_policy(p) for p in db.list_dlp_policies(tenant_id, scope="tenant_override") if p.get("status") == "published"]
            all_policies = baseline + tenant_policies
            rules = []
            classifiers = {}
            for policy in all_policies:
                policy_rules = [_normalize_rule(r) for r in db.list_dlp_rules(policy["id"], tenant_id=policy["tenant_id"])]
                policy["rules"] = policy_rules
                rules.extend(policy_rules)
            for row in db.list_dlp_classifiers(1):
                classifiers[row["id"]] = _normalize_classifier(row)
            for row in db.list_dlp_classifiers(tenant_id):
                classifiers[row["id"]] = _normalize_classifier(row)
            exceptions = [self._normalize_exception(e) for e in db.list_dlp_exceptions(tenant_id, status="active")]
            settings = settings_repo.get()
            keywords = list(settings.get("dlp_keywords", []) or [])
            patterns = dict(settings.get("dlp_custom_patterns", {}) or {})
            for classifier in classifiers.values():
                if not classifier.get("enabled", True):
                    continue
                cfg = classifier.get("config") or {}
                if classifier.get("classifier_type") == "keyword" and cfg.get("keyword"):
                    keywords.append(cfg["keyword"])
                if classifier.get("classifier_type") == "regex" and cfg.get("pattern"):
                    patterns.setdefault(classifier["name"], cfg["pattern"])
            deduped_keywords = []
            seen_keywords = set()
            for keyword in keywords:
                normalized = str(keyword).strip()
                if not normalized or normalized in seen_keywords:
                    continue
                seen_keywords.add(normalized)
                deduped_keywords.append(normalized)
            payload = {
                "tenant_id": tenant_id,
                "mode": "detect_then_block",
                "rollout_mode": max(
                    (p.get("rollout_mode", "monitor_only") for p in all_policies),
                    key=lambda item: ROLLOUT_RANK.get(item, 2),
                    default="monitor_only",
                ),
                "policies": all_policies,
                "rules": rules,
                "classifiers": list(classifiers.values()),
                "exceptions": exceptions,
                "keywords": deduped_keywords,
                "custom_patterns": patterns,
                "risk_thresholds": settings.get("dlp_risk_thresholds", {"low": 1, "medium": 3, "high": 7}),
            }
            payload["policy_version"] = max((int(p.get("version", 1) or 1) for p in all_policies), default=1)
            payload["policy_hash"] = _policy_checksum(payload)
            payload["ruleset_checksum"] = _policy_checksum({"rules": rules, "classifiers": list(classifiers.values())})
            payload["dlp_enabled"] = settings.get("dlp_enabled", True) is not False
            return payload

    def list_policies_with_rules(self, tenant_id: int) -> list[dict]:
        self.ensure_seeded(tenant_id)
        policies = [_normalize_policy(p) for p in db.list_dlp_policies(tenant_id)]
        for policy in policies:
            policy["rules"] = [_normalize_rule(r) for r in db.list_dlp_rules(policy["id"], tenant_id=tenant_id)]
        return policies

    def list_platform_baseline(self) -> dict:
        self.ensure_seeded(1)
        policies = [_normalize_policy(p) for p in db.list_dlp_policies(1, scope="platform_baseline")]
        for policy in policies:
            policy["rules"] = [_normalize_rule(r) for r in db.list_dlp_rules(policy["id"], tenant_id=1)]
        classifiers = [_normalize_classifier(c) for c in db.list_dlp_classifiers(1)]
        return {"policies": policies, "classifiers": classifiers}

    def publish_policy(self, tenant_id: int, policy_id: int, actor: str) -> dict:
        policy = db.get_dlp_policy(policy_id, tenant_id=tenant_id)
        if not policy:
            raise ValueError("Policy not found")
        next_version = int(policy.get("version", 0) or 0) + 1
        db.update_dlp_policy(
            policy_id,
            {
                "status": "published",
                "version": next_version,
                "published_at": utcnow(),
                "published_by": actor,
            },
            tenant_id=tenant_id,
        )
        return self.get_effective_policy(tenant_id)

    def simulate_policy(self, tenant_id: int, sample: dict) -> dict:
        effective = self.get_effective_policy(tenant_id)
        content = sample.get("content", "") or ""
        file_path = sample.get("file_path", "") or ""
        destination = sample.get("destination_type", "local") or "local"
        channel = sample.get("channel", "file") or "file"
        findings = []
        try:
            module = _load_agent_dlp_engine()
            if module:
                engine = module.DLPEngine(
                    enabled=True,
                    custom_keywords=effective.get("keywords", []),
                    custom_patterns=effective.get("custom_patterns", {}),
                    risk_thresholds=effective.get("risk_thresholds", {}),
                )
                scan = engine.scan(content)
                findings = scan.get("findings", [])
        except Exception as exc:
            logger.debug("Policy simulation fallback engaged: %s", exc)
        if not findings:
            findings = self._fallback_findings(effective, content)
        evaluation = self.evaluate_event_against_policy(
            tenant_id,
            {
                "channel": channel,
                "destination_type": destination,
                "findings": findings,
                "file_path": file_path,
                "file_name": sample.get("file_name") or Path(file_path).name,
                "machine_id": sample.get("machine_id", ""),
                "actor_username": sample.get("actor_username", ""),
            },
            effective_policy=effective,
        )
        return {
            "effective_policy_version": effective["policy_version"],
            "findings": findings,
            "evaluation": evaluation,
        }

    def _fallback_findings(self, effective: dict, content: str) -> list[dict]:
        findings = []
        low = content.lower()
        for keyword in effective.get("keywords", []):
            count = low.count(str(keyword).lower())
            if count:
                findings.append({"type": f"keyword:{str(keyword).lower()}", "count": count})
        for name, pattern in (effective.get("custom_patterns", {}) or {}).items():
            try:
                count = len(re.findall(pattern, content))
            except re.error:
                count = 0
            if count:
                findings.append({"type": name, "count": count})
        return findings

    def evaluate_event_against_policy(self, tenant_id: int, event: dict, effective_policy: dict | None = None) -> dict:
        effective = effective_policy or self.get_effective_policy(tenant_id)
        findings = event.get("findings", []) or []
        hit_names = {f.get("type", "") for f in findings}
        classifier_hits = []
        classifier_map = {c["id"]: c for c in effective.get("classifiers", [])}
        matched_rule = None
        for rule in sorted(effective.get("rules", []), key=lambda r: (SEVERITY_RANK.get(r.get("severity", "low"), 0), float(r.get("confidence", 0))), reverse=True):
            channels = set(rule.get("channels", ["file"]))
            if "any" not in channels and event.get("channel", "file") not in channels:
                continue
            destinations = set(rule.get("destination_scope", ["any"]))
            if "any" not in destinations and event.get("destination_type", "local") not in destinations:
                continue
            local_hits = []
            for classifier_id in rule.get("classifier_ids", []):
                classifier = classifier_map.get(classifier_id)
                if not classifier:
                    continue
                cname = classifier["name"]
                builtin_name = (classifier.get("config") or {}).get("builtin_name")
                if cname in hit_names or builtin_name in hit_names or any(h.startswith(cname) for h in hit_names):
                    local_hits.append(
                        {
                            "classifier_id": classifier_id,
                            "name": cname,
                            "category": classifier.get("category", "custom"),
                            "severity": classifier.get("severity", "medium"),
                        }
                    )
            if local_hits:
                classifier_hits = local_hits
                matched_rule = rule
                break
        if not matched_rule and findings:
            matched_rule = {
                "id": None,
                "name": "Default observation",
                "severity": event.get("risk_level", "medium"),
                "confidence": 0.5,
                "action": "monitor",
            }
        action = matched_rule.get("action", "monitor") if matched_rule else "monitor"
        action_result = "observed"
        unsupported_reason = ""
        reported_action = str(event.get("action_taken", "") or "")
        reported_result = str(event.get("action_result", "") or "")
        agent_executed = reported_result in {"blocked", "warning_shown", "block_failed"}
        if action in {"block_transfer", "quarantine", "manager_approval", "require_justification"}:
            if reported_action == action and agent_executed:
                action_result = reported_result
            else:
                action_result = "unsupported"
                unsupported_reason = "endpoint_enforcement_not_available_in_current_agent_channel"
        elif reported_action == "warn_user" and reported_result in WARNING_RESULTS:
            action = "warn_user"
            action_result = reported_result
        exception = self.match_exception(tenant_id, event, classifier_hits)
        if exception:
            action = "monitor"
            action_result = "exception_applied"
        masked_evidence = self.build_masked_evidence(event, classifier_hits)
        return {
            "policy_version": effective["policy_version"],
            "policy_hash": effective["policy_hash"],
            "ruleset_checksum": effective["ruleset_checksum"],
            "policy_rule_id": matched_rule.get("id") if matched_rule else None,
            "policy_rule_name": matched_rule.get("name") if matched_rule else "",
            "confidence": float(matched_rule.get("confidence", 0.5) if matched_rule else 0.5),
            "severity": matched_rule.get("severity", event.get("risk_level", "medium")) if matched_rule else event.get("risk_level", "medium"),
            "action_taken": action,
            "action_result": action_result,
            "unsupported_reason": unsupported_reason,
            "justification_required": action == "require_justification",
            "exception_applied": exception,
            "classifier_hits": classifier_hits,
            "masked_evidence": masked_evidence,
        }

    def build_masked_evidence(self, event: dict, classifier_hits: list[dict]) -> list[dict]:
        findings = event.get("findings", []) or []
        evidence = []
        for finding in findings[:8]:
            evidence.append(
                {
                    "type": finding.get("type", "unknown"),
                    "count": int(finding.get("count", 1) or 1),
                    "preview": "<masked>",
                    "reason": f"Matched classifier {finding.get('type', 'unknown')}",
                }
            )
        if not evidence:
            for hit in classifier_hits[:8]:
                evidence.append(
                    {
                        "type": hit.get("name", "unknown"),
                        "count": 1,
                        "preview": "<masked>",
                        "reason": f"Policy hit {hit.get('name', 'unknown')}",
                    }
                )
        return evidence

    def match_exception(self, tenant_id: int, event: dict, classifier_hits: list[dict]) -> dict | None:
        exceptions = [self._normalize_exception(e) for e in db.list_dlp_exceptions(tenant_id, status="active")]
        path = event.get("file_path", "") or ""
        actor = event.get("actor_username", "") or ""
        destination = event.get("destination_type", "") or ""
        app_name = event.get("app_name", "") or ""
        hit_names = {hit.get("name", "") for hit in classifier_hits}
        for exc in exceptions:
            expires_at = exc.get("expires_at")
            if expires_at and expires_at < utcnow():
                continue
            if exc.get("scope_type") == "machine" and exc.get("scope_value") and exc["scope_value"] != event.get("machine_id", ""):
                continue
            if exc.get("scope_type") == "user" and exc.get("scope_value") and exc["scope_value"] != actor:
                continue
            if exc.get("scope_type") == "path" and exc.get("path_pattern") and exc["path_pattern"] not in path:
                continue
            if exc.get("classifier_name") and exc["classifier_name"] not in hit_names:
                continue
            if exc.get("destination_type") and exc["destination_type"] != destination:
                continue
            if exc.get("app_name") and exc["app_name"] != app_name:
                continue
            return {
                "id": exc["id"],
                "reason": exc.get("reason", ""),
                "scope_type": exc.get("scope_type", ""),
            }
        return None

    def ingest_dlp_event(self, tenant_id: int, data: dict) -> dict:
        with self._tenant_scope(tenant_id):
            self.ensure_seeded(tenant_id)
            event = dict(data)
            event.setdefault("event_type", "file_transfer")
            if not event.get("channel"):
                event["channel"] = event.get("destination") or "file"
            if not event.get("destination_type"):
                event["destination_type"] = event.get("destination") or "local"
            if not event.get("destination_label"):
                event["destination_label"] = event.get("device") or event.get("destination") or ""
            if not event.get("content_fingerprint"):
                event["content_fingerprint"] = event.get("file_hash") or ""
            if not event.get("actor_username"):
                machine = db.get_machine(event.get("machine_id", "")) if event.get("machine_id") else None
                event["actor_username"] = (
                    (machine or {}).get("username")
                    or event.get("username")
                    or ""
                )
            effective = self.get_effective_policy(tenant_id)
            evaluation = self.evaluate_event_against_policy(tenant_id, event, effective_policy=effective)
            event.update(
                {
                    "policy_version": evaluation["policy_version"],
                    "policy_rule_id": evaluation["policy_rule_id"],
                    "classifier_hits": evaluation["classifier_hits"],
                    "confidence": evaluation["confidence"],
                    "action_taken": evaluation["action_taken"],
                    "action_result": evaluation["action_result"],
                    "justification_required": evaluation["justification_required"],
                    "exception_applied": evaluation["exception_applied"] or {},
                    "masked_evidence": evaluation["masked_evidence"],
                    "destination_type": event.get("destination_type", "local"),
                    "destination_label": event.get("destination_label", ""),
                    "content_fingerprint": event.get("content_fingerprint", ""),
                    "risk_level": evaluation["severity"],
                }
            )
            event_id = db.insert_dlp_event(event)
            incident = self._upsert_incident(tenant_id, event, event_id=event_id)
            if incident:
                event["incident_id"] = incident["id"]
                db.update_dlp_event_incident(event_id, incident["id"])
            logger.info(
                "dlp_decision tenant_id=%s machine_id_prefix=%s file_name=%s destination_type=%s severity=%s action_taken=%s action_result=%s matched_rule=%s exception_applied=%s unsupported_reason=%s classifier_hits=%s",
                tenant_id,
                self._machine_prefix(event.get("machine_id", "")),
                event.get("file_name", "") or event.get("file_path", ""),
                event.get("destination_type", ""),
                evaluation["severity"],
                evaluation["action_taken"],
                evaluation["action_result"],
                evaluation.get("policy_rule_name", ""),
                bool(evaluation.get("exception_applied")),
                evaluation.get("unsupported_reason", ""),
                ",".join(hit.get("name", "") for hit in evaluation.get("classifier_hits", [])),
            )
            set_sentry_tags(
                {
                    "dlp_policy_version": evaluation["policy_version"],
                    "dlp_channel": event.get("channel", "file"),
                    "dlp_action_taken": evaluation["action_taken"],
                    "dlp_action_result": evaluation["action_result"],
                }
            )
            return {
                "event_id": event_id,
                "incident": incident,
                "event": event,
                "evaluation": evaluation,
                "new_alert": incident and incident.get("_new_alert", False),
            }

    def _upsert_incident(self, tenant_id: int, event: dict, event_id: int | None = None) -> dict:
        incident = db.find_recent_matching_dlp_incident(
            tenant_id=tenant_id,
            policy_rule_id=event.get("policy_rule_id"),
            file_hash=event.get("file_hash", ""),
            content_fingerprint=event.get("content_fingerprint", ""),
            machine_id=event.get("machine_id", ""),
            actor_username=event.get("actor_username", ""),
            channel=event.get("channel", "file"),
        )
        summary = f"{event.get('file_name') or event.get('file_path') or 'Unknown file'} via {event.get('destination_type', 'local')}"
        title = f"DLP {str(event.get('risk_level', 'medium')).upper()} - {event.get('file_name') or 'Sensitive activity'}"
        metadata = {
            "action_taken": event.get("action_taken", "monitor"),
            "action_result": event.get("action_result", "observed"),
            "masked_evidence": event.get("masked_evidence", []),
            "policy_version": event.get("policy_version"),
            "exception_applied": event.get("exception_applied", {}),
            "file_path": event.get("file_path", ""),
            "file_name": event.get("file_name", ""),
            "machine_id": event.get("machine_id", ""),
            "actor_username": event.get("actor_username", ""),
            "destination_type": event.get("destination_type", ""),
            "destination_label": event.get("destination_label", ""),
            "classifier_hits": event.get("classifier_hits", []),
            "enterprise_label": event.get("enterprise_label", ""),
            "policy_rule_name": event.get("policy_rule_name", ""),
            "last_action_result": event.get("action_result", "observed"),
            "last_channel": event.get("channel", "file"),
            "last_event_id": event_id,
        }
        if incident:
            next_count = int(incident.get("event_count", 1) or 1) + 1
            existing_metadata = _json_loads(incident.get("metadata"), {})
            channels_seen = sorted(set((existing_metadata.get("channels_seen") or []) + [event.get("channel", "file")]))
            destinations_seen = sorted(set((existing_metadata.get("destinations_seen") or []) + [event.get("destination_type", "")]))
            db.update_dlp_incident(
                incident["id"],
                {
                    "last_seen": event.get("timestamp") or utcnow(),
                    "event_count": next_count,
                    "severity": self._max_severity(incident.get("severity", "medium"), event.get("risk_level", "medium")),
                    "summary": summary,
                    "metadata": {
                        **existing_metadata,
                        **metadata,
                        "channels_seen": channels_seen,
                        "destinations_seen": destinations_seen,
                    },
                },
                tenant_id=tenant_id,
            )
            db.add_dlp_incident_timeline(
                incident["id"],
                "event_attached",
                event.get("actor_username", "agent"),
                {
                    "event_count": next_count,
                    "event_id": event_id,
                    "action_result": event.get("action_result", "observed"),
                    "destination_type": event.get("destination_type", ""),
                    "channel": event.get("channel", "file"),
                },
                tenant_id=tenant_id,
            )
            incident = self._normalize_incident(db.get_dlp_incident(incident["id"], tenant_id=tenant_id) or incident)
            incident["_new_alert"] = False
            return incident

        incident_id = db.create_dlp_incident(
            {
                "state": "new",
                "severity": event.get("risk_level", "medium"),
                "title": title,
                "summary": summary,
                "policy_rule_id": event.get("policy_rule_id"),
                "file_hash": event.get("file_hash", ""),
                "content_fingerprint": event.get("content_fingerprint", ""),
                "machine_id": event.get("machine_id", ""),
                "actor_username": event.get("actor_username", ""),
                "channel": event.get("channel", "file"),
                "destination_type": event.get("destination_type", ""),
                "destination_label": event.get("destination_label", ""),
                "first_seen": event.get("timestamp") or utcnow(),
                "last_seen": event.get("timestamp") or utcnow(),
                "event_count": 1,
                "metadata": metadata,
            },
            tenant_id=tenant_id,
        )
        db.add_dlp_incident_timeline(
            incident_id,
            "incident_created",
            event.get("actor_username", "agent"),
            {
                "policy_rule_id": event.get("policy_rule_id"),
                "policy_rule_name": event.get("policy_rule_name", ""),
                "risk_level": event.get("risk_level", "medium"),
                "event_id": event_id,
                "action_result": event.get("action_result", "observed"),
            },
            tenant_id=tenant_id,
        )
        incident = self._normalize_incident(db.get_dlp_incident(incident_id, tenant_id=tenant_id) or {"id": incident_id})
        incident["_new_alert"] = SEVERITY_RANK.get(event.get("risk_level", "medium"), 1) >= SEVERITY_RANK["medium"]
        return incident

    def get_incident_detail(self, tenant_id: int, incident_id: int) -> dict | None:
        incident = db.get_dlp_incident(incident_id, tenant_id=tenant_id)
        if not incident:
            return None
        incident = self._normalize_incident(incident)
        incident["notes"] = [self._normalize_note(row) for row in db.list_dlp_incident_notes(incident_id, tenant_id=tenant_id)]
        incident["timeline"] = [self._normalize_timeline(row) for row in db.list_dlp_incident_timeline(incident_id, tenant_id=tenant_id)]
        incident_events = db.get_dlp_events(
            incident_id=incident_id,
            limit=100,
            offset=0,
        )
        incident_events = [self._normalize_event_row(row) for row in incident_events]
        related_events = db.get_dlp_events(
            file_hash=incident.get("file_hash", ""),
            content_fingerprint=incident.get("content_fingerprint", ""),
            actor_username=incident.get("actor_username", ""),
            limit=40,
            offset=0,
        )
        related_events = [self._normalize_event_row(row) for row in related_events]
        incident["events"] = incident_events
        rule_names = self._rule_name_map(tenant_id)
        incident["policy_name"] = rule_names.get(int(incident.get("policy_rule_id") or 0)) or incident.get("metadata", {}).get("policy_rule_name") or "Current policy"
        incident["evidence_summary"] = self._build_evidence_summary(
            incident,
            incident_events,
            db.list_evidence_objects_for_machine(incident.get("machine_id", ""), tenant_id=tenant_id, limit=8),
        )
        incident["related_activity"] = self._build_related_activity(
            [row for row in related_events if row.get("incident_id") != incident_id or row.get("id") not in {event.get("id") for event in incident_events}]
            or incident_events
        )
        incident["related_incidents"] = [
            self._normalize_incident(item)
            for item in db.list_related_dlp_incidents(
                incident_id,
                tenant_id=tenant_id,
                file_hash=incident.get("file_hash", ""),
                content_fingerprint=incident.get("content_fingerprint", ""),
                actor_username=incident.get("actor_username", ""),
                machine_id=incident.get("machine_id", ""),
                limit=6,
            )
        ]
        history_window_days = int(incident.get("metadata", {}).get("history_window_days") or DEFAULT_HISTORY_WINDOW_DAYS)
        historical_incidents = self._get_historical_incidents(
            tenant_id,
            incident,
            history_window_days=history_window_days,
            limit=12,
        )
        incident["history_summary"] = self._build_history_summary(incident, historical_incidents)
        incident["historical_incidents"] = historical_incidents
        incident["history_filters_applied"] = {
            "default_window_days": history_window_days,
            "actor_username": incident.get("actor_username", ""),
            "machine_id": incident.get("machine_id", ""),
            "file_hash": incident.get("file_hash", ""),
            "content_fingerprint": incident.get("content_fingerprint", ""),
            "destination_type": incident.get("destination_type", ""),
        }
        incident["previous_similar_incident"] = historical_incidents[0] if historical_incidents else None
        incident["retention_summary"] = self._build_retention_summary(tenant_id, incident, incident_events)
        incident["recommended_actions"] = self._recommended_actions(incident, related_events)
        return incident

    def list_incidents(
        self,
        tenant_id: int,
        state: str = "",
        severity: str = "",
        assignee: str = "",
        limit: int = 50,
        offset: int = 0,
        actor_username: str = "",
        machine_id: str = "",
        file_hash: str = "",
        content_fingerprint: str = "",
        destination_type: str = "",
        disposition: str = "",
        date_from: str = "",
        date_to: str = "",
    ) -> dict:
        date_from = self._normalize_datetime_filter(date_from)
        date_to = self._normalize_datetime_filter(date_to)
        items = db.list_dlp_incidents(
            tenant_id=tenant_id,
            state=state,
            severity=severity,
            assignee=assignee,
            limit=limit,
            offset=offset,
            actor_username=actor_username,
            machine_id=machine_id,
            file_hash=file_hash,
            content_fingerprint=content_fingerprint,
            destination_type=destination_type,
            disposition=disposition,
            date_from=date_from,
            date_to=date_to,
        )
        rule_names = self._rule_name_map(tenant_id)
        for index, item in enumerate(items):
            normalized = self._normalize_incident(item)
            normalized["policy_name"] = rule_names.get(int(normalized.get("policy_rule_id") or 0)) or normalized.get("metadata", {}).get("policy_rule_name") or "Current policy"
            items[index] = normalized
        total = db.count_dlp_incidents(
            tenant_id=tenant_id,
            state=state,
            severity=severity,
            assignee=assignee,
            actor_username=actor_username,
            machine_id=machine_id,
            file_hash=file_hash,
            content_fingerprint=content_fingerprint,
            destination_type=destination_type,
            disposition=disposition,
            date_from=date_from,
            date_to=date_to,
        )
        return {"items": items, "total": total}

    def incident_stats(self, tenant_id: int) -> dict:
        incidents = db.list_dlp_incidents(tenant_id=tenant_id, limit=500, offset=0)
        by_state = {}
        by_severity = {}
        by_channel = {}
        for item in incidents:
            by_state[item.get("state", "open")] = by_state.get(item.get("state", "open"), 0) + 1
            by_severity[item.get("severity", "medium")] = by_severity.get(item.get("severity", "medium"), 0) + 1
            by_channel[item.get("channel", "file")] = by_channel.get(item.get("channel", "file"), 0) + 1
        return {
            "total": len(incidents),
            "by_state": by_state,
            "by_severity": by_severity,
            "by_channel": by_channel,
        }

    def list_user_risk(
        self,
        tenant_id: int,
        *,
        date_from: str = "",
        date_to: str = "",
        window_days: int = DEFAULT_HISTORY_WINDOW_DAYS,
        min_risk_level: str = "",
        trend: str = "",
        machine_id: str = "",
        destination_type: str = "",
        disposition: str = "",
        exclude_disposition: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        date_from = self._normalize_datetime_filter(date_from) or self._history_window_start(window_days)
        date_to = self._normalize_datetime_filter(date_to)
        profiles = self._compute_user_risk_profiles(
            tenant_id,
            date_from=date_from,
            date_to=date_to,
            machine_id=machine_id,
            destination_type=destination_type,
            disposition=disposition,
            exclude_disposition=exclude_disposition,
        )
        if min_risk_level:
            threshold = USER_RISK_LEVEL_RANK.get(str(min_risk_level).lower(), 0)
            profiles = [item for item in profiles if USER_RISK_LEVEL_RANK.get(item.get("risk_level", "low"), 0) >= threshold]
        if trend:
            profiles = [item for item in profiles if str(item.get("trend", "")).lower() == str(trend).lower()]
        total = len(profiles)
        items = []
        for profile in profiles[offset:offset + limit]:
            summary_profile = dict(profile)
            summary_profile.pop("_all_reason_history", None)
            items.append(summary_profile)
        return {
            "items": items,
            "total": total,
            "filters": {
                "date_from": date_from,
                "date_to": date_to,
                "window_days": int(window_days or DEFAULT_HISTORY_WINDOW_DAYS),
                "min_risk_level": min_risk_level,
                "trend": trend,
                "machine_id": machine_id,
                "destination_type": destination_type,
                "disposition": disposition,
                "exclude_disposition": exclude_disposition,
            },
        }

    def get_user_risk_detail(
        self,
        tenant_id: int,
        actor_username: str,
        *,
        date_from: str = "",
        date_to: str = "",
        window_days: int = DEFAULT_HISTORY_WINDOW_DAYS,
        machine_id: str = "",
        destination_type: str = "",
        disposition: str = "",
        exclude_disposition: str = "",
    ) -> dict | None:
        actor = str(actor_username or "").strip()
        if not actor:
            return None
        date_from = self._normalize_datetime_filter(date_from) or self._history_window_start(window_days)
        date_to = self._normalize_datetime_filter(date_to)
        profiles = self._compute_user_risk_profiles(
            tenant_id,
            date_from=date_from,
            date_to=date_to,
            machine_id=machine_id,
            destination_type=destination_type,
            disposition=disposition,
            exclude_disposition=exclude_disposition,
            actor_username=actor,
        )
        detail = next((item for item in profiles if item.get("actor_username") == actor), None)
        if not detail:
            return None
        detail["reason_history"] = detail.pop("_all_reason_history", detail.get("reason_history", []))
        detail["filters_applied"] = {
            "date_from": date_from,
            "date_to": date_to,
            "window_days": int(window_days or DEFAULT_HISTORY_WINDOW_DAYS),
            "machine_id": machine_id,
            "destination_type": destination_type,
            "disposition": disposition,
            "exclude_disposition": exclude_disposition,
        }
        return detail

    def update_incident_review(self, tenant_id: int, incident_id: int, payload: dict, actor: str) -> dict | None:
        incident = db.get_dlp_incident(incident_id, tenant_id=tenant_id)
        if not incident:
            return None
        incident = self._normalize_incident(incident)
        metadata = dict(incident.get("metadata") or {})
        updates: dict[str, Any] = {}
        timeline_payload: dict[str, Any] = {}
        state = payload.get("state")
        if state:
            normalized_state = self._normalize_incident_state(state)
            updates["state"] = normalized_state
            timeline_payload["state"] = normalized_state
        for key in ("severity", "assignee", "summary"):
            if payload.get(key) not in (None, ""):
                updates[key] = payload[key]
                timeline_payload[key] = payload[key]
        disposition = payload.get("disposition")
        if disposition:
            metadata["disposition"] = INCIDENT_DISPOSITIONS.get(str(disposition).lower(), str(disposition).lower())
            timeline_payload["disposition"] = metadata["disposition"]
        resolution_reason = payload.get("resolution_reason")
        if resolution_reason:
            metadata["resolution_reason"] = resolution_reason
            timeline_payload["resolution_reason"] = resolution_reason
        if metadata != incident.get("metadata", {}):
            updates["metadata"] = metadata
        if updates:
            db.update_dlp_incident(incident_id, updates, tenant_id=tenant_id)
            db.add_dlp_incident_timeline(incident_id, "incident_review_updated", actor, timeline_payload or updates, tenant_id=tenant_id)
        note = payload.get("note")
        if note:
            db.add_dlp_incident_note(incident_id, note, actor, tenant_id=tenant_id)
            db.add_dlp_incident_timeline(
                incident_id,
                "analyst_note_added",
                actor,
                {"preview": note[:160]},
                tenant_id=tenant_id,
            )
        return self.get_incident_detail(tenant_id, incident_id)

    def _history_window_start(self, days: int = DEFAULT_HISTORY_WINDOW_DAYS) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=max(int(days or DEFAULT_HISTORY_WINDOW_DAYS), 1))).isoformat()

    def _normalize_datetime_filter(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if "T" in text and "+" not in text and text.count(":") >= 2:
            prefix, sep, suffix = text.rpartition(" ")
            if sep and ":" in suffix:
                return f"{prefix}+{suffix}"
        return text

    def _parse_timestamp(self, value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    def _risk_level_from_score(self, score: int) -> dict:
        for entry in USER_RISK_LEVELS:
            if score >= entry["min"]:
                return entry
        return USER_RISK_LEVELS[-1]

    def _reason_copy(self, code: str, count: int) -> str:
        labels = {
            "repeat_blocked_actions": "Repeated blocked actions",
            "repeat_warning_attempts": "Warnings followed by continued attempts",
            "after_hours_sensitive_activity": "After-hours sensitive activity",
            "new_usb_destination": "First-time sensitive USB activity",
            "new_destination_type": "First-time sensitive destination type",
            "repeat_sensitive_file": "Repeated attempts involving the same file identity",
            "repeat_incident_count": "Repeated related incidents",
            "multiple_machines": "Sensitive activity across multiple machines",
            "escalated_by_analyst": "Analyst escalated related incidents",
            "contained_by_analyst": "Analyst confirmed risky activity",
            "high_risk_spike": "Short-term spike in high-risk activity",
            "cooldown": "Recent risky activity is cooling down",
            "approved_business_use": "Approved business use lowered the score",
            "false_positive": "False positive history lowered the score",
        }
        label = labels.get(code, code.replace("_", " "))
        if count > 1 and code not in {"cooldown", "multiple_machines", "high_risk_spike"}:
            return f"{label} ({count})"
        return label

    def _risk_profile_sort_key(self, item: dict) -> tuple:
        return (
            -int(item.get("risk_score", 0) or 0),
            -int(item.get("blocked_event_count", 0) or 0),
            -int(item.get("high_risk_event_count", 0) or 0),
            str(item.get("latest_high_risk_timestamp") or item.get("latest_activity_at") or ""),
        )

    def _compute_user_risk_profiles(
        self,
        tenant_id: int,
        *,
        date_from: str,
        date_to: str = "",
        machine_id: str = "",
        destination_type: str = "",
        disposition: str = "",
        exclude_disposition: str = "",
        actor_username: str = "",
    ) -> list[dict]:
        with self._tenant_scope(tenant_id):
            events = [
                self._normalize_event_row(row)
                for row in db.get_dlp_events(
                    machine_id=machine_id,
                    destination_type=destination_type,
                    date_from=date_from,
                    date_to=date_to,
                    actor_username=actor_username,
                    limit=5000,
                    offset=0,
                )
            ]
            incidents = [
                self._normalize_incident(row)
                for row in db.list_dlp_incidents(
                    tenant_id=tenant_id,
                    machine_id=machine_id,
                    destination_type=destination_type,
                    actor_username=actor_username,
                    disposition=disposition,
                    date_from=date_from,
                    date_to=date_to,
                    limit=2000,
                    offset=0,
                )
            ]
        incident_map = {int(item.get("id") or 0): item for item in incidents if item.get("id") is not None}
        if exclude_disposition:
            incidents = [
                item for item in incidents
                if str(item.get("metadata", {}).get("disposition") or "").lower() != str(exclude_disposition).lower()
            ]
            incident_map = {int(item.get("id") or 0): item for item in incidents if item.get("id") is not None}
        if disposition:
            target = str(disposition).lower()
            incidents = [
                item for item in incidents
                if str(item.get("metadata", {}).get("disposition") or "").lower() == target
            ]
            incident_map = {int(item.get("id") or 0): item for item in incidents if item.get("id") is not None}
        filtered_events: list[dict] = []
        for row in events:
            incident_id = int(row.get("incident_id") or 0)
            incident = incident_map.get(incident_id)
            if disposition and incident_id and not incident:
                continue
            if exclude_disposition and incident_id and not incident:
                continue
            filtered_events.append(row)
        events = filtered_events

        grouped: dict[str, dict] = {}
        for event in events:
            actor = str(event.get("actor_username") or "").strip()
            if not actor:
                continue
            entry = grouped.setdefault(
                actor,
                {
                    "actor_username": actor,
                    "events": [],
                    "incidents": [],
                    "machine_ids": set(),
                    "destination_types": set(),
                    "file_keys": {},
                    "reason_counts": {},
                    "reason_points": {},
                    "latest_event": None,
                    "high_risk_event_count": 0,
                    "blocked_event_count": 0,
                    "warning_event_count": 0,
                    "after_hours_event_count": 0,
                    "new_destination_count": 0,
                    "repeat_incident_count": 0,
                    "latest_high_risk_timestamp": "",
                },
            )
            entry["events"].append(event)
            if event.get("machine_id"):
                entry["machine_ids"].add(event["machine_id"])
            if event.get("destination_type"):
                entry["destination_types"].add(event["destination_type"])
            timestamp = self._parse_timestamp(event.get("timestamp"))
            if not entry["latest_event"] or (
                timestamp and self._parse_timestamp(entry["latest_event"].get("timestamp")) and timestamp >= self._parse_timestamp(entry["latest_event"].get("timestamp"))
            ) or (timestamp and not self._parse_timestamp(entry["latest_event"].get("timestamp"))):
                entry["latest_event"] = event
            risk_level = str(event.get("risk_level") or event.get("risk") or "low").lower()
            if risk_level in HIGH_RISK_LEVELS:
                entry["high_risk_event_count"] += 1
                if event.get("timestamp") and str(event.get("timestamp")) > str(entry["latest_high_risk_timestamp"] or ""):
                    entry["latest_high_risk_timestamp"] = event.get("timestamp")
            if str(event.get("action_result") or "").lower() == "blocked":
                entry["blocked_event_count"] += 1
            if str(event.get("action_result") or "").lower() in WARNING_RESULTS or str(event.get("action_taken") or "").lower() == "warn_user":
                entry["warning_event_count"] += 1
            if timestamp and (timestamp.hour < 6 or timestamp.hour >= 20):
                entry["after_hours_event_count"] += 1
            file_key = event.get("file_hash") or event.get("content_fingerprint") or ""
            if file_key:
                entry["file_keys"][file_key] = entry["file_keys"].get(file_key, 0) + 1

        for incident in incidents:
            actor = str(incident.get("actor_username") or "").strip()
            if not actor:
                continue
            entry = grouped.setdefault(
                actor,
                {
                    "actor_username": actor,
                    "events": [],
                    "incidents": [],
                    "machine_ids": set(),
                    "destination_types": set(),
                    "file_keys": {},
                    "reason_counts": {},
                    "reason_points": {},
                    "latest_event": None,
                    "high_risk_event_count": 0,
                    "blocked_event_count": 0,
                    "warning_event_count": 0,
                    "after_hours_event_count": 0,
                    "new_destination_count": 0,
                    "repeat_incident_count": 0,
                    "latest_high_risk_timestamp": "",
                },
            )
            entry["incidents"].append(incident)
            if incident.get("machine_id"):
                entry["machine_ids"].add(incident["machine_id"])
            if incident.get("destination_type"):
                entry["destination_types"].add(incident["destination_type"])

        profiles: list[dict] = []
        now = datetime.now(timezone.utc)
        for actor, payload in grouped.items():
            events_for_actor = sorted(
                payload["events"],
                key=lambda item: self._parse_timestamp(item.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            incidents_for_actor = sorted(
                payload["incidents"],
                key=lambda item: self._parse_timestamp(item.get("last_seen")) or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            if not events_for_actor and not incidents_for_actor:
                continue

            risk_score = 0
            reason_counts: dict[str, int] = {}
            reason_points: dict[str, int] = {}

            def add_reason(code: str, points: int, count: int = 1):
                nonlocal risk_score
                risk_score += points
                reason_counts[code] = reason_counts.get(code, 0) + count
                reason_points[code] = reason_points.get(code, 0) + points

            blocked_count = payload["blocked_event_count"]
            warning_count = payload["warning_event_count"]
            after_hours_count = payload["after_hours_event_count"]
            high_risk_count = payload["high_risk_event_count"]
            repeated_file_count = sum(1 for count in payload["file_keys"].values() if count > 1)
            machine_count = len(payload["machine_ids"])
            destination_count = len(payload["destination_types"])
            incident_repeat_count = sum(1 for incident in incidents_for_actor if int(incident.get("event_count") or 0) > 1)
            latest_activity_at = (
                events_for_actor[0].get("timestamp")
                if events_for_actor
                else incidents_for_actor[0].get("last_seen")
            )
            latest_activity_dt = self._parse_timestamp(latest_activity_at)

            if blocked_count:
                add_reason("repeat_blocked_actions", blocked_count * 6, blocked_count)
            if warning_count >= 2:
                add_reason("repeat_warning_attempts", 4 + max(0, warning_count - 2), warning_count)
            if after_hours_count:
                add_reason("after_hours_sensitive_activity", min(after_hours_count * 2, 6), after_hours_count)
            if "usb" in payload["destination_types"]:
                add_reason("new_usb_destination", 3, 1)
            if destination_count > 1:
                add_reason("new_destination_type", min(destination_count, 3), destination_count)
            if repeated_file_count:
                add_reason("repeat_sensitive_file", repeated_file_count * 3, repeated_file_count)
            if machine_count > 1:
                add_reason("multiple_machines", 3 + (machine_count - 2), machine_count)
            if incident_repeat_count:
                add_reason("repeat_incident_count", min(incident_repeat_count * 2, 6), incident_repeat_count)

            recent7_high = 0
            recent30_high = 0
            for event in events_for_actor:
                ts = self._parse_timestamp(event.get("timestamp"))
                if not ts:
                    continue
                age_days = (now - ts.astimezone(timezone.utc)).days
                level = str(event.get("risk_level") or event.get("risk") or "low").lower()
                if age_days <= 7 and level in HIGH_RISK_LEVELS:
                    recent7_high += 1
                if age_days <= 30 and level in HIGH_RISK_LEVELS:
                    recent30_high += 1
            if recent7_high >= 2 and recent7_high >= max(2, recent30_high // 2):
                add_reason("high_risk_spike", 5, recent7_high)

            contained_count = 0
            escalated_count = 0
            approved_count = 0
            false_positive_count = 0
            for incident in incidents_for_actor:
                disposition_value = str(incident.get("metadata", {}).get("disposition") or "").lower()
                if disposition_value == "contained":
                    contained_count += 1
                elif disposition_value == "escalated":
                    escalated_count += 1
                elif disposition_value == "approved_business_use":
                    approved_count += 1
                elif disposition_value == "false_positive":
                    false_positive_count += 1
            if contained_count:
                add_reason("contained_by_analyst", contained_count * 3, contained_count)
            if escalated_count:
                add_reason("escalated_by_analyst", escalated_count * 5, escalated_count)
            if approved_count:
                add_reason("approved_business_use", -min(approved_count * 3, 6), approved_count)
            if false_positive_count:
                add_reason("false_positive", -min(false_positive_count * 4, 8), false_positive_count)

            if latest_activity_dt:
                quiet_days = (now - latest_activity_dt.astimezone(timezone.utc)).days
                if quiet_days >= 14:
                    add_reason("cooldown", -4 if quiet_days >= 30 else -2, quiet_days)

            risk_score = max(int(risk_score), 0)
            risk_level = self._risk_level_from_score(risk_score)
            trend_label = "stable"
            if latest_activity_dt and (now - latest_activity_dt.astimezone(timezone.utc)).days >= 14:
                trend_label = "cooling"
            elif recent7_high >= max(2, recent30_high // 2) or blocked_count >= 2:
                trend_label = "rising"

            top_reasons = sorted(
                reason_points.items(),
                key=lambda item: (-abs(item[1]), -reason_counts.get(item[0], 0), item[0]),
            )
            all_codes = [code for code, _points in top_reasons]
            top_codes = all_codes[:5]
            reason_summary = [self._reason_copy(code, reason_counts.get(code, 1)) for code in top_codes]
            latest_event = payload["latest_event"] or (events_for_actor[0] if events_for_actor else {})
            latest_incident = incidents_for_actor[0] if incidents_for_actor else None
            related_files = []
            for item in events_for_actor:
                label = item.get("file_name") or item.get("file_path") or "Sensitive content"
                candidate = {
                    "file_name": item.get("file_name") or label,
                    "file_path": item.get("file_path") or "",
                    "file_hash": item.get("file_hash") or "",
                    "content_fingerprint": item.get("content_fingerprint") or "",
                }
                if not any(
                    existing.get("file_name") == candidate["file_name"]
                    and existing.get("file_hash") == candidate["file_hash"]
                    and existing.get("content_fingerprint") == candidate["content_fingerprint"]
                    for existing in related_files
                ):
                    related_files.append(candidate)
                if len(related_files) >= 5:
                    break
            recent_activity_summary = (
                latest_event.get("file_name")
                or latest_event.get("file_path")
                or (latest_incident.get("summary") if latest_incident else "")
                or "Recent sensitive activity"
            )
            latest_destination_type = (
                latest_event.get("destination_type")
                or (latest_incident.get("destination_type") if latest_incident else "")
                or ""
            )
            latest_machine_id = (
                latest_event.get("machine_id")
                or (latest_incident.get("machine_id") if latest_incident else "")
                or ""
            )
            profile = {
                "actor_username": actor,
                "risk_score": risk_score,
                "risk_level": risk_level["label"],
                "risk_tone": risk_level["tone"],
                "trend": trend_label,
                "reason_codes": top_codes,
                "reason_summary": reason_summary,
                "reason_history": [
                    {
                        "code": code,
                        "label": self._reason_copy(code, reason_counts.get(code, 1)),
                        "count": reason_counts.get(code, 1),
                        "points": reason_points.get(code, 0),
                    }
                    for code in top_codes
                ],
                "_all_reason_history": [
                    {
                        "code": code,
                        "label": self._reason_copy(code, reason_counts.get(code, 1)),
                        "count": reason_counts.get(code, 1),
                        "points": reason_points.get(code, 0),
                    }
                    for code in all_codes
                ],
                "recent_activity_summary": recent_activity_summary,
                "linked_machine_count": machine_count,
                "related_machine_count": machine_count,
                "repeat_incident_count": len(incidents_for_actor),
                "blocked_event_count": blocked_count,
                "warning_event_count": warning_count,
                "after_hours_event_count": after_hours_count,
                "new_destination_count": destination_count,
                "high_risk_event_count": high_risk_count,
                "latest_high_risk_timestamp": payload["latest_high_risk_timestamp"] or latest_activity_at,
                "latest_activity_at": latest_activity_at,
                "latest_destination_type": latest_destination_type,
                "latest_machine_id": latest_machine_id,
                "recent_machine_ids": sorted(payload["machine_ids"]),
                "related_files": related_files,
                "recommended_actions": self._user_risk_recommended_actions(
                    risk_level["label"],
                    trend_label,
                    top_codes,
                    latest_event,
                    latest_incident,
                ),
                "recent_events": [
                    self._build_related_activity([event])[0]
                    for event in events_for_actor[:12]
                ],
                "recent_incidents": [
                    {
                        "id": incident.get("id"),
                        "title": incident.get("title") or incident.get("summary") or f"DLP incident {incident.get('id')}",
                        "summary": incident.get("summary") or "",
                        "severity": incident.get("severity", "medium"),
                        "state": incident.get("state", "new"),
                        "disposition": incident.get("metadata", {}).get("disposition", ""),
                        "destination_type": incident.get("destination_type", ""),
                        "destination_label": incident.get("destination_label", ""),
                        "last_seen": incident.get("last_seen"),
                        "machine_id": incident.get("machine_id", ""),
                    }
                    for incident in incidents_for_actor[:10]
                ],
            }
            profiles.append(profile)
        profiles.sort(key=self._risk_profile_sort_key)
        return profiles

    def _user_risk_recommended_actions(
        self,
        risk_level: str,
        trend: str,
        reason_codes: list[str],
        latest_event: dict | None,
        latest_incident: dict | None,
    ) -> list[str]:
        actions: list[str] = []
        if risk_level in {"high", "critical"}:
            actions.append("Review this user's newest blocked or high-risk action first.")
        if trend == "rising":
            actions.append("Check whether the risky behavior is spreading across more files, devices, or destinations.")
        if "multiple_machines" in reason_codes:
            actions.append("Verify whether the same user is moving sensitive data across multiple machines.")
        if "after_hours_sensitive_activity" in reason_codes:
            actions.append("Confirm whether the after-hours activity had an approved business reason.")
        if latest_event and str(latest_event.get("action_result") or "").lower() == "blocked":
            actions.append("Confirm whether the blocked action should stay blocked or needs a tightly scoped exception.")
        if latest_incident and latest_incident.get("metadata", {}).get("disposition") == "escalated":
            actions.append("Follow the earlier escalation outcome before closing new alerts for this user.")
        if not actions:
            actions.append("Review the latest user activity and capture an analyst decision.")
        return actions

    def _get_historical_incidents(self, tenant_id: int, incident: dict, *, history_window_days: int = DEFAULT_HISTORY_WINDOW_DAYS, limit: int = 12) -> list[dict]:
        start = self._history_window_start(history_window_days)
        candidates = db.list_related_dlp_incidents(
            int(incident.get("id") or 0),
            tenant_id=tenant_id,
            actor_username=incident.get("actor_username", ""),
            machine_id=incident.get("machine_id", ""),
            file_hash=incident.get("file_hash", ""),
            content_fingerprint=incident.get("content_fingerprint", ""),
            destination_type=incident.get("destination_type", ""),
            destination_label=incident.get("destination_label", ""),
            date_from=start,
            limit=limit + 12,
        )
        rule_names = self._rule_name_map(tenant_id)
        history: list[dict] = []
        for row in candidates:
            normalized = self._normalize_incident(row)
            normalized["policy_name"] = rule_names.get(int(normalized.get("policy_rule_id") or 0)) or normalized.get("metadata", {}).get("policy_rule_name") or "Current policy"
            normalized["relation_reasons"] = self._history_relation_reasons(incident, normalized)
            history.append(normalized)
            if len(history) >= limit:
                break
        return history

    def _history_relation_reasons(self, source: dict, candidate: dict) -> list[str]:
        reasons: list[str] = []
        if source.get("actor_username") and source.get("actor_username") == candidate.get("actor_username"):
            reasons.append("same_user")
        if source.get("machine_id") and source.get("machine_id") == candidate.get("machine_id"):
            reasons.append("same_machine")
        if source.get("file_hash") and source.get("file_hash") == candidate.get("file_hash"):
            reasons.append("same_file_hash")
        elif source.get("content_fingerprint") and source.get("content_fingerprint") == candidate.get("content_fingerprint"):
            reasons.append("same_content_fingerprint")
        if source.get("destination_type") and source.get("destination_type") == candidate.get("destination_type"):
            reasons.append("same_destination_type")
        if source.get("destination_label") and source.get("destination_label") == candidate.get("destination_label"):
            reasons.append("same_destination_label")
        return reasons

    def _build_history_summary(self, incident: dict, historical_incidents: list[dict]) -> dict:
        counts = {
            "same_user": 0,
            "same_machine": 0,
            "same_file_identity": 0,
            "same_destination": 0,
        }
        first_seen = incident.get("first_seen")
        last_seen = incident.get("last_seen")
        last_disposition = incident.get("metadata", {}).get("disposition") or ""
        for row in historical_incidents:
            reasons = set(row.get("relation_reasons") or [])
            if "same_user" in reasons:
                counts["same_user"] += 1
            if "same_machine" in reasons:
                counts["same_machine"] += 1
            if {"same_file_hash", "same_content_fingerprint"} & reasons:
                counts["same_file_identity"] += 1
            if {"same_destination_type", "same_destination_label"} & reasons:
                counts["same_destination"] += 1
            if row.get("first_seen") and (not first_seen or str(row.get("first_seen")) < str(first_seen)):
                first_seen = row.get("first_seen")
            if row.get("last_seen") and (not last_seen or str(row.get("last_seen")) > str(last_seen)):
                last_seen = row.get("last_seen")
            if not last_disposition and row.get("metadata", {}).get("disposition"):
                last_disposition = row.get("metadata", {}).get("disposition")
        return {
            "repeat_incident_count": len(historical_incidents),
            "first_seen": first_seen,
            "last_seen": last_seen,
            "last_analyst_outcome": last_disposition or "none_recorded",
            **counts,
        }

    def _build_retention_summary(self, tenant_id: int, incident: dict, incident_events: list[dict]) -> dict:
        storage = db.get_storage_settings()
        evidence_rows = db.list_evidence_objects_for_machine(incident.get("machine_id", ""), tenant_id=tenant_id, limit=50)
        related_event_ids = {row.get("id") for row in incident_events}
        active = 0
        expiring_soon = 0
        expired = 0
        linked_artifacts = 0
        now = datetime.now(timezone.utc)
        next_expiry: str | None = None
        for row in evidence_rows:
            metadata = _json_loads(row.get("metadata"), {})
            row_event_id = metadata.get("source_event_id") or metadata.get("event_id")
            if row_event_id and row_event_id in related_event_ids:
                linked_artifacts += 1
            retention_status = str(row.get("retention_status") or "active").lower()
            expires_at = row.get("retention_expires_at")
            if expires_at:
                expires_text = expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at)
                if not next_expiry or expires_text < next_expiry:
                    next_expiry = expires_text
                try:
                    expires_dt = expires_at if isinstance(expires_at, datetime) else datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                except Exception:
                    expires_dt = None
                if expires_dt and expires_dt < now:
                    expired += 1
                    continue
                if expires_dt and expires_dt <= now + timedelta(days=14):
                    expiring_soon += 1
                    continue
            if retention_status == "expired":
                expired += 1
            else:
                active += 1
        return {
            "window_days": DEFAULT_HISTORY_WINDOW_DAYS,
            "storage_backend": storage.get("evidence_backend", "filesystem"),
            "encryption_status": storage.get("evidence_encryption_status", "plaintext_at_rest"),
            "linked_artifact_count": linked_artifacts,
            "active_artifact_count": active,
            "expiring_soon_count": expiring_soon,
            "expired_artifact_count": expired,
            "next_expiry_at": next_expiry,
        }

    def _normalize_exception(self, row: dict) -> dict:
        item = dict(row)
        item["metadata"] = _json_loads(item.get("metadata"), {})
        return item

    def _max_severity(self, a: str, b: str) -> str:
        return a if SEVERITY_RANK.get(a, 0) >= SEVERITY_RANK.get(b, 0) else b

    def _normalize_incident_state(self, value: str) -> str:
        state = str(value or "new").strip().lower()
        return INCIDENT_STATE_MAP.get(state, state or "new")

    def _normalize_incident(self, incident: dict) -> dict:
        item = dict(incident or {})
        item["metadata"] = _json_loads(item.get("metadata"), {})
        item["state"] = self._normalize_incident_state(item.get("state", "new"))
        if not item.get("actor_username"):
            item["actor_username"] = item["metadata"].get("actor_username", "")
        if not item.get("destination_type"):
            item["destination_type"] = item["metadata"].get("destination_type", "")
        if not item.get("destination_label"):
            item["destination_label"] = item["metadata"].get("destination_label", "")
        return item

    def _normalize_note(self, note: dict) -> dict:
        item = dict(note or {})
        item["author"] = item.get("created_by") or item.get("author") or "analyst"
        return item

    def _normalize_timeline(self, entry: dict) -> dict:
        item = dict(entry or {})
        item["payload"] = _json_loads(item.get("payload"), {})
        actor = str(item.get("actor") or "").lower()
        item["actor_type"] = "analyst" if actor and actor not in {"system", "agent"} else "system"
        return item

    def _normalize_event_row(self, row: dict) -> dict:
        item = dict(row or {})
        item["findings"] = _json_loads(item.get("findings"), [])
        item["classifier_hits"] = _json_loads(item.get("classifier_hits"), [])
        item["exception_applied"] = _json_loads(item.get("exception_applied"), {})
        item["masked_evidence"] = _json_loads(item.get("masked_evidence"), [])
        item["scoring"] = _json_loads(item.get("scoring"), {})
        return item

    def _rule_name_map(self, tenant_id: int) -> dict[int, str]:
        names: dict[int, str] = {}
        for row in db.list_dlp_rules(None, tenant_id=tenant_id):
            if row.get("id") is not None:
                names[int(row["id"])] = row.get("name") or "Current policy"
        return names

    def _recommended_actions(self, incident: dict, related_events: list[dict]) -> list[str]:
        actions: list[str] = []
        action_result = str(incident.get("metadata", {}).get("action_result", "")).lower()
        state = incident.get("state", "new")
        if state in {"new", "investigating"}:
            actions.append("Review the newest event and confirm whether the response matched policy.")
        if action_result == "blocked":
            actions.append("Confirm whether the blocked action was an attempted exfiltration or expected policy enforcement.")
        if any(str(event.get("destination_type", "")).lower() in {"usb", "cloud_sync", "upload", "email"} for event in related_events):
            actions.append("Check for repeat attempts on the same file, destination, or user session.")
        if incident.get("metadata", {}).get("exception_applied"):
            actions.append("Verify the business exception is still valid and scoped tightly enough.")
        if not actions:
            actions.append("Capture the analyst decision and close or escalate the incident.")
        return actions

    def _build_evidence_summary(self, incident: dict, related_events: list[dict], evidence_rows: list[dict]) -> list[dict]:
        metadata = incident.get("metadata", {})
        evidence: list[dict] = []
        classifier_hits = metadata.get("classifier_hits") or []
        if classifier_hits:
            evidence.append(
                {
                    "kind": "classifier_hits",
                    "title": "Detection matches",
                    "items": [
                        {
                            "name": hit.get("name") or hit.get("type") or "detector",
                            "severity": hit.get("severity") or incident.get("severity", "medium"),
                            "category": hit.get("category") or "",
                            "count": hit.get("count") or hit.get("matches") or 1,
                        }
                        for hit in classifier_hits
                    ],
                }
            )
        masked = metadata.get("masked_evidence") or []
        if masked:
            evidence.append(
                {
                    "kind": "masked_evidence",
                    "title": "Masked evidence",
                    "items": masked[:10],
                }
            )
        if related_events:
            evidence.append(
                {
                    "kind": "related_events",
                    "title": "Related endpoint activity",
                    "items": [
                        {
                            "event_id": event.get("id"),
                            "timestamp": event.get("timestamp"),
                            "channel": event.get("channel", "file"),
                            "destination_type": event.get("destination_type") or event.get("destination"),
                            "destination_label": event.get("destination_label") or event.get("device") or "",
                            "action_result": event.get("action_result", "observed"),
                            "file_name": event.get("file_name") or event.get("file_path") or "Sensitive content",
                        }
                        for event in related_events[:8]
                    ],
                }
            )
        if evidence_rows:
            evidence.append(
                {
                    "kind": "stored_artifacts",
                    "title": "Stored artifacts",
                    "items": [
                        {
                            "id": row.get("id"),
                            "category": row.get("category", "generic"),
                            "classification": row.get("evidence_classification", "standard"),
                            "retention_status": row.get("retention_status", "active"),
                            "encryption_status": row.get("encryption_status", "unknown"),
                            "created_at": row.get("created_at"),
                        }
                        for row in evidence_rows[:6]
                    ],
                }
            )
        return evidence

    def _build_related_activity(self, related_events: list[dict]) -> list[dict]:
        return [
            {
                "id": event.get("id"),
                "timestamp": event.get("timestamp"),
                "channel": event.get("channel", "file"),
                "destination_type": event.get("destination_type") or event.get("destination") or "local",
                "destination_label": event.get("destination_label") or event.get("device") or "",
                "action_taken": event.get("action_taken", "monitor"),
                "action_result": event.get("action_result", "observed"),
                "file_name": event.get("file_name") or event.get("file_path") or "Sensitive content",
                "file_path": event.get("file_path", ""),
                "risk_level": event.get("risk_level", "medium"),
                "enterprise_label": event.get("enterprise_label", ""),
            }
            for event in related_events[:12]
        ]

dlp_service = DlpService()
