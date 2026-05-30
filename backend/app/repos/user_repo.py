"""User repository wrappers."""

from database import db


class UserRepo:
    def get_by_username(self, username: str):
        return db.get_user_by_username(username)

    def get_by_id(self, user_id: int):
        return db.get_user_by_id(user_id)

    def list_current_tenant(self):
        return db.get_all_users()

    def list_cross_tenant(self, tenant_id=None):
        return db.get_all_users_cross_tenant(tenant_id)

    def create(self, payload: dict) -> int:
        return db.create_user(payload)

    def update(self, user_id: int, payload: dict):
        return db.update_user(user_id, payload)

    def delete(self, user_id: int):
        return db.delete_user(user_id)

    def count_by_role(self, role: str) -> int:
        return db.count_users_by_role(role)


user_repo = UserRepo()
