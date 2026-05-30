"""Audit repository wrappers."""

from database import db


class AuditRepo:
    def insert(self, payload: dict):
        return db.insert_audit_log(payload)


audit_repo = AuditRepo()
