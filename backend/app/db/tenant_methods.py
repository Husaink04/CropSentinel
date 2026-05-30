"""Tenant-scoped DB methods extracted from the legacy Database class."""

from typing import List, Optional

from app.db.core import Connection as _Conn, get_tenant_id as _tid


class TenantMethodsMixin:
    @staticmethod
    def _new_enrollment_token() -> str:
        import secrets as _sec

        return f"cpet_{_sec.token_urlsafe(24)}"

    def create_tenant(
        self,
        slug: str,
        name: str = "",
        customer_name: str = "",
        tier: str = "starter",
        max_seats: int = 0,
        valid_days: Optional[int] = None,
        grace_days: int = 14,
    ) -> int:
        token = self._new_enrollment_token()
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tenants (
                        slug, name, status, enrollment_token,
                        customer_name, tier, max_seats,
                        valid_until, grace_days,
                        subscription_started
                    )
                    VALUES (
                        %s, %s, 'active', %s,
                        %s, %s, %s,
                        CASE WHEN %s::int IS NULL THEN NULL
                             ELSE NOW() + (%s::int || ' days')::interval END,
                        %s,
                        NOW()
                    )
                    RETURNING id
                    """,
                    (
                        slug,
                        name or slug,
                        token,
                        customer_name or (name or slug),
                        tier,
                        int(max_seats or 0),
                        valid_days,
                        valid_days,
                        int(grace_days or 14),
                    ),
                )
                return int(cur.fetchone()["id"])

    def rotate_enrollment_token(self, tenant_id: int) -> Optional[str]:
        token = self._new_enrollment_token()
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE tenants SET enrollment_token = %s, updated_at = NOW() "
                    "WHERE id = %s RETURNING enrollment_token",
                    (token, tenant_id),
                )
                row = cur.fetchone()
                return row["enrollment_token"] if row else None

    def get_tenant(self, tenant_id: int) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM tenants WHERE id = %s", (tenant_id,))
                r = cur.fetchone()
                return dict(r) if r else None

    def get_tenant_by_slug(self, slug: str) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM tenants WHERE slug = %s", (slug,))
                r = cur.fetchone()
                return dict(r) if r else None

    def get_tenant_by_enrollment_token(self, token: str) -> Optional[dict]:
        if not token:
            return None
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM tenants WHERE enrollment_token = %s AND status = 'active'",
                    (token,),
                )
                r = cur.fetchone()
                return dict(r) if r else None

    def get_all_tenants(self) -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM tenants ORDER BY id")
                return [dict(r) for r in cur.fetchall()]

    def count_tenants(self) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM tenants WHERE status = 'active'")
                return int(cur.fetchone()["c"])

    def update_tenant(
        self,
        tenant_id: int,
        name: Optional[str] = None,
        status: Optional[str] = None,
        customer_name: Optional[str] = None,
        tier: Optional[str] = None,
        max_seats: Optional[int] = None,
        grace_days: Optional[int] = None,
        extend_days: Optional[int] = None,
        valid_until: Optional[str] = None,
    ) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                sets, params = [], []
                if name is not None:
                    sets.append("name = %s")
                    params.append(name)
                if status is not None:
                    sets.append("status = %s")
                    params.append(status)
                if customer_name is not None:
                    sets.append("customer_name = %s")
                    params.append(customer_name)
                if tier is not None:
                    sets.append("tier = %s")
                    params.append(tier)
                if max_seats is not None:
                    sets.append("max_seats = %s")
                    params.append(int(max_seats))
                if grace_days is not None:
                    sets.append("grace_days = %s")
                    params.append(int(grace_days))
                if valid_until is not None:
                    sets.append("valid_until = %s")
                    params.append(valid_until)
                if extend_days is not None and extend_days > 0:
                    sets.append(
                        "valid_until = COALESCE(valid_until, NOW()) + (%s || ' days')::interval"
                    )
                    params.append(int(extend_days))
                if not sets:
                    return self.get_tenant(tenant_id)
                sets.append("updated_at = NOW()")
                params.append(tenant_id)
                cur.execute(
                    f"UPDATE tenants SET {', '.join(sets)} WHERE id = %s RETURNING *",
                    params,
                )
                r = cur.fetchone()
                return dict(r) if r else None

    def count_tenant_machines(self, tenant_id: int) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS c FROM machines WHERE tenant_id = %s",
                    (tenant_id,),
                )
                return int(cur.fetchone()["c"])

    def get_tenant_license_info(self, tenant_id: int) -> Optional[dict]:
        t = self.get_tenant(tenant_id)
        if not t:
            return None
        seats_used = self.count_tenant_machines(tenant_id)
        max_seats = int(t.get("max_seats") or 0)
        valid_until = t.get("valid_until")
        grace_days = int(t.get("grace_days") or 14)

        is_expired = False
        is_in_grace = False
        is_past_grace = False
        days_remaining = None
        grace_days_remaining = None

        if valid_until is not None:
            from datetime import datetime, timedelta, timezone

            now = datetime.now(timezone.utc)
            vu = valid_until
            if isinstance(vu, str):
                vu = datetime.fromisoformat(vu.replace("Z", "+00:00"))
            days_remaining = int((vu - now).total_seconds() // 86400)
            if now > vu:
                is_expired = True
                grace_end = vu + timedelta(days=grace_days)
                if now <= grace_end:
                    is_in_grace = True
                    grace_days_remaining = int((grace_end - now).total_seconds() // 86400)
                else:
                    is_past_grace = True

        if t.get("status") == "suspended":
            status_label = "Suspended"
        elif is_past_grace:
            status_label = "Expired (past grace)"
        elif is_in_grace:
            status_label = f"In grace period ({grace_days_remaining}d left)"
        elif is_expired:
            status_label = "Expired"
        elif valid_until is None:
            status_label = "Perpetual"
        else:
            status_label = f"Active ({days_remaining}d remaining)"

        return {
            "tenant_id": tenant_id,
            "name": t.get("name", ""),
            "customer_name": t.get("customer_name", "") or t.get("name", ""),
            "tier": t.get("tier", "starter"),
            "max_seats": max_seats,
            "seats_used": seats_used,
            "seats_remaining": (max_seats - seats_used) if max_seats > 0 else None,
            "valid_until": valid_until.isoformat() if valid_until and not isinstance(valid_until, str) else valid_until,
            "grace_days": grace_days,
            "subscription_started": (
                t.get("subscription_started").isoformat()
                if t.get("subscription_started") and not isinstance(t.get("subscription_started"), str)
                else t.get("subscription_started")
            ),
            "is_expired": is_expired,
            "is_in_grace": is_in_grace,
            "is_past_grace": is_past_grace,
            "days_remaining": days_remaining,
            "grace_days_remaining": grace_days_remaining,
            "status": t.get("status", "active"),
            "status_label": status_label,
        }

    def delete_tenant(self, tenant_id: int) -> None:
        if tenant_id == 1:
            raise ValueError("Cannot delete the default tenant (id=1).")
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))

    def get_tenant_stats(self, tenant_id: int) -> dict:
        with _Conn() as conn:
            with conn.cursor() as cur:
                stats = {}
                for table, label in [
                    ("machines", "machines"),
                    ("users", "users"),
                    ("screenshots", "screenshots"),
                    ("alert_rules", "alert_rules"),
                    ("dlp_events", "dlp_events"),
                ]:
                    cur.execute(
                        f"SELECT COUNT(*) AS c FROM {table} WHERE tenant_id = %s",
                        (tenant_id,),
                    )
                    stats[label] = cur.fetchone()["c"]
                return stats

    def get_all_tenants_with_stats(self) -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.*,
                           COALESCE(mc.cnt, 0) AS machine_count,
                           COALESCE(uc.cnt, 0) AS user_count
                    FROM tenants t
                    LEFT JOIN (SELECT tenant_id, COUNT(*) AS cnt FROM machines GROUP BY tenant_id) mc
                        ON mc.tenant_id = t.id
                    LEFT JOIN (SELECT tenant_id, COUNT(*) AS cnt FROM users GROUP BY tenant_id) uc
                        ON uc.tenant_id = t.id
                    ORDER BY t.id
                    """
                )
                return [dict(r) for r in cur.fetchall()]
