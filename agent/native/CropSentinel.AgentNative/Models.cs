using System.Text.Json.Serialization;
using System.Text.Json;

namespace CropSentinel.AgentNative;

public sealed class MachineRegisterRequest
{
    [JsonPropertyName("machine_id")]
    public required string MachineId { get; init; }

    [JsonPropertyName("hostname")]
    public required string Hostname { get; init; }

    [JsonPropertyName("os")]
    public required string Os { get; init; }

    [JsonPropertyName("os_version")]
    public required string OsVersion { get; init; }

    [JsonPropertyName("username")]
    public required string Username { get; init; }

    [JsonPropertyName("ip_address")]
    public required string IpAddress { get; init; }

    [JsonPropertyName("mac_address")]
    public string MacAddress { get; init; } = "";

    [JsonPropertyName("consent_given")]
    public required bool ConsentGiven { get; init; }

    [JsonPropertyName("consent_timestamp")]
    public required string ConsentTimestamp { get; init; }

    [JsonPropertyName("first_seen")]
    public required string FirstSeen { get; init; }

    [JsonPropertyName("agent_version")]
    public required string AgentVersion { get; init; }
}

public sealed class RegistrationResponse
{
    [JsonPropertyName("status")]
    public string Status { get; init; } = "";

    [JsonPropertyName("machine_id")]
    public string MachineId { get; init; } = "";
}

public sealed class HeartbeatRequest
{
    [JsonPropertyName("machine_id")]
    public required string MachineId { get; init; }

    [JsonPropertyName("timestamp")]
    public required string Timestamp { get; init; }

    [JsonPropertyName("cpu_percent")]
    public double CpuPercent { get; init; }

    [JsonPropertyName("memory_percent")]
    public double MemoryPercent { get; init; }

    [JsonPropertyName("active_app")]
    public string ActiveApp { get; init; } = "";

    [JsonPropertyName("active_browser")]
    public string ActiveBrowser { get; init; } = "";

    [JsonPropertyName("active_url")]
    public string ActiveUrl { get; init; } = "";

    [JsonPropertyName("idle_seconds")]
    public int IdleSeconds { get; init; }

    [JsonPropertyName("agent_health")]
    public AgentHealth AgentHealth { get; init; } = new();
}

public sealed class AppActivityRequest
{
    [JsonPropertyName("machine_id")]
    public required string MachineId { get; init; }

    [JsonPropertyName("timestamp")]
    public required string Timestamp { get; init; }

    [JsonPropertyName("app_name")]
    public required string AppName { get; init; }

    [JsonPropertyName("window_title")]
    public string WindowTitle { get; init; } = "";

    [JsonPropertyName("process_name")]
    public string ProcessName { get; init; } = "";

    [JsonPropertyName("duration_seconds")]
    public int DurationSeconds { get; init; }

    [JsonPropertyName("is_active")]
    public bool IsActive { get; init; } = true;
}

public sealed class BrowserActivityRequest
{
    [JsonPropertyName("machine_id")]
    public required string MachineId { get; init; }

    [JsonPropertyName("timestamp")]
    public required string Timestamp { get; init; }

    [JsonPropertyName("browser")]
    public required string Browser { get; init; }

    [JsonPropertyName("url")]
    public required string Url { get; init; }

    [JsonPropertyName("title")]
    public string Title { get; init; } = "";

    [JsonPropertyName("domain")]
    public string Domain { get; init; } = "";

    [JsonPropertyName("duration_seconds")]
    public int DurationSeconds { get; init; }
}

public sealed class InputActivityRequest
{
    [JsonPropertyName("machine_id")]
    public required string MachineId { get; init; }

    [JsonPropertyName("timestamp")]
    public required string Timestamp { get; init; }

    [JsonPropertyName("bucket_start")]
    public required string BucketStart { get; init; }

    [JsonPropertyName("bucket_end")]
    public required string BucketEnd { get; init; }

    [JsonPropertyName("process_name")]
    public string ProcessName { get; init; } = "";

    [JsonPropertyName("window_title")]
    public string WindowTitle { get; init; } = "";

    [JsonPropertyName("key_event_count")]
    public int KeyEventCount { get; init; }

    [JsonPropertyName("mouse_click_count")]
    public int MouseClickCount { get; init; }

    [JsonPropertyName("mouse_scroll_count")]
    public int MouseScrollCount { get; init; }

    [JsonPropertyName("pattern_hashes")]
    public IReadOnlyList<string> PatternHashes { get; init; } = Array.Empty<string>();

    [JsonPropertyName("ngram_size")]
    public int NgramSize { get; init; } = 8;
}

public sealed class ScreenshotRequest
{
    [JsonPropertyName("machine_id")]
    public required string MachineId { get; init; }

    [JsonPropertyName("timestamp")]
    public required string Timestamp { get; init; }

    [JsonPropertyName("image_data")]
    public required string ImageData { get; init; }

    [JsonPropertyName("trigger")]
    public string Trigger { get; init; } = "scheduled";
}

public sealed class FileActivityRequest
{
    [JsonPropertyName("machine_id")]
    public required string MachineId { get; init; }

    [JsonPropertyName("timestamp")]
    public required string Timestamp { get; init; }

    [JsonPropertyName("action")]
    public required string Action { get; init; }

    [JsonPropertyName("file_path")]
    public string FilePath { get; init; } = "";

    [JsonPropertyName("file_name")]
    public string FileName { get; init; } = "";

    [JsonPropertyName("file_ext")]
    public string FileExt { get; init; } = "";

    [JsonPropertyName("file_size")]
    public long FileSize { get; init; }

    [JsonPropertyName("destination")]
    public string Destination { get; init; } = "";

    [JsonPropertyName("is_directory")]
    public bool IsDirectory { get; init; }

    [JsonPropertyName("file_data")]
    public string? FileData { get; init; }

    [JsonPropertyName("backup_available")]
    public bool? BackupAvailable { get; init; }

    [JsonPropertyName("backup_skip_reason")]
    public string BackupSkipReason { get; init; } = "";

    [JsonPropertyName("enterprise_label")]
    public string EnterpriseLabel { get; init; } = "";

    [JsonPropertyName("sensitivity_score")]
    public int SensitivityScore { get; init; }

    [JsonPropertyName("label_source")]
    public string LabelSource { get; init; } = "";

    [JsonPropertyName("label_reason")]
    public string LabelReason { get; init; } = "";

    [JsonPropertyName("destination_type")]
    public string DestinationType { get; init; } = "";

    [JsonPropertyName("destination_label")]
    public string DestinationLabel { get; init; } = "";

    [JsonPropertyName("block_candidate")]
    public bool BlockCandidate { get; init; }

    [JsonPropertyName("block_reason")]
    public string BlockReason { get; init; } = "";

    [JsonPropertyName("blocking_supported")]
    public bool BlockingSupported { get; init; }

    [JsonPropertyName("blocking_mode")]
    public string BlockingMode { get; init; } = "detect_only";
}

public sealed class NetworkPortInfo
{
    [JsonPropertyName("port")]
    public int Port { get; init; }

    [JsonPropertyName("protocol")]
    public string Protocol { get; init; } = "tcp";

    [JsonPropertyName("process")]
    public string Process { get; init; } = "";

    [JsonPropertyName("pid")]
    public int Pid { get; init; }

    [JsonPropertyName("address")]
    public string Address { get; init; } = "";
}

public sealed class NetworkConnectionInfo
{
    [JsonPropertyName("remote_ip")]
    public string RemoteIp { get; init; } = "";

    [JsonPropertyName("remote_port")]
    public int RemotePort { get; init; }

    [JsonPropertyName("protocol")]
    public string Protocol { get; init; } = "tcp";

    [JsonPropertyName("process")]
    public string Process { get; init; } = "";

    [JsonPropertyName("pid")]
    public int Pid { get; init; }

    [JsonPropertyName("domain")]
    public string Domain { get; init; } = "";
}

public sealed class NetworkActivityRequest
{
    [JsonPropertyName("machine_id")]
    public required string MachineId { get; init; }

    [JsonPropertyName("timestamp")]
    public required string Timestamp { get; init; }

    [JsonPropertyName("bytes_sent")]
    public long BytesSent { get; init; }

    [JsonPropertyName("bytes_recv")]
    public long BytesRecv { get; init; }

    [JsonPropertyName("total_sent")]
    public long TotalSent { get; init; }

    [JsonPropertyName("total_recv")]
    public long TotalRecv { get; init; }

    [JsonPropertyName("listen_count")]
    public int ListenCount { get; init; }

    [JsonPropertyName("conn_count")]
    public int ConnCount { get; init; }

    [JsonPropertyName("listening_ports")]
    public IReadOnlyList<NetworkPortInfo> ListeningPorts { get; init; } = Array.Empty<NetworkPortInfo>();

    [JsonPropertyName("connections")]
    public IReadOnlyList<NetworkConnectionInfo> Connections { get; init; } = Array.Empty<NetworkConnectionInfo>();
}

public sealed class AgentHealth
{
    [JsonPropertyName("runtime")]
    public string Runtime { get; init; } = "dotnet-native-aot";

    [JsonPropertyName("transport")]
    public string Transport { get; init; } = "http";

    [JsonPropertyName("websocket_enabled")]
    public bool WebSocketEnabled { get; init; }

    [JsonPropertyName("status")]
    public string Status { get; init; } = "ok";
}

public sealed class BackendErrorResponse
{
    [JsonPropertyName("detail")]
    public string Detail { get; init; } = "";
}

public sealed class HeartbeatResponse
{
    [JsonPropertyName("status")]
    public string Status { get; init; } = "";

    [JsonPropertyName("server_time")]
    public string ServerTime { get; init; } = "";

    [JsonPropertyName("config")]
    public JsonElement Config { get; init; }
}

public sealed class PhishingCheckRequest
{
    [JsonPropertyName("machine_id")]
    public required string MachineId { get; init; }

    [JsonPropertyName("url")]
    public required string Url { get; init; }

    [JsonPropertyName("user_id")]
    public string UserId { get; init; } = "";

    [JsonPropertyName("app_name")]
    public string AppName { get; init; } = "";

    [JsonPropertyName("process_name")]
    public string ProcessName { get; init; } = "";

    [JsonPropertyName("page_title")]
    public string PageTitle { get; init; } = "";

    [JsonPropertyName("channel")]
    public string Channel { get; init; } = "browser";

    [JsonPropertyName("initial_agent_verdict")]
    public string InitialAgentVerdict { get; init; } = "clean";

    [JsonPropertyName("local_features")]
    public Dictionary<string, object?> LocalFeatures { get; init; } = new();
}

public sealed class PhishingCheckResponse
{
    [JsonPropertyName("verdict")]
    public string Verdict { get; init; } = "";

    [JsonPropertyName("action")]
    public string Action { get; init; } = "";

    [JsonPropertyName("severity")]
    public string Severity { get; init; } = "low";

    [JsonPropertyName("risk_score")]
    public double RiskScore { get; init; }

    [JsonPropertyName("confidence")]
    public double Confidence { get; init; }

    [JsonPropertyName("reason_codes")]
    public IReadOnlyList<string> ReasonCodes { get; init; } = Array.Empty<string>();

    [JsonPropertyName("policy_version")]
    public int PolicyVersion { get; init; }

    [JsonPropertyName("policy_hash")]
    public string PolicyHash { get; init; } = "";
}

public sealed class PhishingEventRequest
{
    [JsonPropertyName("machine_id")]
    public required string MachineId { get; init; }

    [JsonPropertyName("timestamp")]
    public required string Timestamp { get; init; }

    [JsonPropertyName("event_type")]
    public string EventType { get; init; } = "browser_visit";

    [JsonPropertyName("channel")]
    public string Channel { get; init; } = "browser";

    [JsonPropertyName("url")]
    public string Url { get; init; } = "";

    [JsonPropertyName("domain")]
    public string Domain { get; init; } = "";

    [JsonPropertyName("page_title")]
    public string PageTitle { get; init; } = "";

    [JsonPropertyName("app_name")]
    public string AppName { get; init; } = "";

    [JsonPropertyName("process_name")]
    public string ProcessName { get; init; } = "";

    [JsonPropertyName("remote_ip")]
    public string RemoteIp { get; init; } = "";

    [JsonPropertyName("destination_label")]
    public string DestinationLabel { get; init; } = "";

    [JsonPropertyName("actor_username")]
    public string ActorUsername { get; init; } = "";

    [JsonPropertyName("policy_version")]
    public int? PolicyVersion { get; init; }

    [JsonPropertyName("policy_hash")]
    public string PolicyHash { get; init; } = "";

    [JsonPropertyName("rule_id")]
    public string RuleId { get; init; } = "";

    [JsonPropertyName("risk_score")]
    public double? RiskScore { get; init; }

    [JsonPropertyName("confidence")]
    public double? Confidence { get; init; }

    [JsonPropertyName("severity")]
    public string Severity { get; init; } = "low";

    [JsonPropertyName("action_taken")]
    public string ActionTaken { get; init; } = "monitor";

    [JsonPropertyName("action_result")]
    public string ActionResult { get; init; } = "observed";

    [JsonPropertyName("reason_codes")]
    public IReadOnlyList<string> ReasonCodes { get; init; } = Array.Empty<string>();

    [JsonPropertyName("evidence")]
    public IReadOnlyList<Dictionary<string, object?>> Evidence { get; init; } = Array.Empty<Dictionary<string, object?>>();

    [JsonPropertyName("unsupported_reason")]
    public string UnsupportedReason { get; init; } = "";
}

public sealed class DlpEventRequest
{
    [JsonPropertyName("machine_id")]
    public required string MachineId { get; init; }

    [JsonPropertyName("timestamp")]
    public required string Timestamp { get; init; }

    [JsonPropertyName("file_path")]
    public string FilePath { get; init; } = "";

    [JsonPropertyName("file_name")]
    public string FileName { get; init; } = "";

    [JsonPropertyName("file_ext")]
    public string FileExt { get; init; } = "";

    [JsonPropertyName("file_size")]
    public int FileSize { get; init; }

    [JsonPropertyName("risk")]
    public string Risk { get; init; } = "low";

    [JsonPropertyName("risk_level")]
    public string RiskLevel { get; init; } = "low";

    [JsonPropertyName("risk_score")]
    public int RiskScore { get; init; }

    [JsonPropertyName("findings")]
    public IReadOnlyList<Dictionary<string, object?>> Findings { get; init; } = Array.Empty<Dictionary<string, object?>>();

    [JsonPropertyName("destination")]
    public string Destination { get; init; } = "";

    [JsonPropertyName("event_type")]
    public string EventType { get; init; } = "browser_activity";

    [JsonPropertyName("channel")]
    public string Channel { get; init; } = "browser";

    [JsonPropertyName("policy_version")]
    public int? PolicyVersion { get; init; }

    [JsonPropertyName("confidence")]
    public double? Confidence { get; init; }

    [JsonPropertyName("action_taken")]
    public string ActionTaken { get; init; } = "monitor";

    [JsonPropertyName("action_result")]
    public string ActionResult { get; init; } = "observed";

    [JsonPropertyName("actor_username")]
    public string ActorUsername { get; init; } = "";

    [JsonPropertyName("app_name")]
    public string AppName { get; init; } = "";

    [JsonPropertyName("destination_type")]
    public string DestinationType { get; init; } = "web";

    [JsonPropertyName("content_fingerprint")]
    public string ContentFingerprint { get; init; } = "";

    [JsonPropertyName("enterprise_label")]
    public string EnterpriseLabel { get; init; } = "";

    [JsonPropertyName("sensitivity_score")]
    public int SensitivityScore { get; init; }

    [JsonPropertyName("label_source")]
    public string LabelSource { get; init; } = "native_dlp";

    [JsonPropertyName("label_reason")]
    public string LabelReason { get; init; } = "";

    [JsonPropertyName("block_candidate")]
    public bool BlockCandidate { get; init; }

    [JsonPropertyName("block_reason")]
    public string BlockReason { get; init; } = "";

    [JsonPropertyName("blocking_supported")]
    public bool BlockingSupported { get; init; }

    [JsonPropertyName("blocking_mode")]
    public string BlockingMode { get; init; } = "detect_only";
}

public sealed class BatchActivityRequest
{
    [JsonPropertyName("machine_id")]
    public required string MachineId { get; init; }

    [JsonPropertyName("events")]
    public required IReadOnlyList<BatchActivityEvent> Events { get; init; }
}

public sealed class BatchActivityEvent
{
    [JsonPropertyName("queue_id")]
    public required string QueueId { get; init; }

    [JsonPropertyName("event_type")]
    public required string EventType { get; init; }

    [JsonPropertyName("data")]
    public required JsonElement Data { get; init; }
}

public sealed class BatchActivityResponse
{
    [JsonPropertyName("status")]
    public string Status { get; init; } = "";

    [JsonPropertyName("processed")]
    public int Processed { get; init; }

    [JsonPropertyName("success_ids")]
    public IReadOnlyList<string> SuccessIds { get; init; } = Array.Empty<string>();

    [JsonPropertyName("failed_ids")]
    public IReadOnlyList<string> FailedIds { get; init; } = Array.Empty<string>();
}

public sealed class WebRtcSessionDescriptionPayload
{
    [JsonPropertyName("type")]
    public string Type { get; init; } = "";

    [JsonPropertyName("sdp")]
    public string Sdp { get; init; } = "";
}

public sealed class WebRtcIceCandidatePayload
{
    [JsonPropertyName("sdpMid")]
    public string SdpMid { get; init; } = "";

    [JsonPropertyName("sdpMLineIndex")]
    public int SdpMLineIndex { get; init; }

    [JsonPropertyName("candidate")]
    public string Candidate { get; init; } = "";
}

public sealed class WebRtcOfferSignal
{
    [JsonPropertyName("type")]
    public string Type { get; init; } = "webrtc_offer";

    [JsonPropertyName("session_id")]
    public required string SessionId { get; init; }

    [JsonPropertyName("sdp")]
    public required WebRtcSessionDescriptionPayload Sdp { get; init; }
}

public sealed class WebRtcIceSignal
{
    [JsonPropertyName("type")]
    public string Type { get; init; } = "webrtc_ice";

    [JsonPropertyName("session_id")]
    public required string SessionId { get; init; }

    [JsonPropertyName("candidate")]
    public required WebRtcIceCandidatePayload Candidate { get; init; }
}

public sealed class WebRtcEndSignal
{
    [JsonPropertyName("type")]
    public string Type { get; init; } = "webrtc_end";

    [JsonPropertyName("session_id")]
    public required string SessionId { get; init; }

    [JsonPropertyName("reason")]
    public string Reason { get; init; } = "";
}

public sealed class RemoteCommandResultSignal
{
    [JsonPropertyName("type")]
    public string Type { get; init; } = "remote_command";

    [JsonPropertyName("action")]
    public string Action { get; init; } = "";

    [JsonPropertyName("status")]
    public string Status { get; init; } = "sent";

    [JsonPropertyName("detail")]
    public string Detail { get; init; } = "";
}
