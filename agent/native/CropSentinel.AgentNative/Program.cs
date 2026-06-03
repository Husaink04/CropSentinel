using CropSentinel.AgentNative;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Hosting.WindowsServices;

var builder = Host.CreateApplicationBuilder(args);
LoadConfigEnv(builder.Configuration);
var agentOptions = AgentOptions.FromConfiguration(builder.Configuration);

if (WindowsServiceHelpers.IsWindowsService())
{
    builder.Services.AddWindowsService(options =>
    {
        options.ServiceName = "CropSentinel Native Agent";
    });
}

builder.Services.AddSingleton(Options.Create(agentOptions));

builder.Services.AddHttpClient<BackendClient>();
builder.Services.AddSingleton<IMachineIdentityProvider, MachineIdentityProvider>();
builder.Services.AddSingleton<IAgentClock, AgentClock>();
builder.Services.AddSingleton<IHeartbeatSignalProvider, WindowsHeartbeatSignalProvider>();
builder.Services.AddSingleton<RuntimePolicyStore>();
builder.Services.AddSingleton<NativePhishingProtection>();
builder.Services.AddSingleton<NativeDlpEngine>();
builder.Services.AddSingleton<OfflineEventQueue>();
builder.Services.AddSingleton<NativeRemoteCommandExecutor>();
builder.Services.AddSingleton<NativeWebRtcSessionManager>();
if (OperatingSystem.IsWindows())
{
    builder.Services.AddSingleton<IBrowserActivityReader, WindowsBrowserActivityReader>();
    builder.Services.AddSingleton<IInputActivityTracker, WindowsInputActivityTracker>();
    builder.Services.AddSingleton<IScreenshotProvider, WindowsScreenshotProvider>();
    builder.Services.AddSingleton<INetworkActivityCollector, WindowsNetworkActivityCollector>();
    builder.Services.AddSingleton<IFileActivityCollector, WindowsFileActivityCollector>();
    builder.Services.AddSingleton<NativeRemoteInputExecutor>();
    builder.Services.AddSingleton<NativeFileTransferHandler>();
}
else
{
    builder.Services.AddSingleton<IBrowserActivityReader, NoopBrowserActivityReader>();
    builder.Services.AddSingleton<IInputActivityTracker, NoopInputActivityTracker>();
    builder.Services.AddSingleton<IScreenshotProvider, NoopScreenshotProvider>();
    builder.Services.AddSingleton<INetworkActivityCollector, NoopNetworkActivityCollector>();
    builder.Services.AddSingleton<IFileActivityCollector, NoopFileActivityCollector>();
    builder.Services.AddSingleton<NativeRemoteInputExecutor>();
    builder.Services.AddSingleton<NativeFileTransferHandler>();
}
builder.Services.AddHostedService<AgentWorker>();

builder.Logging.ClearProviders();
builder.Logging.AddSimpleConsole(options =>
{
    options.TimestampFormat = "yyyy-MM-dd HH:mm:ss ";
    options.SingleLine = true;
});

await builder.Build().RunAsync();

static void LoadConfigEnv(ConfigurationManager configuration)
{
    var programData = Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData);
    var configPath = Path.Combine(programData, "CropSentinel", "config.env");

    if (!File.Exists(configPath))
    {
        configPath = Path.Combine(AppContext.BaseDirectory, "config.env");
    }

    if (!File.Exists(configPath))
    {
        return;
    }

    var settings = new Dictionary<string, string>();
    foreach (var line in File.ReadLines(configPath))
    {
        var trimmed = line.Trim();
        if (string.IsNullOrWhiteSpace(trimmed) || trimmed.StartsWith("#"))
        {
            continue;
        }

        var idx = trimmed.IndexOf('=');
        if (idx <= 0)
        {
            continue;
        }

        var key = trimmed[..idx].Trim();
        var val = trimmed[(idx + 1)..].Trim();

        // Strip quotes if present
        if (val.Length >= 2 && val.StartsWith("\"") && val.EndsWith("\""))
        {
            val = val[1..^1].Trim();
        }
        else if (val.Length >= 2 && val.StartsWith("'") && val.EndsWith("'"))
        {
            val = val[1..^1].Trim();
        }

        switch (key)
        {
            case "CROPSENTINEL_SERVER":
            case "CROPPRO_SERVER":
                settings["CropSentinelAgent:ApiBaseUrl"] = val;
                if (val.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
                {
                    settings["CropSentinelAgent:WebSocketBaseUrl"] = "wss://" + val[8..];
                }
                else if (val.StartsWith("http://", StringComparison.OrdinalIgnoreCase))
                {
                    settings["CropSentinelAgent:WebSocketBaseUrl"] = "ws://" + val[7..];
                }
                break;

            case "CROPSENTINEL_ENROLL_TOKEN":
            case "CROPPRO_ENROLL_TOKEN":
                settings["CropSentinelAgent:EnrollmentToken"] = val;
                break;

            case "CROPSENTINEL_AGENT_KEY":
            case "CROPPRO_AGENT_KEY":
                settings["CropSentinelAgent:AgentApiKey"] = val;
                break;

            case "CROPSENTINEL_SCREENSHOT_INTERVAL":
            case "CROPPRO_SCREENSHOT_INTERVAL":
                settings["CropSentinelAgent:ScreenshotIntervalSeconds"] = val;
                break;

            case "CROPSENTINEL_SYNC_INTERVAL":
            case "CROPPRO_SYNC_INTERVAL":
                settings["CropSentinelAgent:BrowserSyncIntervalSeconds"] = val;
                break;
        }
    }

    if (settings.Count > 0)
    {
        configuration.AddInMemoryCollection(settings!);
    }
}
