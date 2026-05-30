"""Team management and team productivity DB methods."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4

from app.db.core import Connection as _Conn, get_tenant_id as _tid


def _date_range_bounds(start_date: str = "", end_date: str = "") -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
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


class TeamMethodsMixin:
    def create_team(self, name: str, description: str = "") -> dict:
        team_id = str(uuid4())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO teams (id, tenant_id, name, description)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, tenant_id, name, description, created_at
                    """,
                    (team_id, _tid(), name.strip(), description.strip()),
                )
                return dict(cur.fetchone())

    def get_teams(self, search: str = "", limit: int = 50, offset: int = 0) -> dict:
        where = ["t.tenant_id = %s"]
        params: list = [_tid()]
        if search:
            where.append("LOWER(t.name) LIKE %s")
            params.append(f"%{search.lower()}%")
        where_clause = " AND ".join(where)
        lim = max(1, min(int(limit or 50), 200))
        off = max(0, int(offset or 0))

        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS c
                    FROM teams t
                    WHERE {where_clause}
                    """,
                    params,
                )
                total = int(cur.fetchone()["c"])

                cur.execute(
                    f"""
                    SELECT
                        t.id,
                        t.tenant_id,
                        t.name,
                        t.description,
                        t.created_at,
                        COUNT(tm.machine_id) AS machine_count,
                        COUNT(tm.machine_id) FILTER (
                            WHERE m.last_seen >= NOW() - INTERVAL '15 minutes'
                        ) AS active_now
                    FROM teams t
                    LEFT JOIN team_memberships tm ON tm.team_id = t.id
                    LEFT JOIN machines m
                      ON m.machine_id = tm.machine_id
                     AND m.tenant_id = t.tenant_id
                    WHERE {where_clause}
                    GROUP BY t.id
                    ORDER BY t.created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    params + [lim, off],
                )
                rows = [dict(r) for r in cur.fetchall()]
                return {"items": rows, "total": total, "limit": lim, "offset": off}

    def get_team(self, team_id: str) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, tenant_id, name, description, created_at
                    FROM teams
                    WHERE id = %s AND tenant_id = %s
                    """,
                    (team_id, _tid()),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def update_team(self, team_id: str, name: Optional[str] = None, description: Optional[str] = None) -> Optional[dict]:
        updates = []
        params: list = []
        if name is not None:
            updates.append("name = %s")
            params.append(name.strip())
        if description is not None:
            updates.append("description = %s")
            params.append(description.strip())
        if not updates:
            return self.get_team(team_id)

        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE teams
                    SET {", ".join(updates)}
                    WHERE id = %s AND tenant_id = %s
                    RETURNING id, tenant_id, name, description, created_at
                    """,
                    params + [team_id, _tid()],
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def delete_team(self, team_id: str) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM teams WHERE id = %s AND tenant_id = %s",
                    (team_id, _tid()),
                )
                return cur.rowcount > 0

    def add_machine_to_team(self, team_id: str, machine_id: str) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM teams WHERE id = %s AND tenant_id = %s",
                    (team_id, _tid()),
                )
                if not cur.fetchone():
                    return False
                cur.execute(
                    "SELECT 1 FROM machines WHERE machine_id = %s AND tenant_id = %s",
                    (machine_id, _tid()),
                )
                if not cur.fetchone():
                    return False
                cur.execute(
                    """
                    INSERT INTO team_memberships (team_id, machine_id)
                    VALUES (%s, %s)
                    ON CONFLICT (team_id, machine_id) DO NOTHING
                    """,
                    (team_id, machine_id),
                )
                return True

    def get_team_machines(
        self,
        team_id: str,
        search: str = "",
        status: str = "",
        limit: int = 50,
        offset: int = 0,
        start_date: str = "",
        end_date: str = "",
    ) -> dict:
        team = self.get_team(team_id)
        if not team:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

        clauses = [
            "t.id = %s",
            "t.tenant_id = %s",
        ]
        params: list = [team_id, _tid()]
        if search:
            clauses.append(
                "(LOWER(m.hostname) LIKE %s OR LOWER(m.username) LIKE %s OR LOWER(m.machine_id) LIKE %s)"
            )
            s = f"%{search.lower()}%"
            params.extend([s, s, s])
        if status == "online":
            clauses.append("m.last_seen >= NOW() - INTERVAL '15 minutes'")
        elif status == "offline":
            clauses.append("m.last_seen < NOW() - INTERVAL '15 minutes'")
        where_clause = " AND ".join(clauses)
        lim = max(1, min(int(limit or 50), 200))
        off = max(0, int(offset or 0))

        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS c
                    FROM teams t
                    JOIN team_memberships tm ON tm.team_id = t.id
                    JOIN machines m ON m.machine_id = tm.machine_id AND m.tenant_id = t.tenant_id
                    WHERE {where_clause}
                    """,
                    params,
                )
                total = int(cur.fetchone()["c"])

                cur.execute(
                    f"""
                    SELECT
                        m.machine_id,
                        m.hostname,
                        m.username,
                        m.last_seen,
                        (m.last_seen >= NOW() - INTERVAL '15 minutes') AS online
                    FROM teams t
                    JOIN team_memberships tm ON tm.team_id = t.id
                    JOIN machines m ON m.machine_id = tm.machine_id AND m.tenant_id = t.tenant_id
                    WHERE {where_clause}
                    ORDER BY m.last_seen DESC NULLS LAST
                    LIMIT %s OFFSET %s
                    """,
                    params + [lim, off],
                )
                rows = [dict(r) for r in cur.fetchall()]

        for row in rows:
            metrics = self.get_machine_productivity(
                row["machine_id"], start_date=start_date, end_date=end_date
            )
            row["productivity_score"] = metrics.get("productivity_score", 0)
            row["active_time_seconds"] = metrics.get("active_time_seconds", 0)
            row["idle_time_seconds"] = metrics.get("idle_time_seconds", 0)
        return {"items": rows, "total": total, "limit": lim, "offset": off}

    def remove_machine_from_team(self, team_id: str, machine_id: str) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM team_memberships tm
                    USING teams t
                    WHERE tm.team_id = t.id
                      AND tm.team_id = %s
                      AND tm.machine_id = %s
                      AND t.tenant_id = %s
                    """,
                    (team_id, machine_id, _tid()),
                )
                return cur.rowcount > 0

    def get_machine_productivity(self, machine_id: str, start_date: str = "", end_date: str = "") -> dict:
        from app.services.productivity_service import productivity_service

        payload = productivity_service.get_machine_productivity(machine_id, start_date, end_date)
        if not payload:
            return {}
        return {
            **payload,
            "machine_id": payload["summary"]["machine_id"],
            "hostname": payload["summary"]["hostname"],
            "username": payload["summary"]["username"],
            "last_seen": payload["summary"]["last_seen"],
            "active_time_seconds": payload["summary"]["active_time_seconds"],
            "idle_time_seconds": payload["summary"]["idle_time_seconds"],
            "productivity_score": payload["summary"]["productivity_score"],
            "productive_app_seconds": payload["score_components"]["productive_time_seconds"],
            "productive_browser_seconds": payload["score_components"]["supportive_time_seconds"],
            "unproductive_browser_seconds": payload["score_components"]["distracting_time_seconds"],
            "timeline": payload["timeline"],
        }

    def get_team_productivity(self, team_id: str, start_date: str = "", end_date: str = "", trend_days: int = 7) -> dict:
        from app.services.productivity_service import productivity_service

        return productivity_service.get_team_productivity(team_id, start_date, end_date, trend_days)
