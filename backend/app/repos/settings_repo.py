"""Settings repository wrappers."""

from database import db


class SettingsRepo:
    def get(self):
        return db.get_settings()

    def update(self, payload: dict):
        return db.update_settings(payload)


settings_repo = SettingsRepo()
