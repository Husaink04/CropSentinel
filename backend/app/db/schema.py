"""Schema DDL and boot-time migration helpers."""

import secrets
from datetime import datetime, timezone

DDL = """
-- €€€ TENANTS (multi-tenancy root) €€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€
-- Every tenant-scoped table FKs back here. The "default" tenant is seeded
-- automatically with id=1 so existing single-tenant queries keep working
-- via the tenant_id DEFAULT 1 fallback on every other table.
CREATE TABLE IF NOT EXISTS tenants (
    id                   SERIAL      PRIMARY KEY,
    slug                 TEXT        UNIQUE NOT NULL,
    name                 TEXT        NOT NULL DEFAULT '',
    status               TEXT        NOT NULL DEFAULT 'active',
    enrollment_token     TEXT        UNIQUE,
    customer_name        TEXT        DEFAULT '',
    tier                 TEXT        DEFAULT 'starter',
    max_seats            INTEGER     DEFAULT 0,
    valid_until          TIMESTAMPTZ,
    grace_days           INTEGER     DEFAULT 14,
    subscription_started TIMESTAMPTZ DEFAULT NOW(),
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS machines (
    id                BIGINT,
    machine_id        TEXT PRIMARY KEY,
    tenant_id         INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    hostname          TEXT        DEFAULT '',
    os                TEXT        DEFAULT '',
    os_version        TEXT        DEFAULT '',
    username          TEXT        DEFAULT '',
    ip_address        TEXT        DEFAULT '',
    mac_address       TEXT        DEFAULT '',
    consent_given     BOOLEAN     DEFAULT FALSE,
    consent_timestamp TIMESTAMPTZ,
    first_seen        TIMESTAMPTZ DEFAULT NOW(),
    last_seen         TIMESTAMPTZ DEFAULT NOW(),
    agent_version     TEXT        DEFAULT '1.0.0',
    cpu_percent       REAL        DEFAULT 0,
    memory_percent    REAL        DEFAULT 0,
    active_app        TEXT        DEFAULT '',
    idle_seconds      INTEGER     DEFAULT 0,
    agent_health      JSONB       DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_machines_tenant ON machines(tenant_id);

CREATE TABLE IF NOT EXISTS evidence_objects (
    id                      BIGSERIAL   PRIMARY KEY,
    tenant_id               INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id              TEXT        DEFAULT '',
    machine_ref             BIGINT,
    category                TEXT        NOT NULL DEFAULT 'generic',
    evidence_classification TEXT        NOT NULL DEFAULT 'standard',
    content_type            TEXT        DEFAULT 'application/octet-stream',
    storage_backend         TEXT        NOT NULL DEFAULT 'filesystem',
    storage_key             TEXT        NOT NULL UNIQUE,
    sha256                  TEXT        DEFAULT '',
    size_bytes              BIGINT      DEFAULT 0,
    encryption_status       TEXT        NOT NULL DEFAULT 'plaintext_at_rest',
    retention_status        TEXT        NOT NULL DEFAULT 'active',
    retention_expires_at    TIMESTAMPTZ,
    metadata                JSONB       DEFAULT '{}',
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_evidence_objects_tenant_category
    ON evidence_objects(tenant_id, category, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_objects_machine
    ON evidence_objects(tenant_id, machine_ref, created_at DESC);

CREATE TABLE IF NOT EXISTS teams (
    id          UUID        PRIMARY KEY,
    tenant_id   INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    description TEXT        DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_teams_tenant_name ON teams(tenant_id, name);

CREATE TABLE IF NOT EXISTS team_memberships (
    id          BIGSERIAL   PRIMARY KEY,
    team_id     UUID        NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    machine_id  TEXT        NOT NULL REFERENCES machines(machine_id) ON DELETE CASCADE,
    added_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(team_id, machine_id)
);
CREATE INDEX IF NOT EXISTS idx_team_memberships_team ON team_memberships(team_id);
CREATE INDEX IF NOT EXISTS idx_team_memberships_machine ON team_memberships(machine_id);

CREATE TABLE IF NOT EXISTS browser_activity (
    id               BIGSERIAL   NOT NULL,
    tenant_id        INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id       TEXT        REFERENCES machines(machine_id) ON DELETE CASCADE,
    machine_ref      BIGINT,
    timestamp        TIMESTAMPTZ DEFAULT NOW(),
    browser          TEXT        DEFAULT '',
    url              TEXT        DEFAULT '',
    title            TEXT        DEFAULT '',
    domain           TEXT        DEFAULT '',
    duration_seconds INTEGER     DEFAULT 0
)
PARTITION BY RANGE (timestamp);
CREATE INDEX IF NOT EXISTS idx_browser_tenant_ts  ON browser_activity(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_browser_machine_ts ON browser_activity(machine_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_browser_id_tenant  ON browser_activity(tenant_id, id);
CREATE INDEX IF NOT EXISTS idx_browser_domain     ON browser_activity(domain);

CREATE TABLE IF NOT EXISTS app_activity (
    id               BIGSERIAL   NOT NULL,
    tenant_id        INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id       TEXT        REFERENCES machines(machine_id) ON DELETE CASCADE,
    machine_ref      BIGINT,
    timestamp        TIMESTAMPTZ DEFAULT NOW(),
    app_name         TEXT        DEFAULT '',
    window_title     TEXT        DEFAULT '',
    process_name     TEXT        DEFAULT '',
    duration_seconds INTEGER     DEFAULT 0,
    is_active        BOOLEAN     DEFAULT TRUE
)
PARTITION BY RANGE (timestamp);
CREATE INDEX IF NOT EXISTS idx_app_tenant_ts    ON app_activity(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_app_machine_ts   ON app_activity(machine_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_app_id_tenant    ON app_activity(tenant_id, id);
CREATE INDEX IF NOT EXISTS idx_app_name_ts      ON app_activity(app_name, timestamp DESC);

CREATE TABLE IF NOT EXISTS screenshots (
    id               BIGSERIAL   PRIMARY KEY,
    tenant_id        INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id       TEXT        REFERENCES machines(machine_id) ON DELETE CASCADE,
    machine_ref      BIGINT,
    timestamp        TIMESTAMPTZ DEFAULT NOW(),
    image_data       TEXT        DEFAULT '',
    trigger          TEXT        DEFAULT 'scheduled',
    evidence_id      BIGINT REFERENCES evidence_objects(id) ON DELETE SET NULL,
    storage_key      TEXT        DEFAULT '',
    storage_backend  TEXT        DEFAULT '',
    sha256           TEXT        DEFAULT '',
    size_bytes       BIGINT      DEFAULT 0,
    content_type     TEXT        DEFAULT 'image/png',
    retention_expires_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_screenshots_tenant  ON screenshots(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_screenshots_machine ON screenshots(machine_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS settings (
    tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    key       TEXT    NOT NULL,
    value     TEXT    DEFAULT '',
    PRIMARY KEY (tenant_id, key)
);
CREATE INDEX IF NOT EXISTS idx_settings_tenant ON settings(tenant_id);

CREATE TABLE IF NOT EXISTS tenant_config_documents (
    id             BIGSERIAL   PRIMARY KEY,
    tenant_id      INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    doc_type       TEXT        NOT NULL,
    schema_version INTEGER     NOT NULL DEFAULT 1,
    payload        JSONB       DEFAULT '{}',
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, doc_type)
);
CREATE INDEX IF NOT EXISTS idx_tenant_config_documents_tenant_type
    ON tenant_config_documents(tenant_id, doc_type);

CREATE TABLE IF NOT EXISTS alert_rules (
    id          SERIAL      PRIMARY KEY,
    tenant_id   INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    description TEXT        DEFAULT '',
    rule_type   TEXT        NOT NULL DEFAULT 'system',
    condition   TEXT        NOT NULL DEFAULT '',
    threshold   TEXT        DEFAULT '',
    machine_id  TEXT        DEFAULT 'all',
    severity    TEXT        DEFAULT 'medium',
    enabled     BOOLEAN     DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alert_rules_tenant ON alert_rules(tenant_id);

CREATE TABLE IF NOT EXISTS alert_logs (
    id              BIGSERIAL   PRIMARY KEY,
    tenant_id       INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    rule_id         INTEGER     DEFAULT 0,
    rule_name       TEXT        DEFAULT '',
    machine_id      TEXT        DEFAULT '',
    hostname        TEXT        DEFAULT '',
    severity        TEXT        DEFAULT 'medium',
    message         TEXT        NOT NULL DEFAULT '',
    details         TEXT        DEFAULT '',
    triggered_at    TIMESTAMPTZ DEFAULT NOW(),
    acknowledged    BOOLEAN     DEFAULT FALSE,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by TEXT        DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_alert_logs_tenant  ON alert_logs(tenant_id, triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_logs_ack     ON alert_logs(acknowledged, triggered_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_logs_machine ON alert_logs(machine_id, triggered_at DESC);

CREATE TABLE IF NOT EXISTS input_activity (
    id                 BIGSERIAL   PRIMARY KEY,
    tenant_id          INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id         TEXT        REFERENCES machines(machine_id) ON DELETE CASCADE,
    machine_ref        BIGINT,
    timestamp          TIMESTAMPTZ DEFAULT NOW(),
    bucket_start       TIMESTAMPTZ,
    bucket_end         TIMESTAMPTZ,
    process_name       TEXT        DEFAULT '',
    window_title       TEXT        DEFAULT '',
    key_event_count    INTEGER     DEFAULT 0,
    mouse_click_count  INTEGER     DEFAULT 0,
    mouse_scroll_count INTEGER     DEFAULT 0,
    pattern_hashes     TEXT        DEFAULT '[]',
    ngram_size         INTEGER     DEFAULT 8
);
CREATE INDEX IF NOT EXISTS idx_input_tenant_ts  ON input_activity(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_input_machine_ts ON input_activity(machine_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS users (
    id                SERIAL      PRIMARY KEY,
    tenant_id         INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    username          TEXT        UNIQUE NOT NULL,
    password_hash     TEXT        NOT NULL,
    display_name      TEXT        DEFAULT '',
    role              TEXT        NOT NULL DEFAULT 'viewer',
    assigned_machines TEXT        DEFAULT '[]',
    active            BOOLEAN     DEFAULT TRUE,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW(),
    created_by        TEXT        DEFAULT 'system'
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_tenant   ON users(tenant_id);

CREATE TABLE IF NOT EXISTS audit_logs (
    id              BIGSERIAL   PRIMARY KEY,
    tenant_id       INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    timestamp       TIMESTAMPTZ DEFAULT NOW(),
    user_id         INTEGER     DEFAULT 0,
    username        TEXT        DEFAULT '',
    role            TEXT        DEFAULT '',
    action          TEXT        NOT NULL DEFAULT '',
    resource_type   TEXT        DEFAULT '',
    resource_id     TEXT        DEFAULT '',
    ip_address      TEXT        DEFAULT '',
    metadata        TEXT        DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant   ON audit_logs(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_ts       ON audit_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user     ON audit_logs(username, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action   ON audit_logs(action, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_logs(resource_type, timestamp DESC);

CREATE TABLE IF NOT EXISTS file_activity (
    id          BIGSERIAL   NOT NULL,
    tenant_id   INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id  TEXT        REFERENCES machines(machine_id) ON DELETE CASCADE,
    machine_ref BIGINT,
    timestamp   TIMESTAMPTZ DEFAULT NOW(),
    action      TEXT        NOT NULL DEFAULT '',
    file_path   TEXT        DEFAULT '',
    file_name   TEXT        DEFAULT '',
    file_ext    TEXT        DEFAULT '',
    file_size   BIGINT      DEFAULT 0,
    destination TEXT        DEFAULT '',
    destination_type TEXT   DEFAULT '',
    destination_label TEXT  DEFAULT '',
    is_directory BOOLEAN    DEFAULT FALSE,
    backup_available BOOLEAN DEFAULT FALSE,
    backup_skip_reason TEXT DEFAULT '',
    enterprise_label TEXT DEFAULT '',
    sensitivity_score INTEGER DEFAULT 0,
    label_source TEXT DEFAULT '',
    label_reason TEXT DEFAULT '',
    block_candidate BOOLEAN DEFAULT FALSE,
    block_reason TEXT DEFAULT '',
    blocking_supported BOOLEAN DEFAULT FALSE,
    blocking_mode TEXT DEFAULT ''
)
PARTITION BY RANGE (timestamp);
CREATE INDEX IF NOT EXISTS idx_file_tenant_ts  ON file_activity(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_file_machine_ts ON file_activity(machine_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_file_id_tenant ON file_activity(tenant_id, id);
CREATE INDEX IF NOT EXISTS idx_file_action     ON file_activity(action);

CREATE TABLE IF NOT EXISTS deleted_file_backups (
    id          BIGSERIAL   PRIMARY KEY,
    tenant_id   INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id  TEXT        REFERENCES machines(machine_id) ON DELETE CASCADE,
    machine_ref BIGINT,
    timestamp   TIMESTAMPTZ DEFAULT NOW(),
    original_path TEXT      NOT NULL,
    file_name   TEXT        NOT NULL DEFAULT '',
    file_ext    TEXT        DEFAULT '',
    file_size   BIGINT      DEFAULT 0,
    file_data   TEXT        NOT NULL DEFAULT '',
    evidence_id BIGINT      REFERENCES evidence_objects(id) ON DELETE SET NULL,
    storage_key TEXT        DEFAULT '',
    storage_backend TEXT    DEFAULT '',
    sha256      TEXT        DEFAULT '',
    content_type TEXT       DEFAULT 'application/octet-stream',
    retention_expires_at TIMESTAMPTZ,
    evidence_classification TEXT DEFAULT 'restore_backup',
    is_directory BOOLEAN    DEFAULT FALSE,
    username    TEXT        DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_deleted_tenant_ts  ON deleted_file_backups(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_deleted_machine_ts ON deleted_file_backups(machine_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS network_activity (
    id              BIGSERIAL   NOT NULL,
    tenant_id       INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id      TEXT        REFERENCES machines(machine_id) ON DELETE CASCADE,
    machine_ref     BIGINT,
    timestamp       TIMESTAMPTZ DEFAULT NOW(),
    bytes_sent      BIGINT      DEFAULT 0,
    bytes_recv      BIGINT      DEFAULT 0,
    total_sent      BIGINT      DEFAULT 0,
    total_recv      BIGINT      DEFAULT 0,
    listen_count    INT         DEFAULT 0,
    conn_count      INT         DEFAULT 0,
    listening_ports JSONB       DEFAULT '[]',
    connections     JSONB       DEFAULT '[]'
)
PARTITION BY RANGE (timestamp);
CREATE INDEX IF NOT EXISTS idx_net_tenant_ts  ON network_activity(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_net_machine_ts ON network_activity(machine_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_net_id_tenant  ON network_activity(tenant_id, id);

CREATE TABLE IF NOT EXISTS dlp_events (
    id                BIGSERIAL   NOT NULL,
    tenant_id         INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id        TEXT        REFERENCES machines(machine_id) ON DELETE CASCADE,
    machine_ref       BIGINT,
    timestamp         TIMESTAMPTZ DEFAULT NOW(),
    file_path         TEXT        DEFAULT '',
    file_name         TEXT        DEFAULT '',
    file_ext          TEXT        DEFAULT '',
    file_size         BIGINT      DEFAULT 0,
    risk_level        TEXT        NOT NULL DEFAULT 'low',
    risk_score        INTEGER     DEFAULT 0,
    findings          JSONB       DEFAULT '[]',
    file_hash         TEXT        DEFAULT '',
    destination       TEXT        DEFAULT 'local',
    device            TEXT        DEFAULT '',
    is_known_sensitive BOOLEAN    DEFAULT FALSE,
    scoring           JSONB       DEFAULT '{}',
    acknowledged      BOOLEAN     DEFAULT FALSE,
    enterprise_label  TEXT        DEFAULT '',
    sensitivity_score INTEGER     DEFAULT 0,
    label_source      TEXT        DEFAULT '',
    label_reason      TEXT        DEFAULT '',
    block_candidate   BOOLEAN     DEFAULT FALSE,
    block_reason      TEXT        DEFAULT '',
    blocking_supported BOOLEAN    DEFAULT FALSE,
    blocking_mode     TEXT        DEFAULT ''
)
PARTITION BY RANGE (timestamp);
CREATE INDEX IF NOT EXISTS idx_dlp_tenant_ts   ON dlp_events(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_dlp_machine_ts  ON dlp_events(machine_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_dlp_id_tenant   ON dlp_events(tenant_id, id);
CREATE INDEX IF NOT EXISTS idx_dlp_risk        ON dlp_events(risk_level, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_dlp_hash        ON dlp_events(file_hash);
CREATE INDEX IF NOT EXISTS idx_dlp_destination ON dlp_events(destination);

CREATE TABLE IF NOT EXISTS dlp_policies (
    id            BIGSERIAL   PRIMARY KEY,
    tenant_id     INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    scope         TEXT        NOT NULL DEFAULT 'tenant_override',
    name          TEXT        NOT NULL DEFAULT '',
    description   TEXT        DEFAULT '',
    mode          TEXT        NOT NULL DEFAULT 'detect_then_block',
    status        TEXT        NOT NULL DEFAULT 'draft',
    priority      INTEGER     DEFAULT 100,
    version       INTEGER     DEFAULT 1,
    rollout_mode  TEXT        NOT NULL DEFAULT 'monitor_only',
    is_baseline   BOOLEAN     DEFAULT FALSE,
    is_mandatory  BOOLEAN     DEFAULT FALSE,
    config        JSONB       DEFAULT '{}',
    published_at  TIMESTAMPTZ,
    published_by  TEXT        DEFAULT '',
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dlp_policies_tenant_scope ON dlp_policies(tenant_id, scope, status);

CREATE TABLE IF NOT EXISTS dlp_classifiers (
    id              BIGSERIAL   PRIMARY KEY,
    tenant_id       INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    scope           TEXT        NOT NULL DEFAULT 'tenant',
    name            TEXT        NOT NULL,
    category        TEXT        DEFAULT 'custom',
    classifier_type TEXT        NOT NULL DEFAULT 'regex',
    builtin         BOOLEAN     DEFAULT FALSE,
    enabled         BOOLEAN     DEFAULT TRUE,
    severity        TEXT        DEFAULT 'medium',
    config          JSONB       DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);
CREATE INDEX IF NOT EXISTS idx_dlp_classifiers_tenant ON dlp_classifiers(tenant_id, enabled, category);

CREATE TABLE IF NOT EXISTS dlp_rules (
    id                BIGSERIAL   PRIMARY KEY,
    tenant_id         INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    policy_id         BIGINT      NOT NULL REFERENCES dlp_policies(id) ON DELETE CASCADE,
    name              TEXT        NOT NULL DEFAULT '',
    description       TEXT        DEFAULT '',
    classifier_ids    JSONB       DEFAULT '[]',
    channels          JSONB       DEFAULT '["file"]',
    destination_scope JSONB       DEFAULT '["any"]',
    severity          TEXT        DEFAULT 'medium',
    confidence        REAL        DEFAULT 0.8,
    action            TEXT        DEFAULT 'monitor',
    mandatory         BOOLEAN     DEFAULT FALSE,
    enabled           BOOLEAN     DEFAULT TRUE,
    config            JSONB       DEFAULT '{}',
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dlp_rules_tenant_policy ON dlp_rules(tenant_id, policy_id, enabled);

CREATE TABLE IF NOT EXISTS dlp_exceptions (
    id               BIGSERIAL   PRIMARY KEY,
    tenant_id        INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    scope_type       TEXT        NOT NULL DEFAULT 'path',
    scope_value      TEXT        DEFAULT '',
    classifier_name  TEXT        DEFAULT '',
    app_name         TEXT        DEFAULT '',
    destination_type TEXT        DEFAULT '',
    path_pattern     TEXT        DEFAULT '',
    reason           TEXT        DEFAULT '',
    expires_at       TIMESTAMPTZ,
    created_by       TEXT        DEFAULT '',
    status           TEXT        DEFAULT 'active',
    metadata         JSONB       DEFAULT '{}',
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dlp_exceptions_tenant ON dlp_exceptions(tenant_id, status, expires_at);

CREATE TABLE IF NOT EXISTS dlp_incidents (
    id                  BIGSERIAL   PRIMARY KEY,
    tenant_id           INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    state               TEXT        NOT NULL DEFAULT 'open',
    severity            TEXT        NOT NULL DEFAULT 'medium',
    title               TEXT        NOT NULL DEFAULT '',
    summary             TEXT        DEFAULT '',
    policy_rule_id      BIGINT,
    file_hash           TEXT        DEFAULT '',
    content_fingerprint TEXT        DEFAULT '',
    machine_id          TEXT        DEFAULT '',
    actor_username      TEXT        DEFAULT '',
    channel             TEXT        DEFAULT 'file',
    destination_type    TEXT        DEFAULT '',
    destination_label   TEXT        DEFAULT '',
    first_seen          TIMESTAMPTZ DEFAULT NOW(),
    last_seen           TIMESTAMPTZ DEFAULT NOW(),
    event_count         INTEGER     DEFAULT 1,
    assignee            TEXT        DEFAULT '',
    metadata            JSONB       DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dlp_incidents_tenant_state ON dlp_incidents(tenant_id, state, severity, last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_dlp_incidents_rule ON dlp_incidents(tenant_id, policy_rule_id, last_seen DESC);

CREATE TABLE IF NOT EXISTS dlp_incident_notes (
    id          BIGSERIAL   PRIMARY KEY,
    tenant_id   INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    incident_id BIGINT      NOT NULL REFERENCES dlp_incidents(id) ON DELETE CASCADE,
    note        TEXT        NOT NULL DEFAULT '',
    created_by  TEXT        DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dlp_incident_notes_incident ON dlp_incident_notes(tenant_id, incident_id, created_at);

CREATE TABLE IF NOT EXISTS dlp_incident_timeline (
    id          BIGSERIAL   PRIMARY KEY,
    tenant_id   INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    incident_id BIGINT      NOT NULL REFERENCES dlp_incidents(id) ON DELETE CASCADE,
    action      TEXT        NOT NULL DEFAULT '',
    actor       TEXT        DEFAULT '',
    payload     JSONB       DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dlp_incident_timeline_incident ON dlp_incident_timeline(tenant_id, incident_id, created_at);

CREATE TABLE IF NOT EXISTS dlp_file_inventory (
    id                  BIGSERIAL   PRIMARY KEY,
    tenant_id           INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id          TEXT        NOT NULL REFERENCES machines(machine_id) ON DELETE CASCADE,
    machine_ref         BIGINT,
    root_id             TEXT        NOT NULL DEFAULT '',
    scan_job_id         BIGINT,
    absolute_path       TEXT        NOT NULL DEFAULT '',
    normalized_path     TEXT        NOT NULL DEFAULT '',
    file_name           TEXT        NOT NULL DEFAULT '',
    extension           TEXT        NOT NULL DEFAULT '',
    size_bytes          BIGINT      DEFAULT 0,
    mtime_ns            BIGINT      DEFAULT 0,
    ctime_ns            BIGINT      DEFAULT 0,
    owner_name          TEXT        DEFAULT '',
    sha256              TEXT        DEFAULT '',
    content_fingerprint TEXT        DEFAULT '',
    scan_version        TEXT        DEFAULT '',
    scan_status         TEXT        DEFAULT 'scanned',
    inspect_status      TEXT        DEFAULT 'pending',
    inspect_reason      TEXT        DEFAULT '',
    parser_type         TEXT        DEFAULT '',
    findings_summary    JSONB       DEFAULT '{}',
    label_summary       JSONB       DEFAULT '{}',
    first_seen_at       TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ DEFAULT NOW(),
    last_scanned_at     TIMESTAMPTZ DEFAULT NOW(),
    uploaded_at         TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, machine_id, normalized_path)
);
CREATE INDEX IF NOT EXISTS idx_dlp_file_inventory_machine_path
    ON dlp_file_inventory(tenant_id, machine_id, normalized_path);
CREATE INDEX IF NOT EXISTS idx_dlp_file_inventory_machine_hash
    ON dlp_file_inventory(tenant_id, machine_id, sha256);
CREATE INDEX IF NOT EXISTS idx_dlp_file_inventory_risk
    ON dlp_file_inventory(tenant_id, ((label_summary->>'risk')), last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_dlp_file_inventory_last_seen
    ON dlp_file_inventory(tenant_id, machine_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS dlp_file_inventory_sync_status (
    id                    BIGSERIAL   PRIMARY KEY,
    tenant_id             INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id            TEXT        NOT NULL REFERENCES machines(machine_id) ON DELETE CASCADE,
    machine_ref           BIGINT,
    root_id               TEXT        NOT NULL DEFAULT '',
    scan_job_id           BIGINT,
    pending_upload_count  INTEGER     DEFAULT 0,
    total_inventory_count INTEGER     DEFAULT 0,
    parser_failure_count  INTEGER     DEFAULT 0,
    oldest_unsynced_at    TIMESTAMPTZ,
    last_batch_at         TIMESTAMPTZ DEFAULT NOW(),
    metadata              JSONB       DEFAULT '{}',
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, machine_id, root_id)
);
CREATE INDEX IF NOT EXISTS idx_dlp_file_inventory_sync_machine
    ON dlp_file_inventory_sync_status(tenant_id, machine_id, last_batch_at DESC);

CREATE TABLE IF NOT EXISTS machine_inventory_rollups (
    id                        BIGSERIAL   PRIMARY KEY,
    tenant_id                 INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id                TEXT        NOT NULL REFERENCES machines(machine_id) ON DELETE CASCADE,
    machine_ref               BIGINT,
    total_inventory_count     INTEGER     DEFAULT 0,
    public_count              INTEGER     DEFAULT 0,
    internal_count            INTEGER     DEFAULT 0,
    sensitive_count           INTEGER     DEFAULT 0,
    confidential_count        INTEGER     DEFAULT 0,
    highly_confidential_count INTEGER     DEFAULT 0,
    pending_upload_count      INTEGER     DEFAULT 0,
    parser_failure_count      INTEGER     DEFAULT 0,
    oldest_unsynced_at        TIMESTAMPTZ,
    last_inventory_scan_at    TIMESTAMPTZ,
    last_inventory_upload_at  TIMESTAMPTZ,
    created_at                TIMESTAMPTZ DEFAULT NOW(),
    updated_at                TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, machine_id)
);
CREATE INDEX IF NOT EXISTS idx_machine_inventory_rollups_tenant
    ON machine_inventory_rollups(tenant_id, last_inventory_upload_at DESC);

CREATE TABLE IF NOT EXISTS phishing_policies (
    id                  BIGSERIAL   PRIMARY KEY,
    tenant_id           INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    scope               TEXT        NOT NULL DEFAULT 'tenant_override',
    name                TEXT        NOT NULL DEFAULT 'Phishing Policy',
    description         TEXT        DEFAULT '',
    status              TEXT        NOT NULL DEFAULT 'published',
    priority            INTEGER     NOT NULL DEFAULT 100,
    version             INTEGER     NOT NULL DEFAULT 1,
    rollout_mode        TEXT        NOT NULL DEFAULT 'warn_only',
    intel_mode          TEXT        NOT NULL DEFAULT 'intel_plus_heuristics',
    protected_channels  JSONB       DEFAULT '["browser","download","desktop_link_open","email_client_open"]',
    severity_thresholds JSONB       DEFAULT '{"medium":55,"high":75,"critical":90}',
    allowlists          JSONB       DEFAULT '{"domains":[],"apps":[],"users":[],"paths":[]}',
    suspicious_tlds     JSONB       DEFAULT '["zip","click","work","country","gq","tk","ru"]',
    brand_watchlist     JSONB       DEFAULT '["microsoft","google","apple","okta","adobe","dropbox","slack","paypal","amazon","github","office365","outlook","bank"]',
    download_risk_rules JSONB       DEFAULT '{"dangerous_extensions":["exe","msi","bat","cmd","ps1","scr","vbs","js","jar","iso","zip"],"warn_unknown_downloads":true}',
    evidence_controls   JSONB       DEFAULT '{"capture_title":true,"store_masked_indicators":true,"store_url":true}',
    config              JSONB       DEFAULT '{}',
    is_baseline         BOOLEAN     DEFAULT FALSE,
    is_mandatory        BOOLEAN     DEFAULT FALSE,
    published_at        TIMESTAMPTZ,
    published_by        TEXT        DEFAULT '',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_phishing_policies_tenant_scope ON phishing_policies(tenant_id, scope, status, priority DESC);

CREATE TABLE IF NOT EXISTS phishing_allowlist_exceptions (
    id          BIGSERIAL   PRIMARY KEY,
    tenant_id   INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    domain      TEXT        NOT NULL DEFAULT '',
    app_name    TEXT        DEFAULT '',
    username    TEXT        DEFAULT '',
    path_pattern TEXT       DEFAULT '',
    reason      TEXT        DEFAULT '',
    expires_at  TIMESTAMPTZ,
    created_by  TEXT        DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_phishing_allowlist_tenant_domain ON phishing_allowlist_exceptions(tenant_id, domain, expires_at);

CREATE TABLE IF NOT EXISTS phishing_blocklist_exceptions (
    id          BIGSERIAL   PRIMARY KEY,
    tenant_id   INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    domain      TEXT        NOT NULL DEFAULT '',
    url_pattern TEXT        DEFAULT '',
    reason      TEXT        DEFAULT '',
    expires_at  TIMESTAMPTZ,
    created_by  TEXT        DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_phishing_blocklist_tenant_domain ON phishing_blocklist_exceptions(tenant_id, domain, expires_at);

CREATE TABLE IF NOT EXISTS phishing_incidents (
    id               BIGSERIAL   PRIMARY KEY,
    tenant_id        INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    state            TEXT        NOT NULL DEFAULT 'open',
    severity         TEXT        NOT NULL DEFAULT 'medium',
    confidence       REAL        DEFAULT 0,
    title            TEXT        NOT NULL DEFAULT 'Phishing incident',
    summary          TEXT        DEFAULT '',
    machine_id       TEXT        DEFAULT '',
    actor_username   TEXT        DEFAULT '',
    app_name         TEXT        DEFAULT '',
    process_name     TEXT        DEFAULT '',
    channel          TEXT        NOT NULL DEFAULT 'browser',
    domain           TEXT        DEFAULT '',
    url              TEXT        DEFAULT '',
    destination_label TEXT       DEFAULT '',
    rule_id          TEXT        DEFAULT '',
    warning_shown    BOOLEAN     DEFAULT FALSE,
    event_count      INTEGER     DEFAULT 1,
    first_seen       TIMESTAMPTZ DEFAULT NOW(),
    last_seen        TIMESTAMPTZ DEFAULT NOW(),
    assignee         TEXT        DEFAULT '',
    metadata         JSONB       DEFAULT '{}',
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_phishing_incidents_tenant_state ON phishing_incidents(tenant_id, state, severity, last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_phishing_incidents_domain ON phishing_incidents(tenant_id, domain, channel, last_seen DESC);

CREATE TABLE IF NOT EXISTS phishing_incident_notes (
    id          BIGSERIAL   PRIMARY KEY,
    tenant_id   INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    incident_id BIGINT      NOT NULL REFERENCES phishing_incidents(id) ON DELETE CASCADE,
    note        TEXT        NOT NULL DEFAULT '',
    created_by  TEXT        DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_phishing_incident_notes_incident ON phishing_incident_notes(tenant_id, incident_id, created_at);

CREATE TABLE IF NOT EXISTS phishing_incident_timeline (
    id          BIGSERIAL   PRIMARY KEY,
    tenant_id   INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    incident_id BIGINT      NOT NULL REFERENCES phishing_incidents(id) ON DELETE CASCADE,
    action      TEXT        NOT NULL DEFAULT '',
    actor       TEXT        DEFAULT '',
    payload     JSONB       DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_phishing_incident_timeline_incident ON phishing_incident_timeline(tenant_id, incident_id, created_at);

CREATE TABLE IF NOT EXISTS phishing_events (
    id                BIGSERIAL   NOT NULL,
    tenant_id         INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    machine_id        TEXT        DEFAULT '',
    machine_ref       BIGINT,
    timestamp         TIMESTAMPTZ DEFAULT NOW(),
    event_type        TEXT        DEFAULT 'browser_visit',
    channel           TEXT        DEFAULT 'browser',
    url               TEXT        DEFAULT '',
    domain            TEXT        DEFAULT '',
    page_title        TEXT        DEFAULT '',
    app_name          TEXT        DEFAULT '',
    process_name      TEXT        DEFAULT '',
    remote_ip         TEXT        DEFAULT '',
    destination_label TEXT        DEFAULT '',
    actor_username    TEXT        DEFAULT '',
    policy_version    INTEGER     DEFAULT 1,
    policy_hash       TEXT        DEFAULT '',
    rule_id           TEXT        DEFAULT '',
    risk_score        REAL        DEFAULT 0,
    confidence        REAL        DEFAULT 0,
    severity          TEXT        DEFAULT 'low',
    action_taken      TEXT        DEFAULT 'monitor',
    action_result     TEXT        DEFAULT 'observed',
    reason_codes      JSONB       DEFAULT '[]',
    evidence          JSONB       DEFAULT '[]',
    screenshot_ref    TEXT        DEFAULT '',
    unsupported_reason TEXT       DEFAULT '',
    incident_id       BIGINT,
    created_at        TIMESTAMPTZ DEFAULT NOW()
)
PARTITION BY RANGE (timestamp);
CREATE INDEX IF NOT EXISTS idx_phishing_events_tenant_ts ON phishing_events(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_phishing_events_id_tenant ON phishing_events(tenant_id, id);
CREATE INDEX IF NOT EXISTS idx_phishing_events_domain ON phishing_events(tenant_id, domain, channel, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_phishing_events_incident ON phishing_events(tenant_id, incident_id, timestamp DESC);
"""

ALL_TABLES = [
    "machine_inventory_rollups",
    "team_memberships",
    "teams",
    "dlp_incident_timeline",
    "phishing_events",
    "phishing_incident_timeline",
    "phishing_incident_notes",
    "phishing_incidents",
    "phishing_blocklist_exceptions",
    "phishing_allowlist_exceptions",
    "phishing_policies",
    "dlp_incident_notes",
    "dlp_incidents",
    "dlp_file_inventory_sync_status",
    "dlp_file_inventory",
    "dlp_exceptions",
    "dlp_rules",
    "dlp_classifiers",
    "dlp_policies",
    "dlp_events",
    "network_activity",
    "deleted_file_backups",
    "file_activity",
    "audit_logs",
    "report_jobs",
    "input_activity",
    "alert_logs",
    "alert_rules",
    "tenant_config_documents",
    "evidence_objects",
    "screenshots",
    "app_activity",
    "browser_activity",
    "users",
    "settings",
    "machines",
    "tenants",
]

PARTITIONED_TELEMETRY_TABLES = {
    "browser_activity": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS browser_activity (
                id BIGSERIAL NOT NULL,
                tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
                machine_id TEXT REFERENCES machines(machine_id) ON DELETE CASCADE,
                machine_ref BIGINT,
                timestamp TIMESTAMPTZ DEFAULT NOW(),
                browser TEXT DEFAULT '',
                url TEXT DEFAULT '',
                title TEXT DEFAULT '',
                domain TEXT DEFAULT '',
                duration_seconds INTEGER DEFAULT 0
            ) PARTITION BY RANGE (timestamp)
        """,
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_browser_tenant_ts ON browser_activity(tenant_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_browser_machine_ts ON browser_activity(machine_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_browser_id_tenant ON browser_activity(tenant_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_browser_domain ON browser_activity(domain)",
        ],
    },
    "app_activity": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS app_activity (
                id BIGSERIAL NOT NULL,
                tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
                machine_id TEXT REFERENCES machines(machine_id) ON DELETE CASCADE,
                machine_ref BIGINT,
                timestamp TIMESTAMPTZ DEFAULT NOW(),
                app_name TEXT DEFAULT '',
                window_title TEXT DEFAULT '',
                process_name TEXT DEFAULT '',
                duration_seconds INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE
            ) PARTITION BY RANGE (timestamp)
        """,
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_app_tenant_ts ON app_activity(tenant_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_app_machine_ts ON app_activity(machine_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_app_id_tenant ON app_activity(tenant_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_app_name_ts ON app_activity(app_name, timestamp DESC)",
        ],
    },
    "file_activity": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS file_activity (
                id BIGSERIAL NOT NULL,
                tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
                machine_id TEXT REFERENCES machines(machine_id) ON DELETE CASCADE,
                machine_ref BIGINT,
                timestamp TIMESTAMPTZ DEFAULT NOW(),
                action TEXT NOT NULL DEFAULT '',
                file_path TEXT DEFAULT '',
                file_name TEXT DEFAULT '',
                file_ext TEXT DEFAULT '',
                file_size BIGINT DEFAULT 0,
                destination TEXT DEFAULT '',
                destination_type TEXT DEFAULT '',
                destination_label TEXT DEFAULT '',
                is_directory BOOLEAN DEFAULT FALSE,
                backup_available BOOLEAN DEFAULT FALSE,
                backup_skip_reason TEXT DEFAULT '',
                enterprise_label TEXT DEFAULT '',
                sensitivity_score INTEGER DEFAULT 0,
                label_source TEXT DEFAULT '',
                label_reason TEXT DEFAULT '',
                block_candidate BOOLEAN DEFAULT FALSE,
                block_reason TEXT DEFAULT '',
                blocking_supported BOOLEAN DEFAULT FALSE,
                blocking_mode TEXT DEFAULT ''
            ) PARTITION BY RANGE (timestamp)
        """,
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_file_tenant_ts ON file_activity(tenant_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_file_machine_ts ON file_activity(machine_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_file_id_tenant ON file_activity(tenant_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_file_action ON file_activity(action)",
        ],
    },
    "network_activity": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS network_activity (
                id BIGSERIAL NOT NULL,
                tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
                machine_id TEXT REFERENCES machines(machine_id) ON DELETE CASCADE,
                machine_ref BIGINT,
                timestamp TIMESTAMPTZ DEFAULT NOW(),
                bytes_sent BIGINT DEFAULT 0,
                bytes_recv BIGINT DEFAULT 0,
                total_sent BIGINT DEFAULT 0,
                total_recv BIGINT DEFAULT 0,
                listen_count INT DEFAULT 0,
                conn_count INT DEFAULT 0,
                listening_ports JSONB DEFAULT '[]',
                connections JSONB DEFAULT '[]'
            ) PARTITION BY RANGE (timestamp)
        """,
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_net_tenant_ts ON network_activity(tenant_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_net_machine_ts ON network_activity(machine_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_net_id_tenant ON network_activity(tenant_id, id)",
        ],
    },
    "dlp_events": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS dlp_events (
                id BIGSERIAL NOT NULL,
                tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
                machine_id TEXT REFERENCES machines(machine_id) ON DELETE CASCADE,
                machine_ref BIGINT,
                timestamp TIMESTAMPTZ DEFAULT NOW(),
                file_path TEXT DEFAULT '',
                file_name TEXT DEFAULT '',
                file_ext TEXT DEFAULT '',
                file_size BIGINT DEFAULT 0,
                risk_level TEXT NOT NULL DEFAULT 'low',
                risk_score INTEGER DEFAULT 0,
                findings JSONB DEFAULT '[]',
                file_hash TEXT DEFAULT '',
                destination TEXT DEFAULT 'local',
                device TEXT DEFAULT '',
                is_known_sensitive BOOLEAN DEFAULT FALSE,
                scoring JSONB DEFAULT '{}',
                acknowledged BOOLEAN DEFAULT FALSE,
                enterprise_label TEXT DEFAULT '',
                sensitivity_score INTEGER DEFAULT 0,
                label_source TEXT DEFAULT '',
                label_reason TEXT DEFAULT '',
                block_candidate BOOLEAN DEFAULT FALSE,
                block_reason TEXT DEFAULT '',
                blocking_supported BOOLEAN DEFAULT FALSE,
                blocking_mode TEXT DEFAULT '',
                event_type TEXT DEFAULT 'file_transfer',
                channel TEXT DEFAULT 'file',
                policy_version INTEGER DEFAULT 1,
                policy_rule_id BIGINT,
                classifier_hits JSONB DEFAULT '[]',
                confidence REAL DEFAULT 0,
                action_taken TEXT DEFAULT 'monitor',
                action_result TEXT DEFAULT 'observed',
                justification_required BOOLEAN DEFAULT FALSE,
                justification_text TEXT DEFAULT '',
                exception_applied JSONB DEFAULT '{}',
                masked_evidence JSONB DEFAULT '[]',
                actor_username TEXT DEFAULT '',
                app_name TEXT DEFAULT '',
                destination_type TEXT DEFAULT '',
                destination_label TEXT DEFAULT '',
                content_fingerprint TEXT DEFAULT '',
                incident_id BIGINT
            ) PARTITION BY RANGE (timestamp)
        """,
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_dlp_tenant_ts ON dlp_events(tenant_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_dlp_machine_ts ON dlp_events(machine_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_dlp_id_tenant ON dlp_events(tenant_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_dlp_risk ON dlp_events(risk_level, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_dlp_hash ON dlp_events(file_hash)",
            "CREATE INDEX IF NOT EXISTS idx_dlp_destination ON dlp_events(destination)",
            "CREATE INDEX IF NOT EXISTS idx_dlp_incident_id ON dlp_events(tenant_id, incident_id)",
            "CREATE INDEX IF NOT EXISTS idx_dlp_policy_rule ON dlp_events(tenant_id, policy_rule_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_dlp_channel_destination ON dlp_events(tenant_id, channel, destination_type, timestamp DESC)",
        ],
    },
    "phishing_events": {
        "create_sql": """
            CREATE TABLE IF NOT EXISTS phishing_events (
                id BIGSERIAL NOT NULL,
                tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
                machine_id TEXT DEFAULT '',
                machine_ref BIGINT,
                timestamp TIMESTAMPTZ DEFAULT NOW(),
                event_type TEXT DEFAULT 'browser_visit',
                channel TEXT DEFAULT 'browser',
                url TEXT DEFAULT '',
                domain TEXT DEFAULT '',
                page_title TEXT DEFAULT '',
                app_name TEXT DEFAULT '',
                process_name TEXT DEFAULT '',
                remote_ip TEXT DEFAULT '',
                destination_label TEXT DEFAULT '',
                actor_username TEXT DEFAULT '',
                policy_version INTEGER DEFAULT 1,
                policy_hash TEXT DEFAULT '',
                rule_id TEXT DEFAULT '',
                risk_score REAL DEFAULT 0,
                confidence REAL DEFAULT 0,
                severity TEXT DEFAULT 'low',
                action_taken TEXT DEFAULT 'monitor',
                action_result TEXT DEFAULT 'observed',
                reason_codes JSONB DEFAULT '[]',
                evidence JSONB DEFAULT '[]',
                screenshot_ref TEXT DEFAULT '',
                unsupported_reason TEXT DEFAULT '',
                incident_id BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            ) PARTITION BY RANGE (timestamp)
        """,
        "indexes": [
            "CREATE INDEX IF NOT EXISTS idx_phishing_events_tenant_ts ON phishing_events(tenant_id, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_phishing_events_id_tenant ON phishing_events(tenant_id, id)",
            "CREATE INDEX IF NOT EXISTS idx_phishing_events_domain ON phishing_events(tenant_id, domain, channel, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_phishing_events_incident ON phishing_events(tenant_id, incident_id, timestamp DESC)",
        ],
    },
}


def _month_floor(ts: datetime) -> datetime:
    return ts.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_month(dt: datetime) -> datetime:
    year = dt.year + (1 if dt.month == 12 else 0)
    month = 1 if dt.month == 12 else dt.month + 1
    return dt.replace(year=year, month=month, day=1)


def _ensure_partition_table(cur, table_name: str, dt: datetime) -> None:
    start = _month_floor(dt)
    end = _add_month(start)
    partition_name = f"{table_name}_{start.strftime('%Y%m')}"
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {partition_name}
        PARTITION OF {table_name}
        FOR VALUES FROM (%s) TO (%s)
        """,
        (start, end),
    )


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("SELECT current_schema() AS schema_name")
    schema_name = (cur.fetchone() or {}).get("schema_name") or "public"
    cur.execute("SELECT to_regclass(%s) AS reg", (f"{schema_name}.{table_name}",))
    row = cur.fetchone() or {}
    return bool(row.get("reg"))


def _is_partitioned_table(cur, table_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM pg_partitioned_table p
        JOIN pg_class c ON c.oid = p.partrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema() AND c.relname = %s
        """,
        (table_name,),
    )
    return cur.fetchone() is not None


def _create_partitioned_parent(cur, table_name: str) -> None:
    spec = PARTITIONED_TELEMETRY_TABLES[table_name]
    cur.execute(spec["create_sql"])
    for index_sql in spec["indexes"]:
        cur.execute(index_sql)


def _migrate_partitioned_table(cur, logger, table_name: str) -> None:
    if not _table_exists(cur, table_name):
        _create_partitioned_parent(cur, table_name)
        now = datetime.now(timezone.utc)
        _ensure_partition_table(cur, table_name, now)
        _ensure_partition_table(cur, table_name, _add_month(_month_floor(now)))
        return
    if _is_partitioned_table(cur, table_name):
        _create_partitioned_parent(cur, table_name)
        now = datetime.now(timezone.utc)
        _ensure_partition_table(cur, table_name, now)
        _ensure_partition_table(cur, table_name, _add_month(_month_floor(now)))
        return

    legacy_name = f"{table_name}_legacy"
    if _table_exists(cur, legacy_name):
        cur.execute(f"DROP TABLE IF EXISTS {legacy_name} CASCADE")
    cur.execute(f"ALTER TABLE {table_name} RENAME TO {legacy_name}")
    _create_partitioned_parent(cur, table_name)
    cur.execute(f"SELECT DISTINCT date_trunc('month', timestamp) AS month_start FROM {legacy_name} ORDER BY month_start ASC")
    months = [row["month_start"] for row in cur.fetchall() if row.get("month_start")]
    if not months:
        months = [datetime.now(timezone.utc)]
    for month_start in months:
        _ensure_partition_table(cur, table_name, month_start)
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    dest_columns = [row["column_name"] for row in cur.fetchall()]
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = %s
        """,
        (legacy_name,),
    )
    source_columns = {row["column_name"] for row in cur.fetchall()}
    common_columns = [col for col in dest_columns if col in source_columns]
    column_sql = ", ".join(common_columns)
    cur.execute(f"INSERT INTO {table_name} ({column_sql}) SELECT {column_sql} FROM {legacy_name}")
    cur.execute(f"DROP TABLE IF EXISTS {legacy_name} CASCADE")
    logger.info("Migrated %s to monthly range partitioning", table_name)


def ensure_partitioned_telemetry_tables(cur, logger) -> None:
    for table_name in PARTITIONED_TELEMETRY_TABLES:
        _migrate_partitioned_table(cur, logger, table_name)


def initialize_schema(cur, logger, reset_requested: bool) -> None:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = current_schema() AND table_name = 'tenants'
        ) AS has_tenants,
        EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = current_schema() AND table_name = 'machines'
        ) AS has_machines
        """
    )
    row = cur.fetchone()
    has_tenants = bool(row["has_tenants"])
    has_machines = bool(row["has_machines"])

    if reset_requested:
        logger.warning("CROPPRO_RESET_DB=1 - DROPPING ALL CROPPRO TABLES.")
        for table_name in ALL_TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
    elif has_machines and not has_tenants:
        raise RuntimeError(
            "CropSentinel database is at the pre-v5 (single-tenant) schema. "
            "The v5 upgrade requires a one-time wipe. Set CROPPRO_RESET_DB=1 "
            "in your environment and restart to recreate the schema."
        )

    if not reset_requested:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'network_activity' AND column_name = 'listening_ports'
            """
        )
        if not cur.fetchone():
            cur.execute("DROP TABLE IF EXISTS network_activity CASCADE")

        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'file_activity' AND column_name = 'file_name'
            """
        )
        if not cur.fetchone():
            cur.execute("DROP TABLE IF EXISTS file_activity CASCADE")

        # v5.x multi-tenant migration: older installs had a global
        # `settings(key PK, value)` table. Add a tenant_id column, backfill
        # existing rows to tenant 1 (the default tenant), and promote the
        # PK to (tenant_id, key) so each tenant has its own row per key.
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'settings' AND column_name = 'tenant_id'
            """
        )
        if not cur.fetchone():
            # Table may not exist yet on a fresh install — that's fine, the
            # CREATE TABLE below will create it correctly. Only migrate if it
            # exists without the column.
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = 'settings'"
            )
            if cur.fetchone():
                logger.warning(
                    "Migrating legacy global `settings` table to tenant-scoped PK."
                )
                cur.execute(
                    "ALTER TABLE settings "
                    "ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1"
                )
                cur.execute("ALTER TABLE settings DROP CONSTRAINT IF EXISTS settings_pkey")
                cur.execute(
                    "ALTER TABLE settings ADD PRIMARY KEY (tenant_id, key)"
                )
                cur.execute(
                    "ALTER TABLE settings "
                    "ADD CONSTRAINT settings_tenant_fk "
                    "FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE"
                )

    cur.execute(DDL)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS report_jobs (
            id            TEXT        PRIMARY KEY,
            tenant_id     INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
            machine_id    TEXT        NOT NULL REFERENCES machines(machine_id) ON DELETE CASCADE,
            report_type   TEXT        NOT NULL DEFAULT 'machine_pdf',
            status        TEXT        NOT NULL DEFAULT 'queued',
            requested_by  TEXT        DEFAULT '',
            start_date    TEXT        DEFAULT '',
            end_date      TEXT        DEFAULT '',
            output_path   TEXT        DEFAULT '',
            evidence_id   BIGINT      REFERENCES evidence_objects(id) ON DELETE SET NULL,
            storage_key   TEXT        DEFAULT '',
            storage_backend TEXT      DEFAULT '',
            content_type  TEXT        DEFAULT 'application/pdf',
            filename      TEXT        DEFAULT '',
            error_message TEXT        DEFAULT '',
            metadata      JSONB       DEFAULT '{}',
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            started_at    TIMESTAMPTZ,
            completed_at  TIMESTAMPTZ
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_report_jobs_tenant_created ON report_jobs(tenant_id, created_at DESC)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_report_jobs_machine_status "
        "ON report_jobs(tenant_id, machine_id, status, created_at DESC)"
    )
    for col_def in (
        "evidence_id BIGINT",
        "storage_key TEXT DEFAULT ''",
        "storage_backend TEXT DEFAULT ''",
        "content_type TEXT DEFAULT 'application/pdf'",
        "filename TEXT DEFAULT ''",
    ):
        cur.execute(f"ALTER TABLE report_jobs ADD COLUMN IF NOT EXISTS {col_def}")
    cur.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'report_jobs_evidence_id_fk'
            ) THEN
                ALTER TABLE report_jobs
                ADD CONSTRAINT report_jobs_evidence_id_fk
                FOREIGN KEY (evidence_id) REFERENCES evidence_objects(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )

    cur.execute("ALTER TABLE machines ADD COLUMN IF NOT EXISTS id BIGINT")
    cur.execute("CREATE SEQUENCE IF NOT EXISTS machines_id_seq")
    cur.execute("ALTER SEQUENCE machines_id_seq OWNED BY machines.id")
    cur.execute("ALTER TABLE machines ALTER COLUMN id SET DEFAULT nextval('machines_id_seq')")
    cur.execute("UPDATE machines SET id = nextval('machines_id_seq') WHERE id IS NULL")
    cur.execute("ALTER TABLE machines ALTER COLUMN id SET NOT NULL")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_machines_id ON machines(id)")
    cur.execute("SELECT setval('machines_id_seq', GREATEST((SELECT COALESCE(MAX(id), 0) FROM machines), 1))")

    for col_def in (
        "enrollment_token     TEXT UNIQUE",
        "customer_name        TEXT DEFAULT ''",
        "tier                 TEXT DEFAULT 'starter'",
        "max_seats            INTEGER DEFAULT 0",
        "valid_until          TIMESTAMPTZ",
        "grace_days           INTEGER DEFAULT 14",
        "subscription_started TIMESTAMPTZ DEFAULT NOW()",
    ):
        cur.execute(f"ALTER TABLE tenants ADD COLUMN IF NOT EXISTS {col_def}")

    for col_def in (
        "geo_country      TEXT DEFAULT ''",
        "geo_country_code TEXT DEFAULT ''",
        "geo_city         TEXT DEFAULT ''",
        "geo_isp          TEXT DEFAULT ''",
        "geo_org          TEXT DEFAULT ''",
        "geo_lat          REAL",
        "geo_lon          REAL",
        "agent_health     JSONB DEFAULT '{}'",
    ):
        cur.execute(f"ALTER TABLE machines ADD COLUMN IF NOT EXISTS {col_def}")

    machine_ref_tables = (
        "browser_activity",
        "app_activity",
        "screenshots",
        "input_activity",
        "file_activity",
        "deleted_file_backups",
        "network_activity",
        "dlp_events",
        "dlp_file_inventory",
        "dlp_file_inventory_sync_status",
        "machine_inventory_rollups",
        "phishing_events",
    )
    for table_name in machine_ref_tables:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS machine_ref BIGINT")
        cur.execute(
            f"""
            UPDATE {table_name} t
            SET machine_ref = m.id
            FROM machines m
            WHERE t.machine_id = m.machine_id
              AND t.machine_ref IS NULL
            """
        )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_browser_machine_ref_ts ON browser_activity(tenant_id, machine_ref, timestamp DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_app_machine_ref_ts ON app_activity(tenant_id, machine_ref, timestamp DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_screenshots_machine_ref ON screenshots(tenant_id, machine_ref, timestamp DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_input_machine_ref_ts ON input_activity(tenant_id, machine_ref, timestamp DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_file_machine_ref_ts ON file_activity(tenant_id, machine_ref, timestamp DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_deleted_machine_ref_ts ON deleted_file_backups(tenant_id, machine_ref, timestamp DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_net_machine_ref_ts ON network_activity(tenant_id, machine_ref, timestamp DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dlp_machine_ref_ts ON dlp_events(tenant_id, machine_ref, timestamp DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dlp_file_inventory_machine_ref_path ON dlp_file_inventory(tenant_id, machine_ref, normalized_path)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_phishing_events_machine_ref_ts ON phishing_events(tenant_id, machine_ref, timestamp DESC)")

    for col_def in (
        "evidence_id BIGINT",
        "storage_key TEXT DEFAULT ''",
        "storage_backend TEXT DEFAULT ''",
        "sha256 TEXT DEFAULT ''",
        "size_bytes BIGINT DEFAULT 0",
        "content_type TEXT DEFAULT 'image/png'",
        "retention_expires_at TIMESTAMPTZ",
    ):
        cur.execute(f"ALTER TABLE screenshots ADD COLUMN IF NOT EXISTS {col_def}")

    for col_def in (
        "evidence_id BIGINT",
        "storage_key TEXT DEFAULT ''",
        "storage_backend TEXT DEFAULT ''",
        "sha256 TEXT DEFAULT ''",
        "content_type TEXT DEFAULT 'application/octet-stream'",
        "retention_expires_at TIMESTAMPTZ",
        "evidence_classification TEXT DEFAULT 'restore_backup'",
    ):
        cur.execute(f"ALTER TABLE deleted_file_backups ADD COLUMN IF NOT EXISTS {col_def}")

    cur.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'screenshots_evidence_id_fk'
            ) THEN
                ALTER TABLE screenshots
                ADD CONSTRAINT screenshots_evidence_id_fk
                FOREIGN KEY (evidence_id) REFERENCES evidence_objects(id) ON DELETE SET NULL;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'deleted_file_backups_evidence_id_fk'
            ) THEN
                ALTER TABLE deleted_file_backups
                ADD CONSTRAINT deleted_file_backups_evidence_id_fk
                FOREIGN KEY (evidence_id) REFERENCES evidence_objects(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )

    for col_def in (
        "backup_available BOOLEAN DEFAULT FALSE",
        "backup_skip_reason TEXT DEFAULT ''",
        "destination_type TEXT DEFAULT ''",
        "destination_label TEXT DEFAULT ''",
        "enterprise_label TEXT DEFAULT ''",
        "sensitivity_score INTEGER DEFAULT 0",
        "label_source TEXT DEFAULT ''",
        "label_reason TEXT DEFAULT ''",
        "block_candidate BOOLEAN DEFAULT FALSE",
        "block_reason TEXT DEFAULT ''",
        "blocking_supported BOOLEAN DEFAULT FALSE",
        "blocking_mode TEXT DEFAULT ''",
    ):
        cur.execute(f"ALTER TABLE file_activity ADD COLUMN IF NOT EXISTS {col_def}")

    for col_def in (
        "event_type TEXT DEFAULT 'file_transfer'",
        "channel TEXT DEFAULT 'file'",
        "policy_version INTEGER DEFAULT 1",
        "policy_rule_id BIGINT",
        "classifier_hits JSONB DEFAULT '[]'",
        "confidence REAL DEFAULT 0",
        "action_taken TEXT DEFAULT 'monitor'",
        "action_result TEXT DEFAULT 'observed'",
        "justification_required BOOLEAN DEFAULT FALSE",
        "justification_text TEXT DEFAULT ''",
        "exception_applied JSONB DEFAULT '{}'",
        "masked_evidence JSONB DEFAULT '[]'",
        "actor_username TEXT DEFAULT ''",
        "app_name TEXT DEFAULT ''",
        "destination_type TEXT DEFAULT ''",
        "destination_label TEXT DEFAULT ''",
        "content_fingerprint TEXT DEFAULT ''",
        "incident_id BIGINT",
        "enterprise_label TEXT DEFAULT ''",
        "sensitivity_score INTEGER DEFAULT 0",
        "label_source TEXT DEFAULT ''",
        "label_reason TEXT DEFAULT ''",
        "block_candidate BOOLEAN DEFAULT FALSE",
        "block_reason TEXT DEFAULT ''",
        "blocking_supported BOOLEAN DEFAULT FALSE",
        "blocking_mode TEXT DEFAULT ''",
    ):
        cur.execute(f"ALTER TABLE dlp_events ADD COLUMN IF NOT EXISTS {col_def}")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_dlp_incident_id ON dlp_events(tenant_id, incident_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dlp_policy_rule ON dlp_events(tenant_id, policy_rule_id, timestamp DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dlp_channel_destination ON dlp_events(tenant_id, channel, destination_type, timestamp DESC)")

    ensure_partitioned_telemetry_tables(cur, logger)

    cur.execute(
        """
        INSERT INTO tenants (id, slug, name, status, tier, max_seats, grace_days)
        VALUES (1, 'default', 'Default Tenant', 'active', 'msp', 0, 14)
        ON CONFLICT (id) DO NOTHING
        """
    )
    cur.execute(
        """
        SELECT setval(pg_get_serial_sequence('tenants', 'id'),
                      GREATEST((SELECT MAX(id) FROM tenants), 1))
        """
    )

    cur.execute("SELECT id FROM tenants WHERE enrollment_token IS NULL OR enrollment_token = ''")
    missing = cur.fetchall()
    for row in missing:
        token = f"cpet_{secrets.token_urlsafe(24)}"
        cur.execute(
            "UPDATE tenants SET enrollment_token = %s WHERE id = %s",
            (token, row["id"]),
        )
    if missing:
        logger.info("Backfilled enrollment_token for %d tenant(s)", len(missing))

    logger.info("Database schema OK (v5 multi-tenant)")
