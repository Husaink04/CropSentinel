"""Tenant repository wrappers."""

from database import db


class TenantRepo:
    def get(self, tenant_id: int):
        return db.get_tenant(tenant_id)

    def get_by_slug(self, slug: str):
        return db.get_tenant_by_slug(slug)

    def get_by_enrollment_token(self, token: str):
        return db.get_tenant_by_enrollment_token(token)

    def get_license_info(self, tenant_id: int):
        return db.get_tenant_license_info(tenant_id)

    def list_with_stats(self):
        return db.get_all_tenants_with_stats()


tenant_repo = TenantRepo()
