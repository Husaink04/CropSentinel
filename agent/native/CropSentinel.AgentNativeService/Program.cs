using CropSentinel.AgentNativeService;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Hosting.WindowsServices;
using Microsoft.Extensions.Logging;

var builder = Host.CreateApplicationBuilder(args);

if (WindowsServiceHelpers.IsWindowsService())
{
    builder.Services.AddWindowsService(options =>
    {
        options.ServiceName = "CropSentinel Agent";
    });
}

builder.Services.AddHostedService<ActiveSessionAgentSupervisorService>();

builder.Logging.ClearProviders();
builder.Logging.AddSimpleConsole(options =>
{
    options.TimestampFormat = "yyyy-MM-dd HH:mm:ss ";
    options.SingleLine = true;
});

await builder.Build().RunAsync();
