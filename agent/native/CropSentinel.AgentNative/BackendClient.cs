using System.Net.Http.Json;
using System.Net.WebSockets;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace CropSentinel.AgentNative;

public sealed class BackendClient
{
    private readonly HttpClient _httpClient;
    private readonly AgentOptions _options;
    private readonly ILogger<BackendClient> _logger;

    public BackendClient(HttpClient httpClient, IOptions<AgentOptions> options, ILogger<BackendClient> logger)
    {
        _httpClient = httpClient;
        _options = options.Value;
        _logger = logger;
        _httpClient.BaseAddress = new Uri(NormalizeBaseUrl(_options.ApiBaseUrl));
        _httpClient.DefaultRequestHeaders.Add("X-CropPro-Agent-Key", _options.AgentApiKey);
        if (!string.IsNullOrWhiteSpace(_options.EnrollmentToken))
        {
            _httpClient.DefaultRequestHeaders.Add("X-CropSentinel-Enroll-Token", _options.EnrollmentToken);
        }
    }

    public async Task<RegistrationResponse> RegisterAsync(MachineRegisterRequest request, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/machines/register",
            request,
            AgentJsonSerializerContext.Default.MachineRegisterRequest,
            cancellationToken);
        await EnsureSuccessAsync(response, "machine registration", cancellationToken);
        var payload = await response.Content.ReadFromJsonAsync(
            AgentJsonSerializerContext.Default.RegistrationResponse,
            cancellationToken);
        return payload ?? new RegistrationResponse();
    }

    public async Task<HeartbeatResponse> SendHeartbeatAsync(HeartbeatRequest request, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/activity/heartbeat",
            request,
            AgentJsonSerializerContext.Default.HeartbeatRequest,
            cancellationToken);
        await EnsureSuccessAsync(response, "heartbeat", cancellationToken);
        var payload = await response.Content.ReadFromJsonAsync(
            AgentJsonSerializerContext.Default.HeartbeatResponse,
            cancellationToken);
        return payload ?? new HeartbeatResponse();
    }

    public async Task SendApplicationActivityAsync(AppActivityRequest request, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/activity/application",
            request,
            AgentJsonSerializerContext.Default.AppActivityRequest,
            cancellationToken);
        await EnsureSuccessAsync(response, "application activity", cancellationToken);
    }

    public async Task SendBrowserActivityAsync(BrowserActivityRequest request, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/activity/browser",
            request,
            AgentJsonSerializerContext.Default.BrowserActivityRequest,
            cancellationToken);
        await EnsureSuccessAsync(response, "browser activity", cancellationToken);
    }

    public async Task SendInputActivityAsync(InputActivityRequest request, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/activity/input",
            request,
            AgentJsonSerializerContext.Default.InputActivityRequest,
            cancellationToken);
        await EnsureSuccessAsync(response, "input activity", cancellationToken);
    }

    public async Task SendScreenshotAsync(ScreenshotRequest request, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/activity/screenshot",
            request,
            AgentJsonSerializerContext.Default.ScreenshotRequest,
            cancellationToken);
        await EnsureSuccessAsync(response, "screenshot activity", cancellationToken);
    }

    public async Task SendNetworkActivityAsync(NetworkActivityRequest request, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/activity/network",
            request,
            AgentJsonSerializerContext.Default.NetworkActivityRequest,
            cancellationToken);
        await EnsureSuccessAsync(response, "network activity", cancellationToken);
    }

    public async Task SendFileActivityAsync(FileActivityRequest request, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/activity/file",
            request,
            AgentJsonSerializerContext.Default.FileActivityRequest,
            cancellationToken);
        await EnsureSuccessAsync(response, "file activity", cancellationToken);
    }

    public async Task SendDlpEventAsync(DlpEventRequest request, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/dlp/events",
            request,
            AgentJsonSerializerContext.Default.DlpEventRequest,
            cancellationToken);
        await EnsureSuccessAsync(response, "dlp event", cancellationToken);
    }

    public async Task<PhishingCheckResponse> CheckPhishingUrlAsync(PhishingCheckRequest request, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/phishing/check",
            request,
            AgentJsonSerializerContext.Default.PhishingCheckRequest,
            cancellationToken);
        await EnsureSuccessAsync(response, "phishing url check", cancellationToken);
        var payload = await response.Content.ReadFromJsonAsync(
            AgentJsonSerializerContext.Default.PhishingCheckResponse,
            cancellationToken);
        return payload ?? new PhishingCheckResponse();
    }

    public async Task SendPhishingActivityAsync(PhishingEventRequest request, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/activity/phishing",
            request,
            AgentJsonSerializerContext.Default.PhishingEventRequest,
            cancellationToken);
        await EnsureSuccessAsync(response, "phishing activity", cancellationToken);
    }

    public async Task<BatchActivityResponse> SendBatchActivityAsync(BatchActivityRequest request, CancellationToken cancellationToken)
    {
        using var response = await _httpClient.PostAsJsonAsync(
            "/api/activity/batch",
            request,
            AgentJsonSerializerContext.Default.BatchActivityRequest,
            cancellationToken);
        await EnsureSuccessAsync(response, "batch activity", cancellationToken);
        var payload = await response.Content.ReadFromJsonAsync(
            AgentJsonSerializerContext.Default.BatchActivityResponse,
            cancellationToken);
        return payload ?? new BatchActivityResponse();
    }

    public async Task<ClientWebSocket> ConnectWebSocketAsync(string machineId, CancellationToken cancellationToken)
    {
        var ws = new ClientWebSocket();
        ws.Options.SetRequestHeader("X-CropPro-Agent-Key", _options.AgentApiKey);
        if (!string.IsNullOrWhiteSpace(_options.EnrollmentToken))
        {
            ws.Options.SetRequestHeader("X-CropSentinel-Enroll-Token", _options.EnrollmentToken);
        }

        var target = new Uri($"{NormalizeBaseUrl(_options.WebSocketBaseUrl).TrimEnd('/')}/ws/agent/{Uri.EscapeDataString(machineId)}");
        await ws.ConnectAsync(target, cancellationToken);
        _logger.LogInformation("Connected agent websocket to {Target}", target);
        return ws;
    }

    private static string NormalizeBaseUrl(string value)
    {
        return string.IsNullOrWhiteSpace(value) ? "http://localhost:8000" : value.TrimEnd('/');
    }

    private static async Task EnsureSuccessAsync(HttpResponseMessage response, string operation, CancellationToken cancellationToken)
    {
        if (response.IsSuccessStatusCode)
        {
            return;
        }

        var detail = "";
        try
        {
            var error = await response.Content.ReadFromJsonAsync(
                AgentJsonSerializerContext.Default.BackendErrorResponse,
                cancellationToken);
            detail = error?.Detail ?? "";
        }
        catch
        {
            detail = await response.Content.ReadAsStringAsync(cancellationToken);
        }

        throw new InvalidOperationException(
            $"Backend rejected {operation}: {(int)response.StatusCode} {response.ReasonPhrase}. {detail}".Trim());
    }
}
