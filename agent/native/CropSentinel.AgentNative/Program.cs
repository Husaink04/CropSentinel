using CropSentinel.AgentNative;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Microsoft.Extensions.Hosting.WindowsServices;

var builder = Host.CreateApplicationBuilder(args);
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
