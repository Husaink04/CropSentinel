"""Tenant repository wrappers."""

from database import db


class TenantRepo:
    def get(self, tenant_id: int, *, accessible_tenant_id: int | None = None):
        return db.get_tenant(tenant_id, accessible_tenant_id=accessible_tenant_id)

    def get_by_slug(self, slug: str):
        return db.get_tenant_by_slug(slug)

    def get_by_enrollment_token(self, token: str):
        return db.get_tenant_by_enrollment_token(token)

    def get_license_info(self, tenant_id: int):
        return db.get_tenant_license_info(tenant_id)

    def list_with_stats(self, *, parent_tenant_id: int | None = None, include_parent: bool = False):
        return db.get_all_tenants_with_stats(parent_tenant_id=parent_tenant_id, include_parent=include_parent)


tenant_repo = TenantRepo()
