from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ActivityEnvelopeRequest(BaseModel):
    event_id: Optional[str] = None
    captured_at: Optional[str] = None
    schema_version: Optional[int] = None
    event_source: Optional[str] = None
    activity_kind: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class AgentPasswordRequest(BaseModel):
    password: str

class MachineRegisterRequest(BaseModel):
    machine_id: str
    hostname: str
    os: str
    os_version: str
    username: str
    ip_address: str
    mac_address: Optional[str] = ""
    consent_given: bool
    consent_timestamp: str
    first_seen: str
    agent_version: str = "1.2.0"

class BrowserActivityRequest(ActivityEnvelopeRequest):
    machine_id: str
    timestamp: str
    browser: str
    url: str
    title: str
    domain: str
    duration_seconds: Optional[int] = 0

class AppActivityRequest(ActivityEnvelopeRequest):
    machine_id: str
    timestamp: str
    app_name: str
    window_title: str
    process_name: str
    duration_seconds: Optional[int] = 0
    is_active: Optional[bool] = True

class ScreenshotRequest(ActivityEnvelopeRequest):
    machine_id: str
    timestamp: str
    image_data: str  # base64 encoded
    trigger: Optional[str] = "scheduled"  # scheduled | manual | on_change

class HeartbeatRequest(ActivityEnvelopeRequest):
    machine_id: str
    timestamp: str
    cpu_percent: Optional[float] = 0
    memory_percent: Optional[float] = 0
    active_app: Optional[str] = ""
    active_browser: Optional[str] = ""
    active_url: Optional[str] = ""
    idle_seconds: Optional[int] = 0
    agent_health: Optional[Dict[str, Any]] = None

class InputActivityRequest(ActivityEnvelopeRequest):
    """Tier B: keycode n-gram hashes only — no raw keystroke text."""
    machine_id: str
    timestamp: str
    bucket_start: str
    bucket_end: str
    process_name: str = ""
    window_title: str = ""
    key_event_count: int = 0
    mouse_click_count: int = 0
    mouse_scroll_count: int = 0
    pattern_hashes: List[str] = []
    ngram_size: int = 8

class SettingsUpdateRequest(BaseModel):
    company_name: Optional[str] = None
    company_logo: Optional[str] = None  # base64
    screenshot_interval: Optional[int] = None
    activity_sync_interval: Optional[int] = None
    heartbeat_interval_seconds: Optional[int] = None
    app_tracker_interval_seconds: Optional[int] = None
    network_interval_seconds: Optional[int] = None
    usb_interval_seconds: Optional[int] = None
    print_interval_seconds: Optional[int] = None
    file_cache_fast_sweep_seconds: Optional[float] = None
    file_cache_recursive_sweep_seconds: Optional[float] = None
    file_cache_sweeper_enabled: Optional[bool] = None
    agent_self_throttle_enabled: Optional[bool] = None
    agent_self_throttle_cpu_percent: Optional[int] = None
    agent_self_throttle_memory_percent: Optional[int] = None
    agent_self_throttle_queue_depth: Optional[int] = None
    agent_self_throttle_multiplier: Optional[float] = None
    agent_self_throttle_cooldown_seconds: Optional[int] = None
    agent_stop_password: Optional[str] = None
    admin_username: Optional[str] = None
    productive_apps: Optional[list] = None
    productive_domains: Optional[list] = None
    unproductive_domains: Optional[list] = None
    productivity_apps: Optional[List[Dict[str, Any]]] = None
    productivity_domains: Optional[List[Dict[str, Any]]] = None
    productivity_categories: Optional[Dict[str, Any]] = None
    meeting_like_apps: Optional[List[Dict[str, Any]]] = None
    ai_work_assist_apps_or_domains: Optional[List[str]] = None
    productivity_policy_version: Optional[int] = None
    tracking_enabled: Optional[bool] = None
    track_screenshots: Optional[bool] = None
    track_browser: Optional[bool] = None
    track_applications: Optional[bool] = None
    track_input_activity: Optional[bool] = None
    input_bucket_seconds: Optional[int] = None
    baseline_inventory_enabled: Optional[bool] = None
    baseline_inventory_worker_count: Optional[int] = None
    baseline_inventory_io_throttle_seconds: Optional[float] = None
    baseline_inventory_upload_interval_seconds: Optional[int] = None
    baseline_inventory_upload_batch_size: Optional[int] = None
    baseline_inventory_max_hash_file_size: Optional[int] = None
    baseline_inventory_max_parser_file_size: Optional[int] = None
    baseline_inventory_max_ocr_file_size: Optional[int] = None
    baseline_inventory_rescan_unchanged_after_seconds: Optional[int] = None
    baseline_inventory_mount_discovery_interval_seconds: Optional[int] = None
    # WebRTC TURN server – single-entry convenience form used by the Settings UI.
    webrtc_turn_url:      Optional[str] = None
    webrtc_turn_username: Optional[str] = None
    webrtc_turn_password: Optional[str] = None
    # Advanced: a full ICE server list of { urls, username?, credential? }.
    # If set and non-empty it overrides the single-TURN fields above.
    ice_servers: Optional[list] = None

class AlertRuleRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    rule_type: str  # system | browser | idle | schedule | connectivity | app
    condition: str  # cpu_percent_gt | domain_in_blacklist | idle_seconds_gt | outside_hours | machine_offline | app_blocked
    threshold: Optional[str] = ""
    machine_id: Optional[str] = "all"
    severity: Optional[str] = "medium"  # low | medium | high | critical
    enabled: Optional[int] = 1


# ── RBAC ──────────────────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = ""
    role: str = "viewer"  # admin | manager | viewer | remote_operator
    assigned_machines: Optional[List[str]] = []
    tenant_id: Optional[int] = None  # platform admin can assign to any tenant

class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    assigned_machines: Optional[List[str]] = None
    active: Optional[bool] = None
    password: Optional[str] = None
    tenant_id: Optional[int] = None


# ── File Activity ────────────────────────────────────────────────────────────

class FileActivityRequest(ActivityEnvelopeRequest):
    machine_id: str
    timestamp: str
    action: str  # create | delete | modify | move
    file_path: str = ""
    file_name: str = ""
    file_ext: str = ""
    file_size: int = 0
    destination: str = ""
    is_directory: bool = False
    file_data: Optional[str] = None  # base64 backup for deleted files
    backup_available: Optional[bool] = None
    backup_skip_reason: str = ""
    enterprise_label: str = ""
    sensitivity_score: int = 0
    label_source: str = ""
    label_reason: str = ""
    destination_type: str = ""
    destination_label: str = ""
    block_candidate: bool = False
    block_reason: str = ""
    blocking_supported: bool = False
    blocking_mode: str = ""


# ── Network Activity ────────────────────────────────────────────────────────

class NetworkActivityRequest(ActivityEnvelopeRequest):
    machine_id: str
    timestamp: str
    bytes_sent: int = 0
    bytes_recv: int = 0
    total_sent: int = 0
    total_recv: int = 0
    listen_count: int = 0
    conn_count: int = 0
    listening_ports: List[dict] = []
    connections: List[dict] = []


# ── DLP Events ─────────────────────────────────────────────────────────────

class DLPEventRequest(BaseModel):
    machine_id: str
    timestamp: str
    file_path: str = ""
    file_name: str = ""
    file_ext: str = ""
    file_size: int = 0
    risk: str = "low"           # low | medium | high
    risk_level: str = ""
    risk_score: int = 0
    findings: List[dict] = []   # [{"type": "email", "count": 3}, ...]
    file_hash: str = ""
    destination: str = "local"
    device: str = ""
    is_known_sensitive: bool = False
    scoring: Dict[str, Any] = {}
    event_type: str = "file_transfer"
    channel: str = "file"
    policy_version: Optional[int] = None
    policy_rule_id: Optional[int] = None
    classifier_hits: List[dict] = []
    confidence: Optional[float] = None
    action_taken: Optional[str] = None
    action_result: Optional[str] = None
    justification_required: Optional[bool] = None
    justification_text: str = ""
    exception_applied: Dict[str, Any] = {}
    masked_evidence: List[dict] = []
    actor_username: str = ""
    app_name: str = ""
    destination_type: str = ""
    destination_label: str = ""
    content_fingerprint: str = ""
    incident_id: Optional[int] = None
    enterprise_label: str = ""
    sensitivity_score: int = 0
    label_source: str = ""
    label_reason: str = ""
    block_candidate: bool = False
    block_reason: str = ""
    blocking_supported: bool = False
    blocking_mode: str = ""


class DlpPolicyRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    scope: str = "tenant_override"
    mode: str = "detect_then_block"
    status: str = "draft"
    priority: int = 100
    rollout_mode: str = "monitor_only"
    is_baseline: bool = False
    is_mandatory: bool = False
    config: Dict[str, Any] = {}


class DlpRuleRequest(BaseModel):
    policy_id: int
    name: str
    description: Optional[str] = ""
    classifier_ids: List[int] = []
    channels: List[str] = ["file"]
    destination_scope: List[str] = ["any"]
    severity: str = "medium"
    confidence: float = 0.8
    action: str = "monitor"
    mandatory: bool = False
    enabled: bool = True
    config: Dict[str, Any] = {}


class DlpClassifierRequest(BaseModel):
    name: str
    category: str = "custom"
    classifier_type: str = "regex"
    scope: str = "tenant"
    builtin: bool = False
    enabled: bool = True
    severity: str = "medium"
    config: Dict[str, Any] = {}


class DlpExceptionRequest(BaseModel):
    scope_type: str = "path"
    scope_value: str = ""
    classifier_name: str = ""
    app_name: str = ""
    destination_type: str = ""
    path_pattern: str = ""
    reason: str = ""
    expires_at: Optional[str] = None
    status: str = "active"
    metadata: Dict[str, Any] = {}


class DlpIncidentUpdateRequest(BaseModel):
    state: Optional[str] = None
    severity: Optional[str] = None
    assignee: Optional[str] = None
    summary: Optional[str] = None
    disposition: Optional[str] = None
    resolution_reason: Optional[str] = None
    note: Optional[str] = None


class DlpSimulationRequest(BaseModel):
    content: str = ""
    file_path: str = ""
    file_name: str = ""
    machine_id: str = ""
    actor_username: str = ""
    channel: str = "file"
    destination_type: str = "local"


class PhishingEventRequest(BaseModel):
    machine_id: str
    timestamp: str
    event_type: str = "browser_visit"
    channel: str = "browser"
    url: str = ""
    domain: str = ""
    page_title: str = ""
    app_name: str = ""
    process_name: str = ""
    remote_ip: str = ""
    destination_label: str = ""
    actor_username: str = ""
    policy_version: Optional[int] = None
    policy_hash: str = ""
    rule_id: str = ""
    risk_score: Optional[float] = None
    confidence: Optional[float] = None
    severity: str = "low"
    action_taken: str = "monitor"
    action_result: str = "observed"
    reason_codes: List[str] = []
    evidence: List[dict] = []
    screenshot_ref: str = ""
    unsupported_reason: str = ""
    incident_id: Optional[int] = None


class PhishingPolicyRequest(BaseModel):
    name: str = "Phishing Policy"
    description: Optional[str] = ""
    scope: str = "tenant_override"
    status: str = "published"
    priority: int = 100
    version: int = 1
    rollout_mode: str = "warn_only"
    intel_mode: str = "intel_plus_heuristics"
    protected_channels: List[str] = ["browser", "download", "desktop_link_open", "email_client_open"]
    severity_thresholds: Dict[str, int] = {"medium": 55, "high": 75, "critical": 90}
    allowlists: Dict[str, List[str]] = {"domains": [], "apps": [], "users": [], "paths": []}
    suspicious_tlds: List[str] = ["zip", "click", "work"]
    brand_watchlist: List[str] = ["microsoft", "google", "okta"]
    download_risk_rules: Dict[str, Any] = {"dangerous_extensions": ["exe", "msi", "bat"], "warn_unknown_downloads": True}
    evidence_controls: Dict[str, Any] = {"capture_title": True, "store_masked_indicators": True, "store_url": True}
    phishing_enabled: bool = True
    is_baseline: bool = False
    is_mandatory: bool = False
    config: Dict[str, Any] = {}


class PhishingIncidentUpdateRequest(BaseModel):
    state: Optional[str] = None
    severity: Optional[str] = None
    assignee: Optional[str] = None
    summary: Optional[str] = None
    note: Optional[str] = None


class PhishingAllowlistRequest(BaseModel):
    domain: str = ""
    app_name: str = ""
    username: str = ""
    path_pattern: str = ""
    reason: str = ""
    expires_at: Optional[str] = None


class PhishingBlocklistRequest(BaseModel):
    domain: str = ""
    url_pattern: str = ""
    reason: str = ""
    expires_at: Optional[str] = None


class PhishingCheckRequest(BaseModel):
    machine_id: str
    url: str
    user_id: str = ""
    app_name: str = ""
    process_name: str = ""
    page_title: str = ""
    channel: str = "browser"
    initial_agent_verdict: str = "clean"
    local_features: Dict[str, Any] = {}


class PhishingReportRequest(BaseModel):
    machine_id: str
    url: str = ""
    domain: str = ""
    incident_id: Optional[int] = None
    feedback: str = ""
    verdict: str = ""
    note: str = ""


class TeamCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""


class TeamUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class TeamMachineAssignRequest(BaseModel):
    machine_id: str
