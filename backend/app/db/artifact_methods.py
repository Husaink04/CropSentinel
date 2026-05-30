"""Artifact and evidence-object storage helpers."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.db.core import Connection as _Conn, get_tenant_id as _tid, utcnow
from app.object_storage import evidence_storage, object_storage

logger = logging.getLogger("croppro.db")


class ArtifactMethodsMixin:
    def create_generated_artifact(
        self,
        *,
        category: str,
        evidence_classification: str,
        content_type: str,
        filename: str,
        raw_bytes: bytes,
        tenant_id: int | None = None,
        machine_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        tid = int(tenant_id if tenant_id is not None else _tid())
        normalized_machine = machine_id or ""
        machine_ref = self.get_machine_ref(normalized_machine, tid) if normalized_machine else None
        stored = object_storage.store_bytes(
            raw_bytes=raw_bytes,
            tenant_id=tid,
            category=category,
            machine_id=normalized_machine,
            filename_hint=filename,
        )
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO evidence_objects
                        (tenant_id, machine_id, machine_ref, category, evidence_classification,
                         content_type, storage_backend, storage_key, sha256, size_bytes,
                         retention_status, metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        tid,
                        normalized_machine,
                        machine_ref,
                        category,
                        evidence_classification,
                        content_type,
                        stored.backend,
                        stored.storage_key,
                        stored.sha256,
                        stored.size_bytes,
                        "active",
                        json.dumps({"filename": filename, **(metadata or {})}),
                        utcnow(),
                        utcnow(),
                    ),
                )
                row = dict(cur.fetchone())
        return row

    def get_evidence_object(self, evidence_id: int, tenant_id: int | None = None) -> Optional[dict]:
        tid = int(tenant_id if tenant_id is not None else _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM evidence_objects WHERE id = %s AND tenant_id = %s",
                    (evidence_id, tid),
                )
                row = cur.fetchone()
        if not row:
            return None
        payload = dict(row)
        if isinstance(payload.get("metadata"), str):
            try:
                payload["metadata"] = json.loads(payload["metadata"])
            except Exception:
                payload["metadata"] = {}
        return payload

    def load_evidence_object_bytes(self, evidence_id: int, tenant_id: int | None = None) -> bytes:
        payload = self.get_evidence_object(evidence_id, tenant_id=tenant_id)
        if not payload:
            raise FileNotFoundError(f"Evidence object {evidence_id} not found")
        return object_storage.load_bytes(payload["storage_key"])

    def backfill_legacy_binary_evidence(self, limit: int = 100) -> dict[str, int]:
        counts = {"screenshots": 0, "deleted_backups": 0}
        if limit <= 0:
            return counts
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, tenant_id, machine_id, machine_ref, image_data, content_type, trigger
                    FROM screenshots
                    WHERE COALESCE(image_data, '') <> '' AND COALESCE(storage_key, '') = ''
                    ORDER BY id ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
                screenshot_rows = [dict(row) for row in cur.fetchall()]
        for row in screenshot_rows:
            try:
                stored = evidence_storage.store_base64(
                    base64_data=row.get("image_data", ""),
                    tenant_id=int(row["tenant_id"]),
                    machine_id=row.get("machine_id") or "unknown",
                    category="screenshots",
                    filename_hint="capture.png",
                )
                with _Conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO evidence_objects
                                (tenant_id, machine_id, machine_ref, category, evidence_classification,
                                 content_type, storage_backend, storage_key, sha256, size_bytes,
                                 retention_status, metadata, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            (
                                row["tenant_id"],
                                row.get("machine_id", ""),
                                row.get("machine_ref"),
                                "screenshots",
                                "screen_capture",
                                row.get("content_type") or "image/png",
                                stored.backend,
                                stored.storage_key,
                                stored.sha256,
                                stored.size_bytes,
                                "active",
                                json.dumps({"trigger": row.get("trigger", "scheduled"), "backfilled": True}),
                                utcnow(),
                                utcnow(),
                            ),
                        )
                        evidence_id = cur.fetchone()["id"]
                        cur.execute(
                            """
                            UPDATE screenshots
                            SET image_data = '',
                                evidence_id = %s,
                                storage_key = %s,
                                storage_backend = %s,
                                sha256 = %s,
                                size_bytes = %s
                            WHERE id = %s
                            """,
                            (evidence_id, stored.storage_key, stored.backend, stored.sha256, stored.size_bytes, row["id"]),
                        )
                counts["screenshots"] += 1
            except Exception as exc:
                logger.warning("Failed screenshot backfill id=%s: %s", row["id"], exc)

        remaining = max(0, limit - counts["screenshots"])
        if remaining <= 0:
            return counts
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, tenant_id, machine_id, machine_ref, file_data, content_type, original_path, file_name
                    FROM deleted_file_backups
                    WHERE COALESCE(file_data, '') <> '' AND COALESCE(storage_key, '') = ''
                    ORDER BY id ASC
                    LIMIT %s
                    """,
                    (remaining,),
                )
                backup_rows = [dict(row) for row in cur.fetchall()]
        for row in backup_rows:
            try:
                stored = evidence_storage.store_base64(
                    base64_data=row.get("file_data", ""),
                    tenant_id=int(row["tenant_id"]),
                    machine_id=row.get("machine_id") or "unknown",
                    category="deleted_backups",
                    filename_hint=row.get("file_name") or "backup.bin",
                )
                with _Conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO evidence_objects
                                (tenant_id, machine_id, machine_ref, category, evidence_classification,
                                 content_type, storage_backend, storage_key, sha256, size_bytes,
                                 retention_status, metadata, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            (
                                row["tenant_id"],
                                row.get("machine_id", ""),
                                row.get("machine_ref"),
                                "deleted_backups",
                                "restore_backup",
                                row.get("content_type") or "application/octet-stream",
                                stored.backend,
                                stored.storage_key,
                                stored.sha256,
                                stored.size_bytes,
                                "active",
                                json.dumps({"original_path": row.get("original_path", ""), "backfilled": True}),
                                utcnow(),
                                utcnow(),
                            ),
                        )
                        evidence_id = cur.fetchone()["id"]
                        cur.execute(
                            """
                            UPDATE deleted_file_backups
                            SET file_data = '',
                                evidence_id = %s,
                                storage_key = %s,
                                storage_backend = %s,
                                sha256 = %s,
                                file_size = CASE WHEN file_size > 0 THEN file_size ELSE %s END
                            WHERE id = %s
                            """,
                            (evidence_id, stored.storage_key, stored.backend, stored.sha256, stored.size_bytes, row["id"]),
                        )
                counts["deleted_backups"] += 1
            except Exception as exc:
                logger.warning("Failed deleted backup backfill id=%s: %s", row["id"], exc)
        return counts
