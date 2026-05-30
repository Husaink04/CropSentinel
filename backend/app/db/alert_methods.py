"""Extracted DB methods mixin."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from app.db.core import (
    Connection as _Conn,
    get_tenant_id as _tid,
    tz_safe as _tz_safe,
    utcnow,
    utcnow_iso,
)

logger = logging.getLogger("croppro.db")

class AlertMethodsMixin:

    # ALERT RULES â€” full CRUD
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_alert_rules(self) -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM alert_rules WHERE tenant_id = %s ORDER BY created_at DESC",
                    (_tid(),),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_alert_rule(self, rule_id: int) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM alert_rules WHERE id = %s AND tenant_id = %s",
                    (rule_id, _tid()),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def create_alert_rule(self, data: dict) -> int:
        now = utcnow()
        tid = _tid()
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO alert_rules
                        (tenant_id, name, description, rule_type, condition,
                         threshold, machine_id, severity, enabled,
                         created_at, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                """, (
                    tid,
                    data["name"],
                    data.get("description", ""),
                    data["rule_type"],
                    data["condition"],
                    data.get("threshold", ""),
                    data.get("machine_id", "all"),
                    data.get("severity", "medium"),
                    bool(data.get("enabled", True)),
                    now, now,
                ))
                return cur.fetchone()["id"]

    def update_alert_rule(self, rule_id: int, data: dict) -> bool:
        ALLOWED = {
            "name", "description", "rule_type", "condition",
            "threshold", "machine_id", "severity", "enabled",
        }
        data = {k: v for k, v in data.items() if k in ALLOWED}
        if "enabled" in data:
            data["enabled"] = bool(data["enabled"])
        if not data:
            return False
        sets = ", ".join(f"{k} = %s" for k in data)
        vals = list(data.values()) + [utcnow(), rule_id, _tid()]
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE alert_rules SET {sets}, updated_at = %s "
                    f"WHERE id = %s AND tenant_id = %s",
                    vals,
                )
                return cur.rowcount > 0

    def delete_alert_rule(self, rule_id: int) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM alert_rules WHERE id = %s AND tenant_id = %s",
                    (rule_id, _tid()),
                )
                return cur.rowcount > 0

    def toggle_alert_rule(self, rule_id: int, enabled: bool) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE alert_rules SET enabled = %s, updated_at = %s "
                    "WHERE id = %s AND tenant_id = %s",
                    (enabled, utcnow(), rule_id, _tid()),
                )
                return cur.rowcount > 0

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # ALERT LOGS â€” create / read / update (acknowledge) / delete
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_alert_logs(self, machine_id: str = "", severity: str = "",
                        acknowledged: Optional[bool] = None,
                        limit: int = 100) -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                parts: list  = ["tenant_id = %s"]
                params: list = [_tid()]
                if machine_id:
                    parts.append("machine_id = %s"); params.append(machine_id)
                if severity:
                    parts.append("severity = %s");   params.append(severity)
                if acknowledged is not None:
                    parts.append("acknowledged = %s"); params.append(acknowledged)
                where = ("WHERE " + " AND ".join(parts)) if parts else ""
                cur.execute(
                    f"SELECT * FROM alert_logs {where} "
                    f"ORDER BY triggered_at DESC LIMIT %s",
                    params + [limit]
                )
                return [dict(r) for r in cur.fetchall()]

    def create_alert_log(self, data: dict) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO alert_logs
                        (tenant_id, rule_id, rule_name, machine_id, hostname,
                         severity, message, details, triggered_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                """, (
                    _tid(),
                    data.get("rule_id",   0),
                    data.get("rule_name", ""),
                    data.get("machine_id",""),
                    data.get("hostname",  ""),
                    data.get("severity",  "medium"),
                    data.get("message",   ""),
                    data.get("details",   ""),
                    data.get("triggered_at") or utcnow(),
                ))
                return cur.fetchone()["id"]

    def acknowledge_alert(self, log_id: int, by: str = "admin") -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE alert_logs
                    SET acknowledged    = TRUE,
                        acknowledged_at = %s,
                        acknowledged_by = %s
                    WHERE id = %s AND tenant_id = %s
                """, (utcnow(), by, log_id, _tid()))
                return cur.rowcount > 0

    def acknowledge_all_alerts(self, by: str = "admin") -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE alert_logs
                    SET acknowledged    = TRUE,
                        acknowledged_at = %s,
                        acknowledged_by = %s
                    WHERE acknowledged = FALSE AND tenant_id = %s
                """, (utcnow(), by, _tid()))
                return cur.rowcount

    def delete_alert_log(self, log_id: int) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM alert_logs WHERE id = %s AND tenant_id = %s",
                    (log_id, _tid()),
                )
                return cur.rowcount > 0

    def delete_alert_logs_for_machine(self, machine_id: str) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM alert_logs WHERE machine_id = %s AND tenant_id = %s",
                    (machine_id, _tid()),
                )
                return cur.rowcount

    def delete_acknowledged_alerts(self) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM alert_logs WHERE acknowledged = TRUE AND tenant_id = %s",
                    (_tid(),),
                )
                return cur.rowcount

    def get_alert_stats(self) -> dict:
        tid = _tid()
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM alert_logs WHERE tenant_id = %s", (tid,))
                total = cur.fetchone()["c"]
                cur.execute(
                    "SELECT COUNT(*) AS c FROM alert_logs "
                    "WHERE acknowledged = FALSE AND tenant_id = %s", (tid,),
                )
                unread = cur.fetchone()["c"]
                cur.execute(
                    "SELECT severity, COUNT(*) AS count FROM alert_logs "
                    "WHERE tenant_id = %s GROUP BY severity", (tid,),
                )
                by_severity = [dict(r) for r in cur.fetchall()]
                today = utcnow().date()
                cur.execute(
                    "SELECT COUNT(*) AS c FROM alert_logs "
                    "WHERE triggered_at::date = %s AND tenant_id = %s",
                    (today, tid),
                )
                today_count = cur.fetchone()["c"]
                cur.execute(
                    "SELECT * FROM alert_logs WHERE tenant_id = %s "
                    "ORDER BY triggered_at DESC LIMIT 5", (tid,),
                )
                recent = [dict(r) for r in cur.fetchall()]

        return {
            "total":       total,
            "unread":      unread,
            "today":       today_count,
            "by_severity": by_severity,
            "recent":      recent,
        }

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # ALERT ENGINE â€” evaluators (called on WS events)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    ALERT_COOLDOWN = 300   # 5 minutes between repeated fires of same rule+machine

    def _alert_in_cooldown(self, rule_id: int, machine_id: str) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT triggered_at FROM alert_logs
                    WHERE rule_id = %s AND machine_id = %s AND tenant_id = %s
                    ORDER BY triggered_at DESC LIMIT 1
                """, (rule_id, machine_id, _tid()))
                row = cur.fetchone()
        if not row:
            return False
        last = _tz_safe(row["triggered_at"])
        return (utcnow() - last).total_seconds() < self.ALERT_COOLDOWN

    def evaluate_alerts_for_heartbeat(self, machine_id: str,
                                       heartbeat: dict) -> List[dict]:
        rules    = self.get_alert_rules()
        machine  = self.get_machine(machine_id) or {}
        hostname = machine.get("hostname", machine_id)
        fired: List[dict] = []

        for rule in rules:
            if not rule.get("enabled"):
                continue
            if rule["machine_id"] not in ("all", machine_id):
                continue

            cond      = rule["condition"]
            thr       = rule.get("threshold", "")
            sev       = rule.get("severity",  "medium")
            triggered = False
            message   = ""

            try:
                if cond == "cpu_percent_gt":
                    val = float(heartbeat.get("cpu_percent", 0))
                    lim = float(thr or 85)
                    if val > lim:
                        triggered = True
                        message = f"CPU at {val:.1f}% (threshold {lim}%) on {hostname}"

                elif cond == "memory_percent_gt":
                    val = float(heartbeat.get("memory_percent", 0))
                    lim = float(thr or 90)
                    if val > lim:
                        triggered = True
                        message = f"Memory at {val:.1f}% (threshold {lim}%) on {hostname}"

                elif cond == "idle_seconds_gt":
                    val = int(heartbeat.get("idle_seconds", 0))
                    lim = int(thr or 1800)
                    if val > lim:
                        triggered = True
                        message = f"Machine {hostname} idle for {val // 60} min"

                elif cond == "outside_hours":
                    if thr and "-" in thr:
                        start_s, end_s = thr.split("-", 1)
                        now_time = utcnow().strftime("%H:%M")
                        if not (start_s <= now_time <= end_s):
                            triggered = True
                            message = f"Activity on {hostname} outside hours ({thr})"

            except Exception as exc:
                logger.debug(f"Alert eval error [{rule['name']}]: {exc}")
                continue

            if triggered and not self._alert_in_cooldown(rule["id"], machine_id):
                log_id = self.create_alert_log({
                    "rule_id":   rule["id"],
                    "rule_name": rule["name"],
                    "machine_id":machine_id,
                    "hostname":  hostname,
                    "severity":  sev,
                    "message":   message,
                    "details":   json.dumps({
                        k: v for k, v in heartbeat.items() if k != "type"
                    }, default=str),
                })
                fired.append({
                    "id":        log_id,
                    "rule_name": rule["name"],
                    "severity":  sev,
                    "message":   message,
                })

        return fired

    def evaluate_alerts_for_browser(self, machine_id: str,
                                     domain: str) -> List[dict]:
        rules     = self.get_alert_rules()
        machine   = self.get_machine(machine_id) or {}
        hostname  = machine.get("hostname", machine_id)
        settings  = self.get_settings()
        blacklist = settings.get("unproductive_domains", [])
        fired: List[dict] = []

        for rule in rules:
            if not rule.get("enabled"):
                continue
            if rule["machine_id"] not in ("all", machine_id):
                continue

            cond      = rule["condition"]
            thr       = rule.get("threshold", "")
            sev       = rule.get("severity",  "medium")
            triggered = False
            message   = ""

            try:
                if cond == "domain_in_blacklist":
                    effective_blacklist = []
                    if thr:
                        effective_blacklist = [item.strip().lower() for item in str(thr).split(",") if item.strip()]
                    if not effective_blacklist:
                        effective_blacklist = [str(item).strip().lower() for item in blacklist if str(item).strip()]
                    if any(bl in domain.lower() for bl in effective_blacklist):
                        triggered = True
                        message = f"{hostname} visited unproductive site: {domain}"

                elif cond == "domain_contains":
                    if thr and thr.lower() in domain.lower():
                        triggered = True
                        message = f"{hostname} visited domain matching '{thr}': {domain}"

            except Exception as exc:
                logger.debug(f"Browser alert eval error [{rule['name']}]: {exc}")
                continue

            if triggered and not self._alert_in_cooldown(rule["id"], machine_id):
                log_id = self.create_alert_log({
                    "rule_id":   rule["id"],
                    "rule_name": rule["name"],
                    "machine_id":machine_id,
                    "hostname":  hostname,
                    "severity":  sev,
                    "message":   message,
                    "details":   domain,
                })
                fired.append({
                    "id":        log_id,
                    "rule_name": rule["name"],
                    "severity":  sev,
                    "message":   message,
                })

        return fired

    def evaluate_alerts_for_offline(self, machine_id: str) -> List[dict]:
        rules    = self.get_alert_rules()
        machine  = self.get_machine(machine_id) or {}
        hostname = machine.get("hostname", machine_id)
        fired: List[dict] = []

        for rule in rules:
            if not rule.get("enabled"):
                continue
            if rule["machine_id"] not in ("all", machine_id):
                continue
            if rule["condition"] != "machine_offline":
                continue
            if self._alert_in_cooldown(rule["id"], machine_id):
                logger.debug(f"Offline alert [{rule['name']}] suppressed â€” cooldown active")
                continue

            log_id = self.create_alert_log({
                "rule_id":   rule["id"],
                "rule_name": rule["name"],
                "machine_id":machine_id,
                "hostname":  hostname,
                "severity":  rule.get("severity", "high"),
                "message":   f"Machine {hostname} went offline",
                "details":   "",
            })
            fired.append({
                "id":        log_id,
                "rule_name": rule["name"],
                "severity":  rule.get("severity", "high"),
                "message":   f"Machine {hostname} went offline",
            })

        return fired

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
