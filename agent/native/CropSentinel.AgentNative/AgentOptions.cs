using Microsoft.Extensions.Configuration;

namespace CropSentinel.AgentNative;

public sealed class AgentOptions
{
    public const string SectionName = "CropSentinelAgent";

    public string ApiBaseUrl { get; set; } = "http://localhost:8000";
    public string WebSocketBaseUrl { get; set; } = "ws://localhost:8000";
    public string AgentApiKey { get; set; } = "";
    public string EnrollmentToken { get; set; } = "";
    public string MachineId { get; set; } = "";
    public string Hostname { get; set; } = Environment.MachineName;
    public string Os { get; set; } = "Windows";
    public string OsVersion { get; set; } = Environment.OSVersion.VersionString;
    public string Username { get; set; } = Environment.UserName;
    public string IpAddress { get; set; } = "";
    public string MacAddress { get; set; } = "";
    public bool ConsentGiven { get; set; } = true;
    public int HeartbeatIntervalSeconds { get; set; } = 30;
    public int AppTrackerIntervalSeconds { get; set; } = 5;
    public int BrowserSyncIntervalSeconds { get; set; } = 30;
    public int InputBucketSeconds { get; set; } = 30;
    public int ScreenshotIntervalSeconds { get; set; } = 180;
    public int NetworkIntervalSeconds { get; set; } = 60;
    public int WebRtcFramesPerSecond { get; set; } = 6;
    public string WebRtcTurnUrl { get; set; } = "";
    public string WebRtcTurnUsername { get; set; } = "";
    public string WebRtcTurnPassword { get; set; } = "";
    public string AgentVersion { get; set; } = "0.1.0-native";
    public string DataDirectory { get; set; } = "";

    public string ResolveDataDirectory()
    {
        if (!string.IsNullOrWhiteSpace(DataDirectory))
        {
            return DataDirectory;
        }

        var root = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);
        if (string.IsNullOrWhiteSpace(root))
        {
            root = AppContext.BaseDirectory;
        }
        return Path.Combine(root, "CropSentinel", "NativeAgent");
    }

    public static AgentOptions FromConfiguration(IConfiguration configuration)
    {
        var section = configuration.GetSection(SectionName);
        return new AgentOptions
        {
            ApiBaseUrl = section["ApiBaseUrl"] ?? "http://localhost:8000",
            WebSocketBaseUrl = section["WebSocketBaseUrl"] ?? "ws://localhost:8000",
            AgentApiKey = section["AgentApiKey"] ?? "",
            EnrollmentToken = section["EnrollmentToken"] ?? "",
            MachineId = section["MachineId"] ?? "",
            Hostname = section["Hostname"] ?? Environment.MachineName,
            Os = section["Os"] ?? "Windows",
            OsVersion = section["OsVersion"] ?? Environment.OSVersion.VersionString,
            Username = section["Username"] ?? Environment.UserName,
            IpAddress = section["IpAddress"] ?? "",
            MacAddress = section["MacAddress"] ?? "",
            ConsentGiven = ParseBool(section["ConsentGiven"], true),
            HeartbeatIntervalSeconds = ParseInt(section["HeartbeatIntervalSeconds"], 30),
            AppTrackerIntervalSeconds = ParseInt(section["AppTrackerIntervalSeconds"], 5),
            BrowserSyncIntervalSeconds = ParseInt(section["BrowserSyncIntervalSeconds"], 30),
            InputBucketSeconds = ParseInt(section["InputBucketSeconds"], 30),
            ScreenshotIntervalSeconds = ParseInt(section["ScreenshotIntervalSeconds"], 180),
            NetworkIntervalSeconds = ParseInt(section["NetworkIntervalSeconds"], 60),
            WebRtcFramesPerSecond = ParseInt(section["WebRtcFramesPerSecond"], 6),
            WebRtcTurnUrl = section["WebRtcTurnUrl"] ?? "",
            WebRtcTurnUsername = section["WebRtcTurnUsername"] ?? "",
            WebRtcTurnPassword = section["WebRtcTurnPassword"] ?? "",
            AgentVersion = section["AgentVersion"] ?? "0.1.0-native",
            DataDirectory = section["DataDirectory"] ?? "",
        };
    }

    private static bool ParseBool(string? value, bool fallback)
    {
        return bool.TryParse(value, out var parsed) ? parsed : fallback;
    }

    private static int ParseInt(string? value, int fallback)
    {
        return int.TryParse(value, out var parsed) ? parsed : fallback;
    }
}
