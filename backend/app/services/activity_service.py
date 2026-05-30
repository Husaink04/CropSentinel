"""Shared activity query service for investigation pages."""

from __future__ import annotations

from typing import Optional

from database import db


def _load_productivity_lists() -> tuple[list[str], list[str], list[str]]:
    settings = db.get_settings()
    return (
        [app.lower() for app in settings.get("productive_apps", [])],
        settings.get("productive_domains", []),
        settings.get("unproductive_domains", []),
    )


def _classify_domain(domain: str, prod_domains: list[str], unprod_domains: list[str]) -> str:
    value = (domain or "").lower()
    if any(pd.lower() in value for pd in prod_domains):
        return "productive"
    if any(ud.lower() in value for ud in unprod_domains):
        return "unproductive"
    return "neutral"


def _classify_app(app_name: str, prod_apps: list[str]) -> str:
    value = (app_name or "").lower()
    if any(app in value for app in prod_apps):
        return "productive"
    return "neutral"


class ActivityService:
    def list_browser_logs(
        self,
        machine_id: str,
        *,
        search: str = "",
        date: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> dict:
        if not machine_id:
            return {"items": [], "total": 0, "stats": {"by_category": {}, "total_duration_seconds": 0}}

        rows = db.get_browser_history(machine_id, limit=limit, search=search, date=date, offset=offset)
        total = db.count_browser_history(machine_id, search=search, date=date)
        _, prod_domains, unprod_domains = _load_productivity_lists()

        by_category = {"productive": 0, "unproductive": 0, "neutral": 0}
        total_duration_seconds = 0
        for row in rows:
            category = _classify_domain(row.get("domain", ""), prod_domains, unprod_domains)
            row["category"] = category
            by_category[category] = by_category.get(category, 0) + 1
            total_duration_seconds += int(row.get("duration_seconds") or 0)

        return {
            "items": rows,
            "total": total,
            "stats": {
                "by_category": by_category,
                "total_duration_seconds": total_duration_seconds,
            },
        }

    def list_app_usage(
        self,
        machine_id: str,
        *,
        search: str = "",
        date: Optional[str] = None,
        category: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        if not machine_id:
            return {"items": [], "total": 0, "stats": {"total_seconds": 0, "by_category": {}}}

        rows = db.get_app_usage(machine_id, date=date, search=search, limit=limit, offset=offset)
        total = db.count_app_usage(machine_id, date=date, search=search)
        prod_apps, _, _ = _load_productivity_lists()

        by_category = {"productive": 0, "neutral": 0}
        total_seconds = 0
        filtered_rows = []
        for row in rows:
            row_category = _classify_app(row.get("app_name", ""), prod_apps)
            row["category"] = row_category
            if category and row_category != category:
                continue
            by_category[row_category] = by_category.get(row_category, 0) + 1
            total_seconds += int(row.get("total_seconds") or 0)
            filtered_rows.append(row)

        filtered_total = total
        if category:
            all_rows = db.get_app_usage(machine_id, date=date, search=search, limit=None, offset=0)
            filtered_total = 0
            for row in all_rows:
                if _classify_app(row.get("app_name", ""), prod_apps) == category:
                    filtered_total += 1

        return {
            "items": filtered_rows,
            "total": filtered_total,
            "stats": {
                "total_seconds": total_seconds,
                "by_category": by_category,
            },
        }

    def list_network_logs(
        self,
        machine_id: str = "",
        *,
        search: str = "",
        date: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        items = db.get_network_activity(machine_id, search, date, limit, offset)
        total = db.count_network_activity(machine_id, search, date)
        return {
            "items": items,
            "total": total,
            "stats": db.get_network_stats(machine_id),
        }

    def list_file_logs(
        self,
        machine_id: str = "",
        *,
        action: str = "",
        search: str = "",
        date: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        items = db.get_file_activity(machine_id, action, search, date, limit, offset)
        total = db.count_file_activity(machine_id, action, search, date)
        return {
            "items": items,
            "total": total,
            "stats": db.get_file_activity_stats(machine_id),
        }


activity_service = ActivityService()
