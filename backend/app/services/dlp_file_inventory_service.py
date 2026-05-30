"""Baseline DLP file inventory ingestion and diagnostics."""

from __future__ import annotations

from typing import Any

from database import db


class DlpFileInventoryService:
    def ingest_batch(self, tenant_id: int, machine_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        records = payload.get("records", []) or []
        root_id = str(payload.get("root_id", "") or "")
        scan_job_id = payload.get("scan_job_id")
        stats = payload.get("stats", {}) or {}

        success_ids: list[int] = []
        failed_ids: list[int] = []

        for record in records:
            inventory_id = record.get("inventory_id")
            try:
                if inventory_id is None:
                    raise ValueError("inventory_id missing")
                data = {
                    **record,
                    "machine_id": machine_id,
                    "root_id": root_id or record.get("root_id", ""),
                    "scan_job_id": scan_job_id if scan_job_id is not None else record.get("scan_job_id"),
                }
                db.upsert_dlp_file_inventory(data, tenant_id=tenant_id)
                success_ids.append(int(inventory_id))
            except Exception:
                if inventory_id is not None:
                    failed_ids.append(int(inventory_id))

        db.upsert_dlp_file_inventory_sync_status(
            {
                "machine_id": machine_id,
                "root_id": root_id,
                "scan_job_id": scan_job_id,
                "pending_upload_count": stats.get("pending_upload_count", 0),
                "total_inventory_count": stats.get("total_inventory_count", 0),
                "parser_failure_count": stats.get("parser_failure_count", 0),
                "oldest_unsynced_at": stats.get("oldest_unsynced_at"),
                "metadata": {
                    "batch_size": len(records),
                    "processed": len(success_ids),
                },
            },
            tenant_id=tenant_id,
        )

        return {
            "status": "ok",
            "processed": len(success_ids),
            "success_ids": success_ids,
            "failed_ids": failed_ids,
        }

    def get_status(self, tenant_id: int, machine_id: str) -> dict[str, Any]:
        return db.get_dlp_file_inventory_status(machine_id, tenant_id=tenant_id)


dlp_file_inventory_service = DlpFileInventoryService()
