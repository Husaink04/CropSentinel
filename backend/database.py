"""Composed database facade built from focused DB mixins."""

import logging
import os

from app.db.alert_methods import AlertMethodsMixin
from app.db.analytics_methods import AnalyticsMethodsMixin
from app.db.artifact_methods import ArtifactMethodsMixin
from app.db.dlp_enterprise_methods import DlpEnterpriseMethodsMixin
# `clear_tenant_context`, `set_tenant_context`, `utcnow`, `utcnow_iso`
# are imported by other modules via `from database import …`, so they
# must stay in this module's namespace even though `database.py` itself
# only uses `Connection`.
from app.db.core import (
    Connection as _Conn,
    clear_tenant_context,
    set_tenant_context,
    utcnow,
    utcnow_iso,
)
from app.db.file_network_dlp_methods import FileNetworkDlpMethodsMixin
from app.db.machine_methods import MachineMethodsMixin
from app.db.phishing_methods import PhishingMethodsMixin
from app.db.schema import initialize_schema
from app.db.settings_user_audit_methods import SettingsUserAuditMethodsMixin
from app.db.team_methods import TeamMethodsMixin
from app.db.tenant_methods import TenantMethodsMixin

logger = logging.getLogger("croppro.db")


class Database(
    TenantMethodsMixin,
    MachineMethodsMixin,
    TeamMethodsMixin,
    AnalyticsMethodsMixin,
    ArtifactMethodsMixin,
    AlertMethodsMixin,
    SettingsUserAuditMethodsMixin,
    FileNetworkDlpMethodsMixin,
    DlpEnterpriseMethodsMixin,
    PhishingMethodsMixin,
):
    """Single entrypoint used by route/service layers."""

    def ping(self) -> None:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

    def init_db(self) -> None:
        with _Conn() as conn:
            with conn.cursor() as cur:
                initialize_schema(
                    cur=cur,
                    logger=logger,
                    reset_requested=os.environ.get("CROPPRO_RESET_DB", "") == "1",
                )


db = Database()
