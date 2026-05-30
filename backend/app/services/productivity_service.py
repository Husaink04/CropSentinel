from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.db.core import Connection as _Conn, get_tenant_id as _tid
from database import db


_BROWSER_HINTS = ("chrome", "msedge", "edge", "firefox", "brave", "opera", "safari", "browser")
_CATEGORY_ORDER = ("productive", "supportive", "neutral", "distracting", "excluded")
_DEFAULT_CATEGORY_WEIGHTS = {
    "productive": 1.0,
    "supportive": 0.72,
    "neutral": 0.35,
    "distracting": 0.0,
    "excluded": 0.0,
}
_DEFAULT_SUPPORTIVE_APPS = [
    "slack",
    "teams",
    "zoom",
    "meet",
    "outlook",
    "gmail",
    "calendar",
    "notion",
    "confluence",
]
_DEFAULT_AI_ASSIST = [
    "chatgpt",
    "claude",
    "gemini",
    "copilot",
    "cursor",
    "perplexity",
]
_DEFAULT_DISTRACTING_DOMAINS = ["youtube.com", "facebook.com", "twitter.com", "instagram.com", "reddit.com", "netflix.com"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _date_range_bounds(start_date: str = "", end_date: str = "") -> tuple[datetime, datetime]:
    now = _utcnow()
    if start_date:
        start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if end_date:
        end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
    else:
        end = now
    if end <= start:
        end = start + timedelta(days=1)
    return start, end


def _iso_day(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).date().isoformat()


def _normalize_text(value: str) -> str:
    return (value or "").strip().lower()


def _normalize_domain(value: str) -> str:
    host = _normalize_text(value)
    if host.startswith("www."):
        host = host[4:]
    if "/" in host:
        host = host.split("/", 1)[0]
    return host


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return 0


def _fmt_duration(seconds: int) -> str:
    total = max(0, _safe_int(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _is_browser_app(app_name: str, process_name: str) -> bool:
    combined = f"{_normalize_text(app_name)} {_normalize_text(process_name)}"
    return any(hint in combined for hint in _BROWSER_HINTS)


@dataclass
class RuleMatch:
    category: str
    weight: float
    always_active: bool
    rule_name: str


class ProductivityService:
    def _default_policy(self) -> dict[str, Any]:
        return {
            "productivity_apps": [],
            "productivity_domains": [],
            "productivity_categories": dict(_DEFAULT_CATEGORY_WEIGHTS),
            "meeting_like_apps": [
                {"match_value": "teams", "match_type": "contains", "category": "supportive", "weight": 0.8, "always_active": True},
                {"match_value": "zoom", "match_type": "contains", "category": "supportive", "weight": 0.8, "always_active": True},
                {"match_value": "meet", "match_type": "contains", "category": "supportive", "weight": 0.8, "always_active": True},
                {"match_value": "slack", "match_type": "contains", "category": "supportive", "weight": 0.75, "always_active": True},
            ],
            "ai_work_assist_apps_or_domains": list(_DEFAULT_AI_ASSIST),
            "productivity_policy_version": 1,
        }

    def _normalize_policy(self, settings: dict[str, Any]) -> dict[str, Any]:
        defaults = self._default_policy()
        categories = dict(_DEFAULT_CATEGORY_WEIGHTS)
        categories.update(settings.get("productivity_categories") or {})

        app_rules = []
        for item in settings.get("productivity_apps") or []:
            if isinstance(item, dict) and item.get("match_value"):
                app_rules.append({
                    "match_value": _normalize_text(item.get("match_value", "")),
                    "match_type": item.get("match_type") or "contains",
                    "category": item.get("category") or "neutral",
                    "weight": float(item.get("weight", categories.get(item.get("category") or "neutral", 0.35))),
                    "always_active": bool(item.get("always_active")),
                })
        domain_rules = []
        for item in settings.get("productivity_domains") or []:
            if isinstance(item, dict) and item.get("match_value"):
                domain_rules.append({
                    "match_value": _normalize_domain(item.get("match_value", "")),
                    "match_type": item.get("match_type") or "contains",
                    "category": item.get("category") or "neutral",
                    "weight": float(item.get("weight", categories.get(item.get("category") or "neutral", 0.35))),
                    "always_active": bool(item.get("always_active")),
                })

        if not app_rules:
            for value in settings.get("productive_apps") or []:
                normalized = _normalize_text(value)
                if normalized:
                    app_rules.append({"match_value": normalized, "match_type": "contains", "category": "productive", "weight": categories["productive"], "always_active": False})
            for value in _DEFAULT_SUPPORTIVE_APPS:
                app_rules.append({"match_value": value, "match_type": "contains", "category": "supportive", "weight": 0.72, "always_active": value in {"teams", "zoom", "meet", "slack"}})
            for value in _DEFAULT_AI_ASSIST:
                app_rules.append({"match_value": value, "match_type": "contains", "category": "supportive", "weight": 0.7, "always_active": False})

        if not domain_rules:
            for value in settings.get("productive_domains") or []:
                normalized = _normalize_domain(value)
                if normalized:
                    category = "supportive" if any(token in normalized for token in ("docs.", "meet.", "calendar.", "mail.")) else "productive"
                    weight = 0.72 if category == "supportive" else 1.0
                    always_active = any(token in normalized for token in ("meet.google.com", "teams.microsoft.com", "zoom.us"))
                    domain_rules.append({"match_value": normalized, "match_type": "contains", "category": category, "weight": weight, "always_active": always_active})
            distracting = settings.get("unproductive_domains") or _DEFAULT_DISTRACTING_DOMAINS
            for value in distracting:
                normalized = _normalize_domain(value)
                if normalized:
                    domain_rules.append({"match_value": normalized, "match_type": "contains", "category": "distracting", "weight": 0.0, "always_active": False})
            for value in _DEFAULT_AI_ASSIST:
                domain_rules.append({"match_value": value, "match_type": "contains", "category": "supportive", "weight": 0.7, "always_active": False})

        policy = {
            **defaults,
            "productivity_apps": app_rules,
            "productivity_domains": domain_rules,
            "productivity_categories": categories,
            "productivity_policy_version": int(settings.get("productivity_policy_version") or 1),
            "track_input_activity": settings.get("track_input_activity") is True,
            "track_browser": settings.get("track_browser") is not False,
        }
        return policy

    def get_policy_settings(self) -> dict[str, Any]:
        settings = db.get_settings()
        policy = self._normalize_policy(settings)
        return {
            "productivity_apps": policy["productivity_apps"],
            "productivity_domains": policy["productivity_domains"],
            "productivity_categories": policy["productivity_categories"],
            "meeting_like_apps": policy["meeting_like_apps"],
            "ai_work_assist_apps_or_domains": policy["ai_work_assist_apps_or_domains"],
            "productivity_policy_version": policy["productivity_policy_version"],
        }

    def build_settings_patch(self, payload: dict[str, Any]) -> dict[str, Any]:
        patch = dict(payload)
        apps = [item for item in payload.get("productivity_apps") or [] if isinstance(item, dict) and item.get("match_value")]
        domains = [item for item in payload.get("productivity_domains") or [] if isinstance(item, dict) and item.get("match_value")]

        if apps:
            patch["productive_apps"] = sorted({item["match_value"] for item in apps if item.get("category") == "productive"})
        if domains:
            patch["productive_domains"] = sorted({item["match_value"] for item in domains if item.get("category") in {"productive", "supportive"}})
            patch["unproductive_domains"] = sorted({item["match_value"] for item in domains if item.get("category") == "distracting"})
        if apps or domains:
            patch["productivity_policy_version"] = int(payload.get("productivity_policy_version") or 1)
        return patch

    def _match_rule(self, value: str, rules: list[dict[str, Any]], *, default_weight: float = 0.35) -> RuleMatch:
        normalized = _normalize_text(value)
        for rule in rules:
            match_value = _normalize_text(rule.get("match_value", ""))
            if not match_value:
                continue
            match_type = rule.get("match_type") or "contains"
            matched = normalized == match_value if match_type == "exact" else match_value in normalized
            if matched:
                category = rule.get("category") or "neutral"
                return RuleMatch(
                    category=category,
                    weight=float(rule.get("weight", default_weight)),
                    always_active=bool(rule.get("always_active")),
                    rule_name=match_value,
                )
        return RuleMatch(category="neutral", weight=default_weight, always_active=False, rule_name="")

    def _fetch_machine_row(self, machine_id: str) -> Optional[dict[str, Any]]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT machine_id, hostname, username, last_seen, idle_seconds, active_app, agent_health
                    FROM machines
                    WHERE tenant_id = %s AND machine_id = %s
                    """,
                    (_tid(), machine_id),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def _fetch_time_series(self, machine_id: str, start_dt: datetime, end_dt: datetime) -> dict[str, list[dict[str, Any]]]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT timestamp, app_name, process_name, window_title, duration_seconds
                    FROM app_activity
                    WHERE tenant_id = %s AND machine_id = %s AND timestamp >= %s AND timestamp < %s
                    ORDER BY timestamp ASC
                    """,
                    (_tid(), machine_id, start_dt, end_dt),
                )
                apps = [dict(row) for row in cur.fetchall()]
                cur.execute(
                    """
                    SELECT timestamp, browser, domain, url, title, duration_seconds
                    FROM browser_activity
                    WHERE tenant_id = %s AND machine_id = %s AND timestamp >= %s AND timestamp < %s
                    ORDER BY timestamp ASC
                    """,
                    (_tid(), machine_id, start_dt, end_dt),
                )
                browser = [dict(row) for row in cur.fetchall()]
                cur.execute(
                    """
                    SELECT timestamp, bucket_start, bucket_end, process_name, window_title,
                           key_event_count, mouse_click_count, mouse_scroll_count
                    FROM input_activity
                    WHERE tenant_id = %s AND machine_id = %s AND timestamp >= %s AND timestamp < %s
                    ORDER BY timestamp ASC
                    """,
                    (_tid(), machine_id, start_dt, end_dt),
                )
                inputs = [dict(row) for row in cur.fetchall()]
        return {"apps": apps, "browser": browser, "inputs": inputs}

    def _aggregate_machine(self, machine_id: str, start_date: str = "", end_date: str = "", *, compare_previous: bool = True) -> dict[str, Any]:
        machine = self._fetch_machine_row(machine_id)
        if not machine:
            return {}

        settings = db.get_settings()
        policy = self._normalize_policy(settings)
        start_dt, end_dt = _date_range_bounds(start_date, end_date)
        raw = self._fetch_time_series(machine_id, start_dt, end_dt)
        app_rows = raw["apps"]
        browser_rows = raw["browser"]
        input_rows = raw["inputs"]

        total_app_seconds = sum(_safe_int(row.get("duration_seconds")) for row in app_rows)
        input_active_seconds = 0
        for row in input_rows:
            duration = max(
                0,
                int(
                    (
                        datetime.fromisoformat(str(row.get("bucket_end"))).replace(tzinfo=timezone.utc)
                        - datetime.fromisoformat(str(row.get("bucket_start"))).replace(tzinfo=timezone.utc)
                    ).total_seconds()
                ) if row.get("bucket_start") and row.get("bucket_end") else 30
            )
            if _safe_int(row.get("key_event_count")) + _safe_int(row.get("mouse_click_count")) + _safe_int(row.get("mouse_scroll_count")) > 0:
                input_active_seconds += max(duration, 30)

        if input_active_seconds > 0:
            active_seconds = input_active_seconds
            idle_seconds = max(0, total_app_seconds - input_active_seconds)
        else:
            active_seconds = total_app_seconds
            idle_seconds = max(_safe_int(machine.get("idle_seconds")), int(total_app_seconds * 0.15))

        app_totals: dict[str, int] = defaultdict(int)
        domain_totals: dict[str, int] = defaultdict(int)
        category_seconds = {name: 0 for name in _CATEGORY_ORDER}
        meeting_like_active_seconds = 0
        browser_app_total = 0
        non_browser_total = 0

        for row in app_rows:
            duration = _safe_int(row.get("duration_seconds"))
            app_name = row.get("app_name") or row.get("process_name") or "Unknown"
            app_totals[app_name] += duration
            if _is_browser_app(str(row.get("app_name") or ""), str(row.get("process_name") or "")):
                browser_app_total += duration
                continue
            non_browser_total += duration
            match = self._match_rule(f"{row.get('app_name', '')} {row.get('process_name', '')}", policy["productivity_apps"])
            category_seconds[match.category] += duration
            if match.always_active:
                meeting_like_active_seconds += duration

        browser_classified_total = 0
        top_domains_by_category: dict[str, list[dict[str, Any]]] = {name: [] for name in _CATEGORY_ORDER}
        domain_buckets: dict[str, dict[str, Any]] = {}
        for row in browser_rows:
            duration = _safe_int(row.get("duration_seconds"))
            domain = _normalize_domain(str(row.get("domain") or row.get("url") or "unknown"))
            domain_totals[domain] += duration
            match = self._match_rule(domain, policy["productivity_domains"])
            browser_classified_total += duration
            category_seconds[match.category] += duration
            if match.always_active:
                meeting_like_active_seconds += duration
            bucket = domain_buckets.setdefault(domain, {"domain": domain, "total_seconds": 0, "category": match.category, "weight": match.weight})
            bucket["total_seconds"] += duration

        residual_browser_seconds = max(0, browser_app_total - browser_classified_total)
        category_seconds["neutral"] += residual_browser_seconds

        digital_seconds = non_browser_total + browser_app_total
        observed_seconds = max(digital_seconds, active_seconds + idle_seconds, 1)
        classified_seconds = sum(category_seconds.values())
        weights = policy["productivity_categories"]
        weighted_seconds = sum(category_seconds[name] * float(weights.get(name, 0)) for name in _CATEGORY_ORDER)
        weighted_ratio = weighted_seconds / max(digital_seconds, 1)
        idle_penalty = max(0.0, (idle_seconds - meeting_like_active_seconds * 0.5) / max(observed_seconds, 1))
        idle_penalty = min(0.35, idle_penalty)
        score = int(round(_clamp((weighted_ratio * 100) * (1 - idle_penalty), 0, 100)))

        context_switch_count = max(0, len(app_rows) - 1)
        focus_blocks = []
        current_block: Optional[dict[str, Any]] = None
        for row in app_rows:
            duration = _safe_int(row.get("duration_seconds"))
            app_name = row.get("app_name") or row.get("process_name") or "Unknown"
            if _is_browser_app(str(row.get("app_name") or ""), str(row.get("process_name") or "")):
                match = RuleMatch(category="supportive", weight=0.72, always_active=False, rule_name="browser")
            else:
                match = self._match_rule(f"{row.get('app_name', '')} {row.get('process_name', '')}", policy["productivity_apps"])
            if match.category in {"productive", "supportive"}:
                if current_block and current_block["category"] == match.category:
                    current_block["seconds"] += duration
                else:
                    if current_block:
                        focus_blocks.append(current_block)
                    current_block = {"category": match.category, "seconds": duration, "label": app_name}
            else:
                if current_block:
                    focus_blocks.append(current_block)
                    current_block = None
        if current_block:
            focus_blocks.append(current_block)
        focus_blocks = [block for block in focus_blocks if block["seconds"] >= 900]
        focus_time_seconds = sum(block["seconds"] for block in focus_blocks)

        distracting_share = category_seconds["distracting"] / max(digital_seconds, 1)
        neutral_share = category_seconds["neutral"] / max(classified_seconds or digital_seconds, 1)
        focus_ratio = focus_time_seconds / max(active_seconds, 1)
        switch_rate = context_switch_count / max(active_seconds / 3600, 1)
        workload_intensity_score = int(round(_clamp(((active_seconds / max(observed_seconds, 1)) * 55) + (focus_ratio * 25) + min(20, switch_rate), 0, 100)))

        confidence = 30
        if digital_seconds > 0:
            confidence += 20
        if browser_rows or browser_app_total == 0 or policy["track_browser"]:
            confidence += 15
        if input_active_seconds > 0:
            confidence += 20
        elif not policy["track_input_activity"]:
            confidence -= 10
        confidence += int(round((1 - min(0.7, neutral_share)) * 15))
        if observed_seconds < 1800:
            confidence -= 15
        if browser_app_total > 0 and not browser_rows:
            confidence -= 10
        confidence = int(_clamp(confidence, 5, 100))

        top_apps = []
        app_category_totals: dict[str, int] = defaultdict(int)
        for app_name, seconds in sorted(app_totals.items(), key=lambda item: item[1], reverse=True)[:12]:
            match = self._match_rule(app_name, policy["productivity_apps"])
            if _is_browser_app(app_name, app_name):
                category = "supportive" if browser_rows else "neutral"
            else:
                category = match.category
            top_apps.append({"app_name": app_name, "total_seconds": seconds, "category": category})
            app_category_totals[category] += seconds

        top_domains = []
        for item in sorted(domain_buckets.values(), key=lambda row: row["total_seconds"], reverse=True)[:12]:
            top_domains.append(item)
            top_domains_by_category[item["category"]].append(item)

        hourly = {hour: {"hour": f"{hour:02d}", "total_seconds": 0, "productive": 0, "supportive": 0, "distracting": 0, "neutral": 0} for hour in range(24)}
        for row in app_rows:
            ts = row.get("timestamp")
            if not ts:
                continue
            hour = datetime.fromisoformat(str(ts)).replace(tzinfo=timezone.utc).hour
            duration = _safe_int(row.get("duration_seconds"))
            hourly[hour]["total_seconds"] += duration
            match = self._match_rule(f"{row.get('app_name', '')} {row.get('process_name', '')}", policy["productivity_apps"])
            hourly[hour][match.category] += duration

        findings = []
        if focus_time_seconds >= 1800:
            findings.append({
                "type": "focus_finding",
                "level": "positive",
                "title": "Strong focus blocks detected",
                "description": f"{_fmt_duration(focus_time_seconds)} of sustained productive or supportive work was detected in this window.",
                "metric": focus_time_seconds,
            })
        if distracting_share >= 0.2 or switch_rate >= 18:
            findings.append({
                "type": "distraction_finding",
                "level": "warning",
                "title": "Distraction pressure is elevated",
                "description": f"Distracting activity accounts for {int(round(distracting_share * 100))}% of digital time with {context_switch_count} app switches.",
                "metric": int(round(distracting_share * 100)),
            })
        if workload_intensity_score >= 75 and focus_ratio < 0.35:
            findings.append({
                "type": "workload_finding",
                "level": "warning",
                "title": "Workload intensity is high",
                "description": "Sustained active time with low focus concentration suggests overload or fragmented work.",
                "metric": workload_intensity_score,
            })
        if neutral_share >= 0.4 or confidence < 60:
            findings.append({
                "type": "classification_gap_finding",
                "level": "info",
                "title": "Rule coverage is still incomplete",
                "description": f"{int(round(neutral_share * 100))}% of classified time is still neutral, so the score confidence is reduced.",
                "metric": confidence,
            })

        trend = {"direction": "flat", "score_delta": 0, "focus_delta_seconds": 0, "active_delta_seconds": 0}
        if compare_previous:
            window_days = max(1, int((end_dt - start_dt).total_seconds() // 86400) or 1)
            prev_end = start_dt
            prev_start = prev_end - timedelta(days=window_days)
            previous = self._aggregate_machine(machine_id, prev_start.date().isoformat(), (prev_end - timedelta(days=1)).date().isoformat(), compare_previous=False)
            if previous:
                prev_score = _safe_int(previous.get("summary", {}).get("productivity_score"))
                prev_focus = _safe_int(previous.get("score_components", {}).get("focus_time_seconds"))
                prev_active = _safe_int(previous.get("summary", {}).get("active_time_seconds"))
                score_delta = score - prev_score
                focus_delta = focus_time_seconds - prev_focus
                active_delta = active_seconds - prev_active
                if score_delta > 4:
                    direction = "up"
                elif score_delta < -4:
                    direction = "down"
                else:
                    direction = "flat"
                trend = {
                    "direction": direction,
                    "score_delta": score_delta,
                    "focus_delta_seconds": focus_delta,
                    "active_delta_seconds": active_delta,
                    "previous_score": prev_score,
                }
                if score_delta != 0 or focus_delta != 0:
                    findings.append({
                        "type": "trend_finding",
                        "level": "positive" if score_delta > 0 else "warning" if score_delta < 0 else "info",
                        "title": "Productivity trend changed",
                        "description": f"Score moved by {score_delta:+d} points compared with the previous matching window.",
                        "metric": score_delta,
                    })

        classification_breakdown = []
        for name in _CATEGORY_ORDER:
            seconds = category_seconds[name]
            classification_breakdown.append({
                "category": name,
                "seconds": seconds,
                "share": round(seconds / max(classified_seconds or digital_seconds, 1), 4),
            })

        summary = {
            "machine_id": machine_id,
            "hostname": machine.get("hostname", ""),
            "username": machine.get("username", ""),
            "last_seen": machine.get("last_seen"),
            "productivity_score": score,
            "active_time_seconds": active_seconds,
            "idle_time_seconds": idle_seconds,
            "focus_time_seconds": focus_time_seconds,
            "distracting_time_seconds": category_seconds["distracting"],
            "workload_intensity_score": workload_intensity_score,
            "score_confidence": confidence,
        }

        return {
            "summary": summary,
            "score_components": {
                "productive_time_seconds": category_seconds["productive"],
                "supportive_time_seconds": category_seconds["supportive"],
                "neutral_time_seconds": category_seconds["neutral"],
                "distracting_time_seconds": category_seconds["distracting"],
                "idle_time_seconds": idle_seconds,
                "active_time_seconds": active_seconds,
                "meeting_like_active_seconds": meeting_like_active_seconds,
                "focus_time_seconds": focus_time_seconds,
                "context_switch_count": context_switch_count,
                "workload_intensity_score": workload_intensity_score,
                "productivity_score": score,
                "score_confidence": confidence,
            },
            "findings": findings,
            "trend": trend,
            "top_apps": top_apps,
            "top_domains": top_domains,
            "classification_breakdown": classification_breakdown,
            "hourly_distribution": list(hourly.values()),
            "focus_blocks": focus_blocks[:6],
            "meta": {
                "window_seconds": int((end_dt - start_dt).total_seconds()),
                "policy_version": policy["productivity_policy_version"],
                "score_confidence": confidence,
                "track_input_activity": policy["track_input_activity"],
                "track_browser": policy["track_browser"],
                "input_coverage_seconds": input_active_seconds,
                "browser_coverage_seconds": browser_classified_total,
                "neutral_share": round(neutral_share, 4),
            },
            "timeline": [
                {"type": "active", "label": "Active input-backed work", "seconds": active_seconds},
                {"type": "idle", "label": "Estimated idle time", "seconds": idle_seconds},
                {"type": "focus", "label": "Focused work blocks", "seconds": focus_time_seconds},
            ],
        }

    def get_machine_productivity(self, machine_id: str, start_date: str = "", end_date: str = "") -> dict[str, Any]:
        return self._aggregate_machine(machine_id, start_date, end_date, compare_previous=True)

    def get_machine_productivity_alias(self, machine_id: str, start_date: str = "", end_date: str = "") -> dict[str, Any]:
        payload = self.get_machine_productivity(machine_id, start_date, end_date)
        if not payload:
            return {}
        components = payload["score_components"]
        summary = payload["summary"]
        return {
            "score": summary["productivity_score"],
            "total_active_seconds": summary["active_time_seconds"],
            "productive_seconds": components["productive_time_seconds"],
            "unproductive_browser_seconds": components["distracting_time_seconds"],
            "productive_browser_seconds": components["supportive_time_seconds"],
            "idle_ratio": round(summary["idle_time_seconds"] / max(summary["active_time_seconds"] + summary["idle_time_seconds"], 1), 4),
            **payload,
        }

    def list_productivity_machines(self, start_date: str = "", end_date: str = "", *, sort_by: str = "score", limit: int = 100) -> dict[str, Any]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT machine_id, hostname, username, last_seen,
                           (last_seen >= NOW() - INTERVAL '15 minutes') AS online
                    FROM machines
                    WHERE tenant_id = %s
                    ORDER BY last_seen DESC NULLS LAST
                    LIMIT %s
                    """,
                    (_tid(), limit),
                )
                rows = [dict(row) for row in cur.fetchall()]

        machine_rows = []
        for row in rows:
            metrics = self.get_machine_productivity(row["machine_id"], start_date, end_date)
            if not metrics:
                continue
            summary = metrics["summary"]
            row_payload = {
                **row,
                "summary": summary,
                "productivity_score": summary["productivity_score"],
                "score_confidence": summary["score_confidence"],
                "active_time_seconds": summary["active_time_seconds"],
                "focus_time_seconds": summary["focus_time_seconds"],
                "distracting_time_seconds": summary["distracting_time_seconds"],
                "workload_intensity_score": summary["workload_intensity_score"],
                "findings": metrics["findings"][:3],
                "classification_breakdown": metrics["classification_breakdown"],
            }
            machine_rows.append(row_payload)

        if sort_by == "focus":
            machine_rows.sort(key=lambda row: row.get("focus_time_seconds", 0), reverse=True)
        elif sort_by == "workload":
            machine_rows.sort(key=lambda row: row.get("workload_intensity_score", 0), reverse=True)
        else:
            machine_rows.sort(key=lambda row: row.get("productivity_score", 0), reverse=True)
        return {"items": machine_rows, "next_cursor": None}

    def get_productivity_overview(self, start_date: str = "", end_date: str = "") -> dict[str, Any]:
        machine_rows = self.list_productivity_machines(start_date, end_date, limit=500)["items"]
        if not machine_rows:
            return {
                "summary": {
                    "machine_count": 0,
                    "avg_score": 0,
                    "focus_time_seconds": 0,
                    "distracting_share": 0,
                    "workload_risk_count": 0,
                    "low_confidence_count": 0,
                },
                "trend": {"direction": "flat", "score_delta": 0},
                "score_distribution": [],
                "top_focus_drivers": [],
                "top_distraction_drivers": [],
                "findings": [],
                "machines": [],
            }

        avg_score = round(sum(row["productivity_score"] for row in machine_rows) / max(len(machine_rows), 1))
        total_focus_seconds = sum(row["focus_time_seconds"] for row in machine_rows)
        total_distracting_seconds = sum(row["distracting_time_seconds"] for row in machine_rows)
        total_active_seconds = sum(row["active_time_seconds"] for row in machine_rows)
        workload_risk_count = sum(1 for row in machine_rows if row["workload_intensity_score"] >= 75)
        low_confidence_count = sum(1 for row in machine_rows if row["score_confidence"] < 60)
        score_distribution = [
            {"band": "80-100", "count": sum(1 for row in machine_rows if row["productivity_score"] >= 80)},
            {"band": "60-79", "count": sum(1 for row in machine_rows if 60 <= row["productivity_score"] < 80)},
            {"band": "40-59", "count": sum(1 for row in machine_rows if 40 <= row["productivity_score"] < 60)},
            {"band": "0-39", "count": sum(1 for row in machine_rows if row["productivity_score"] < 40)},
        ]

        focus_driver_map: dict[str, int] = defaultdict(int)
        distraction_driver_map: dict[str, int] = defaultdict(int)
        findings = []
        for row in machine_rows:
            for finding in row.get("findings", []):
                findings.append({**finding, "machine_id": row["machine_id"], "hostname": row.get("hostname")})
            metrics = self.get_machine_productivity(row["machine_id"], start_date, end_date)
            for app in metrics.get("top_apps", []):
                if app.get("category") in {"productive", "supportive"}:
                    focus_driver_map[app["app_name"]] += app["total_seconds"]
            for domain in metrics.get("top_domains", []):
                if domain.get("category") == "distracting":
                    distraction_driver_map[domain["domain"]] += domain["total_seconds"]

        trend = {"direction": "flat", "score_delta": 0}
        start_dt, end_dt = _date_range_bounds(start_date, end_date)
        window_days = max(1, int((end_dt - start_dt).total_seconds() // 86400) or 1)
        prev_end = start_dt
        prev_start = prev_end - timedelta(days=window_days)
        previous = self.list_productivity_machines(prev_start.date().isoformat(), (prev_end - timedelta(days=1)).date().isoformat(), limit=500)["items"]
        if previous:
            prev_avg = round(sum(row["productivity_score"] for row in previous) / max(len(previous), 1))
            delta = avg_score - prev_avg
            trend = {"direction": "up" if delta > 4 else "down" if delta < -4 else "flat", "score_delta": delta, "previous_avg_score": prev_avg}

        return {
            "summary": {
                "machine_count": len(machine_rows),
                "avg_score": avg_score,
                "focus_time_seconds": total_focus_seconds,
                "distracting_share": round(total_distracting_seconds / max(total_active_seconds, 1), 4),
                "workload_risk_count": workload_risk_count,
                "low_confidence_count": low_confidence_count,
                "active_time_seconds": total_active_seconds,
            },
            "trend": trend,
            "score_distribution": score_distribution,
            "top_focus_drivers": [{"name": name, "seconds": seconds} for name, seconds in sorted(focus_driver_map.items(), key=lambda item: item[1], reverse=True)[:8]],
            "top_distraction_drivers": [{"name": name, "seconds": seconds} for name, seconds in sorted(distraction_driver_map.items(), key=lambda item: item[1], reverse=True)[:8]],
            "findings": findings[:15],
            "machines": machine_rows,
        }

    def get_team_productivity(self, team_id: str, start_date: str = "", end_date: str = "", trend_days: int = 7) -> dict[str, Any]:
        team = db.get_team(team_id)
        if not team:
            return {}
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT tm.machine_id
                    FROM team_memberships tm
                    JOIN teams t ON t.id = tm.team_id
                    WHERE tm.team_id = %s AND t.tenant_id = %s
                    ORDER BY tm.machine_id
                    """,
                    (team_id, _tid()),
                )
                machine_ids = [row["machine_id"] for row in cur.fetchall()]

        machine_rows = []
        for machine_id in machine_ids:
            metrics = self.get_machine_productivity(machine_id, start_date, end_date)
            if metrics:
                machine_rows.append(metrics)

        if not machine_rows:
            return {"team": team, "machines": [], "summary": {"avg_score": 0, "machine_count": 0}}

        avg_score = round(sum(row["summary"]["productivity_score"] for row in machine_rows) / max(len(machine_rows), 1))
        total_active = sum(row["summary"]["active_time_seconds"] for row in machine_rows)
        active_now = 0
        aggregated_apps: dict[str, int] = defaultdict(int)
        low_productivity = []
        findings = []
        for item in machine_rows:
            summary = item["summary"]
            if summary.get("last_seen") and summary["last_seen"] >= _utcnow() - timedelta(minutes=15):
                active_now += 1
            for app in item.get("top_apps", []):
                aggregated_apps[app["app_name"]] += app["total_seconds"]
            if summary["productivity_score"] < 40:
                low_productivity.append({
                    "machine_id": summary["machine_id"],
                    "hostname": summary["hostname"],
                    "username": summary["username"],
                    "productivity_score": summary["productivity_score"],
                })
            findings.extend([{**f, "machine_id": summary["machine_id"], "hostname": summary["hostname"]} for f in item.get("findings", [])])

        today = _utcnow().date()
        team_trends = []
        for offset in range(max(1, min(trend_days, 30))):
            day = today - timedelta(days=max(0, trend_days - offset - 1))
            day_scores = [self.get_machine_productivity(mid, day.isoformat(), day.isoformat()) for mid in machine_ids]
            valid_scores = [entry["summary"]["productivity_score"] for entry in day_scores if entry]
            team_trends.append({
                "date": day.isoformat(),
                "avg_productivity": round(sum(valid_scores) / max(len(valid_scores), 1)) if valid_scores else 0,
                "total_active_time_seconds": sum(entry.get("summary", {}).get("active_time_seconds", 0) for entry in day_scores if entry),
            })

        return {
            "team": team,
            "summary": {
                "avg_score": avg_score,
                "machine_count": len(machine_rows),
                "active_now": active_now,
                "total_active_time_seconds": total_active,
            },
            "machines": machine_rows,
            "avg_productivity": avg_score,
            "total_machines": len(machine_rows),
            "active_machines": active_now,
            "total_active_time_seconds": total_active,
            "aggregated_app_usage": [{"app_name": name, "total_seconds": seconds} for name, seconds in sorted(aggregated_apps.items(), key=lambda item: item[1], reverse=True)[:8]],
            "low_productivity_machines": low_productivity[:8],
            "team_trends": team_trends,
            "findings": findings[:15],
        }

    def get_productivity_logs(self, machine_id: str = "", date: str = "", limit: int = 200) -> list[dict[str, Any]]:
        start_date = date or ""
        end_date = date or ""
        if machine_id:
            rows = [self.get_machine_productivity(machine_id, start_date, end_date)]
        else:
            rows = [self.get_machine_productivity(item["machine_id"], start_date, end_date) for item in self.list_productivity_machines(start_date, end_date, limit=limit)["items"]]
        results = []
        for item in rows:
            if not item:
                continue
            summary = item["summary"]
            results.append({
                "date": date or _iso_day(_utcnow()),
                "machine_id": summary["machine_id"],
                "hostname": summary["hostname"],
                "username": summary["username"],
                "active_time_seconds": summary["active_time_seconds"],
                "focus_time_seconds": summary["focus_time_seconds"],
                "score": summary["productivity_score"],
                "score_confidence": summary["score_confidence"],
                "major_driver": (item.get("findings") or [{}])[0].get("title", "Stable productivity mix"),
                "category": (item.get("findings") or [{}])[0].get("type", ""),
                "unique_apps": len(item.get("top_apps") or []),
            })
        return results[:limit]


productivity_service = ProductivityService()
