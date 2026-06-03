using System.Collections.Concurrent;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace CropSentinel.AgentNative;

public sealed partial class AgentWorker : BackgroundService
{
    private readonly ConcurrentDictionary<string, string> _deleteBackupCache = new(StringComparer.OrdinalIgnoreCase);

    [LibraryImport("user32.dll", EntryPoint = "MessageBoxW", StringMarshalling = StringMarshalling.Utf16)]
    private static partial int MessageBoxW(nint hWnd, string lpText, string lpCaption, uint uType);
    private readonly BackendClient _backendClient;
    private readonly IMachineIdentityProvider _machineIdentityProvider;
    private readonly IAgentClock _clock;
    private readonly IHeartbeatSignalProvider _heartbeatSignalProvider;
    private readonly IBrowserActivityReader _browserActivityReader;
    private readonly IInputActivityTracker _inputActivityTracker;
    private readonly IScreenshotProvider _screenshotProvider;
    private readonly INetworkActivityCollector _networkActivityCollector;
    private readonly IFileActivityCollector _fileActivityCollector;
    private readonly RuntimePolicyStore _runtimePolicyStore;
    private readonly NativePhishingProtection _phishingProtection;
    private readonly NativeDlpEngine _dlpEngine;
    private readonly OfflineEventQueue _offlineEventQueue;
    private readonly NativeRemoteCommandExecutor _remoteCommandExecutor;
    private readonly NativeWebRtcSessionManager _webRtcSessionManager;
    private readonly AgentOptions _options;
    private readonly ILogger<AgentWorker> _logger;

    public AgentWorker(
        BackendClient backendClient,
        IMachineIdentityProvider machineIdentityProvider,
        IAgentClock clock,
        IHeartbeatSignalProvider heartbeatSignalProvider,
        IBrowserActivityReader browserActivityReader,
        IInputActivityTracker inputActivityTracker,
        IScreenshotProvider screenshotProvider,
        INetworkActivityCollector networkActivityCollector,
        IFileActivityCollector fileActivityCollector,
        RuntimePolicyStore runtimePolicyStore,
        NativePhishingProtection phishingProtection,
        NativeDlpEngine dlpEngine,
        OfflineEventQueue offlineEventQueue,
        NativeRemoteCommandExecutor remoteCommandExecutor,
        NativeWebRtcSessionManager webRtcSessionManager,
        IOptions<AgentOptions> options,
        ILogger<AgentWorker> logger)
    {
        _backendClient = backendClient;
        _machineIdentityProvider = machineIdentityProvider;
        _clock = clock;
        _heartbeatSignalProvider = heartbeatSignalProvider;
        _browserActivityReader = browserActivityReader;
        _inputActivityTracker = inputActivityTracker;
        _screenshotProvider = screenshotProvider;
        _networkActivityCollector = networkActivityCollector;
        _fileActivityCollector = fileActivityCollector;
        _runtimePolicyStore = runtimePolicyStore;
        _phishingProtection = phishingProtection;
        _dlpEngine = dlpEngine;
        _offlineEventQueue = offlineEventQueue;
        _remoteCommandExecutor = remoteCommandExecutor;
        _webRtcSessionManager = webRtcSessionManager;
        _options = options.Value;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        ValidateOptions(_options);

        if (string.IsNullOrWhiteSpace(_options.IpAddress))
        {
            _options.IpAddress = GetLocalIpAddress();
        }
        if (string.IsNullOrWhiteSpace(_options.MacAddress))
        {
            _options.MacAddress = GetMacAddress();
        }
        if (string.IsNullOrWhiteSpace(_options.Hostname))
        {
            _options.Hostname = GetHostname();
        }
        _options.Username = GetActiveUsername(_options.Username);

        var machineId = _machineIdentityProvider.GetMachineId();
        _logger.LogInformation("Starting native agent bootstrap for machine {MachineId}", machineId);

        var registration = await _backendClient.RegisterAsync(
            new MachineRegisterRequest
            {
                MachineId = machineId,
                Hostname = _options.Hostname,
                Os = _options.Os,
                OsVersion = _options.OsVersion,
                Username = _options.Username,
                IpAddress = _options.IpAddress,
                MacAddress = _options.MacAddress,
                ConsentGiven = _options.ConsentGiven,
                ConsentTimestamp = _clock.UtcNowIso(),
                FirstSeen = _clock.UtcNowIso(),
                AgentVersion = _options.AgentVersion,
            },
            stoppingToken);

        _logger.LogInformation("Registered machine {MachineId} with status {Status}", registration.MachineId, registration.Status);

        _inputActivityTracker.Start();
        _fileActivityCollector.Start();

        try
        {
            await Task.WhenAll(
                RunHeartbeatLoopAsync(machineId, stoppingToken),
                RunApplicationLoopAsync(machineId, stoppingToken),
                RunBrowserLoopAsync(machineId, stoppingToken),
                RunInputLoopAsync(machineId, stoppingToken),
                RunScreenshotLoopAsync(machineId, stoppingToken),
                RunNetworkLoopAsync(machineId, stoppingToken),
                RunFileLoopAsync(machineId, stoppingToken),
                RunWebSocketLoopAsync(machineId, stoppingToken),
                RunOfflineDrainLoopAsync(machineId, stoppingToken));
        }
        finally
        {
            _inputActivityTracker.Dispose();
            _fileActivityCollector.Dispose();
            await _webRtcSessionManager.DisposeAsync();
        }
    }

    private async Task SendHeartbeatAsync(string machineId, CancellationToken cancellationToken)
    {
        var snapshot = _heartbeatSignalProvider.Capture();
        var request = new HeartbeatRequest
        {
            MachineId = machineId,
            Timestamp = _clock.UtcNowIso(),
            CpuPercent = snapshot.CpuPercent,
            MemoryPercent = snapshot.MemoryPercent,
            ActiveApp = snapshot.ActiveApp,
            ActiveBrowser = snapshot.ActiveBrowser,
            ActiveUrl = snapshot.ActiveUrl,
            IdleSeconds = snapshot.IdleSeconds,
            AgentHealth = new AgentHealth
            {
                Runtime = "dotnet-native-aot",
                Transport = "http",
                WebSocketEnabled = true,
                Status = "ok",
            },
        };

        var response = await _backendClient.SendHeartbeatAsync(request, cancellationToken);
        _runtimePolicyStore.UpdateFromHeartbeatConfig(response.Config);
        _logger.LogInformation("Heartbeat accepted for machine {MachineId}. Status={Status}", machineId, response.Status);
    }

    private async Task RunHeartbeatLoopAsync(string machineId, CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(Math.Max(15, _options.HeartbeatIntervalSeconds)));
        do
        {
            try
            {
                await SendHeartbeatAsync(machineId, cancellationToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _offlineEventQueue.Enqueue("heartbeat", new HeartbeatRequest
                {
                    MachineId = machineId,
                    Timestamp = _clock.UtcNowIso(),
                    CpuPercent = 0,
                    MemoryPercent = 0,
                    IdleSeconds = 0,
                });
                _logger.LogWarning(ex, "Heartbeat loop iteration failed for {MachineId}", machineId);
            }
        }
        while (await timer.WaitForNextTickAsync(cancellationToken));
    }

    private async Task RunApplicationLoopAsync(string machineId, CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(Math.Max(2, _options.AppTrackerIntervalSeconds)));
        HeartbeatSignalSnapshot? previous = null;
        do
        {
            try
            {
                var snapshot = _heartbeatSignalProvider.Capture();
                if (previous is not null && ShouldEmitApplicationActivity(previous, snapshot))
                {
                    await _backendClient.SendApplicationActivityAsync(
                        new AppActivityRequest
                        {
                            MachineId = machineId,
                            Timestamp = _clock.UtcNowIso(),
                            AppName = previous.ActiveApp,
                            WindowTitle = previous.WindowTitle,
                            ProcessName = previous.ProcessName,
                            DurationSeconds = Math.Max(1, _options.AppTrackerIntervalSeconds),
                            IsActive = true,
                        },
                        cancellationToken);
                }
                previous = snapshot;
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                if (previous is not null)
                {
                    _offlineEventQueue.Enqueue("app", new AppActivityRequest
                    {
                        MachineId = machineId,
                        Timestamp = _clock.UtcNowIso(),
                        AppName = previous.ActiveApp,
                        WindowTitle = previous.WindowTitle,
                        ProcessName = previous.ProcessName,
                        DurationSeconds = Math.Max(1, _options.AppTrackerIntervalSeconds),
                        IsActive = true,
                    });
                }
                _logger.LogWarning(ex, "Application activity loop iteration failed for {MachineId}", machineId);
            }
        }
        while (await timer.WaitForNextTickAsync(cancellationToken));
    }

    private static bool ShouldEmitApplicationActivity(HeartbeatSignalSnapshot previous, HeartbeatSignalSnapshot current)
    {
        if (string.IsNullOrWhiteSpace(previous.ActiveApp) || previous.ActiveApp.Equals("Unknown", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        return !string.Equals(previous.ActiveApp, current.ActiveApp, StringComparison.OrdinalIgnoreCase)
            || !string.Equals(previous.WindowTitle, current.WindowTitle, StringComparison.Ordinal);
    }

    private async Task RunBrowserLoopAsync(string machineId, CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(Math.Max(15, _options.BrowserSyncIntervalSeconds)));
        var sinceUtc = DateTimeOffset.UtcNow.AddMinutes(-10);

        do
        {
            try
            {
                var entries = _browserActivityReader.ReadRecent(sinceUtc);
                var maxSeen = sinceUtc;
                var policy = _runtimePolicyStore.Snapshot();
                foreach (var entry in entries)
                {
                    var browserRequest = new BrowserActivityRequest
                    {
                        MachineId = machineId,
                        Timestamp = entry.Timestamp,
                        Browser = entry.Browser,
                        Url = entry.Url,
                        Title = entry.Title,
                        Domain = entry.Domain,
                        DurationSeconds = 0,
                    };

                    try
                    {
                        await _backendClient.SendBrowserActivityAsync(browserRequest, cancellationToken);
                    }
                    catch
                    {
                        _offlineEventQueue.Enqueue("browser", browserRequest);
                    }

                    var phishingVerdict = _phishingProtection.Evaluate(entry, policy.Phishing, $"{entry.Browser}.exe");
                    if (phishingVerdict.Verdict is "suspicious" or "malicious")
                    {
                        var phishingRequest = new PhishingEventRequest
                        {
                            MachineId = machineId,
                            Timestamp = entry.Timestamp,
                            Url = entry.Url,
                            Domain = entry.Domain,
                            PageTitle = entry.Title,
                            AppName = entry.Browser,
                            ProcessName = $"{entry.Browser}.exe",
                            ActorUsername = _options.Username,
                            PolicyVersion = policy.Phishing.PolicyVersion,
                            PolicyHash = policy.Phishing.PolicyHash,
                            RiskScore = phishingVerdict.RiskScore,
                            Confidence = phishingVerdict.Confidence,
                            Severity = phishingVerdict.Severity,
                            ActionTaken = phishingVerdict.ActionTaken,
                            ActionResult = phishingVerdict.ActionResult,
                            ReasonCodes = phishingVerdict.ReasonCodes,
                            UnsupportedReason = phishingVerdict.UnsupportedReason,
                        };

                        try
                        {
                            var checkedVerdict = await _backendClient.CheckPhishingUrlAsync(
                                new PhishingCheckRequest
                                {
                                    MachineId = machineId,
                                    Url = entry.Url,
                                    UserId = _options.Username,
                                    AppName = entry.Browser,
                                    ProcessName = $"{entry.Browser}.exe",
                                    PageTitle = entry.Title,
                                    InitialAgentVerdict = phishingVerdict.Verdict,
                                    LocalFeatures = phishingVerdict.Features,
                                },
                                cancellationToken);

                            phishingRequest = new PhishingEventRequest
                            {
                                MachineId = phishingRequest.MachineId,
                                Timestamp = phishingRequest.Timestamp,
                                EventType = phishingRequest.EventType,
                                Channel = phishingRequest.Channel,
                                Url = phishingRequest.Url,
                                Domain = phishingRequest.Domain,
                                PageTitle = phishingRequest.PageTitle,
                                AppName = phishingRequest.AppName,
                                ProcessName = phishingRequest.ProcessName,
                                RemoteIp = phishingRequest.RemoteIp,
                                DestinationLabel = phishingRequest.DestinationLabel,
                                ActorUsername = phishingRequest.ActorUsername,
                                PolicyVersion = checkedVerdict.PolicyVersion,
                                PolicyHash = checkedVerdict.PolicyHash,
                                RuleId = phishingRequest.RuleId,
                                RiskScore = checkedVerdict.RiskScore,
                                Confidence = checkedVerdict.Confidence,
                                Severity = checkedVerdict.Severity,
                                ActionTaken = checkedVerdict.Action,
                                ActionResult = phishingRequest.ActionResult,
                                ReasonCodes = checkedVerdict.ReasonCodes,
                                Evidence = phishingRequest.Evidence,
                                UnsupportedReason = phishingRequest.UnsupportedReason,
                            };
                        }
                        catch
                        {
                        }

                        try
                        {
                            await _backendClient.SendPhishingActivityAsync(phishingRequest, cancellationToken);
                        }
                        catch
                        {
                            _offlineEventQueue.Enqueue("phishing_alert", phishingRequest);
                        }

                        if (string.Equals(phishingRequest.ActionTaken, "warn_user", StringComparison.OrdinalIgnoreCase)
                            || string.Equals(phishingRequest.ActionTaken, "block", StringComparison.OrdinalIgnoreCase))
                        {
                            var severity = phishingRequest.Severity;
                            var domain = phishingRequest.Domain;
                            var reasons = string.Join(", ", phishingRequest.ReasonCodes.Take(3));
                            if (string.IsNullOrWhiteSpace(reasons))
                            {
                                reasons = "suspicious activity";
                            }
                            var warningText = $"CropSentinel detected a {severity.ToUpper()} phishing risk.\n\n" +
                                              $"Domain: {domain}\n" +
                                              $"Reason: {reasons}\n\n" +
                                              "Do not enter credentials or download files.\n" +
                                              "Close the page and contact your administrator if this was unexpected.";

                            _ = Task.Run(() =>
                            {
                                try
                                {
                                    MessageBoxW(
                                        IntPtr.Zero,
                                        warningText,
                                        "CropSentinel Phishing Warning",
                                        0x00200030); // MB_OK | MB_ICONWARNING | MB_SERVICE_NOTIFICATION
                                }
                                catch {}
                            });
                        }
                    }

                    var dlpResult = _dlpEngine.ScanText($"{entry.Title}\n{entry.Url}", policy.Dlp);
                    if (dlpResult.Matched)
                    {
                        _offlineEventQueue.Enqueue("dlp_alert", new DlpEventRequest
                        {
                            MachineId = machineId,
                            Timestamp = entry.Timestamp,
                            FilePath = entry.Url,
                            FileName = entry.Domain,
                            Risk = dlpResult.RiskLevel,
                            RiskLevel = dlpResult.RiskLevel,
                            RiskScore = dlpResult.RiskScore,
                            Findings = dlpResult.Findings,
                            Destination = entry.Url,
                            PolicyVersion = policy.Dlp.PolicyVersion,
                            Confidence = Math.Round(Math.Clamp(dlpResult.RiskScore / 10d, 0.1, 0.99), 2),
                            ActorUsername = _options.Username,
                            AppName = entry.Browser,
                            ContentFingerprint = dlpResult.Fingerprint,
                            EnterpriseLabel = dlpResult.RiskLevel is "high" ? "confidential" : "internal",
                            SensitivityScore = dlpResult.RiskScore,
                            LabelReason = dlpResult.LabelReason,
                            BlockCandidate = dlpResult.BlockCandidate,
                            BlockReason = dlpResult.BlockReason,
                            BlockingSupported = false,
                        });
                    }

                    if (DateTimeOffset.TryParse(entry.Timestamp, out var parsed) && parsed > maxSeen)
                    {
                        maxSeen = parsed;
                    }
                }
                sinceUtc = maxSeen;
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogWarning(ex, "Browser activity loop iteration failed for {MachineId}", machineId);
            }
        }
        while (await timer.WaitForNextTickAsync(cancellationToken));
    }

    private async Task RunInputLoopAsync(string machineId, CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(Math.Max(10, _options.InputBucketSeconds)));
        string? previousBucketEnd = null;

        do
        {
            try
            {
                var bucket = _inputActivityTracker.FlushBucket();
                if (bucket.KeyEventCount == 0 && bucket.MouseClickCount == 0 && bucket.MouseScrollCount == 0)
                {
                    continue;
                }

                var end = _clock.UtcNowIso();
                var start = previousBucketEnd ?? end;
                previousBucketEnd = end;
                var context = _heartbeatSignalProvider.Capture();

                var request = new InputActivityRequest
                {
                    MachineId = machineId,
                    Timestamp = end,
                    BucketStart = start,
                    BucketEnd = end,
                    ProcessName = context.ProcessName,
                    WindowTitle = context.WindowTitle,
                    KeyEventCount = bucket.KeyEventCount,
                    MouseClickCount = bucket.MouseClickCount,
                    MouseScrollCount = bucket.MouseScrollCount,
                    PatternHashes = bucket.PatternHashes,
                    NgramSize = 8,
                };

                try
                {
                    await _backendClient.SendInputActivityAsync(
                    request,
                    cancellationToken);
                }
                catch
                {
                    _offlineEventQueue.Enqueue("input", request);
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogWarning(ex, "Input activity loop iteration failed for {MachineId}", machineId);
            }
        }
        while (await timer.WaitForNextTickAsync(cancellationToken));
    }

    private async Task RunOfflineDrainLoopAsync(string machineId, CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(5));
        do
        {
            try
            {
                var batch = _offlineEventQueue.DequeueBatch(50);
                if (batch.Count == 0)
                {
                    continue;
                }

                var response = await _backendClient.SendBatchActivityAsync(
                    new BatchActivityRequest
                    {
                        MachineId = machineId,
                        Events = batch.Select(item => new BatchActivityEvent
                        {
                            QueueId = item.QueueId,
                            EventType = item.EventType,
                            Data = item.Data,
                        }).ToArray(),
                    },
                    cancellationToken);

                var acked = batch
                    .Where(item => response.SuccessIds.Contains(item.QueueId, StringComparer.Ordinal))
                    .Select(item => item.Id)
                    .ToArray();

                if (acked.Length > 0)
                {
                    _offlineEventQueue.Acknowledge(acked);
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogDebug(ex, "Offline drain iteration skipped.");
            }
        }
        while (await timer.WaitForNextTickAsync(cancellationToken));
    }

    private async Task RunScreenshotLoopAsync(string machineId, CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(Math.Max(30, _options.ScreenshotIntervalSeconds)));
        do
        {
            try
            {
                await SendScreenshotAsync(machineId, "scheduled", cancellationToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogWarning(ex, "Screenshot loop iteration failed for {MachineId}", machineId);
            }
        }
        while (await timer.WaitForNextTickAsync(cancellationToken));
    }

    private async Task SendScreenshotAsync(string machineId, string trigger, CancellationToken cancellationToken)
    {
        var image = _screenshotProvider.TryCaptureBase64Jpeg();
        if (string.IsNullOrWhiteSpace(image))
        {
            return;
        }

        var request = new ScreenshotRequest
        {
            MachineId = machineId,
            Timestamp = _clock.UtcNowIso(),
            ImageData = image,
            Trigger = trigger,
        };

        try
        {
            await _backendClient.SendScreenshotAsync(request, cancellationToken);
        }
        catch
        {
            _offlineEventQueue.Enqueue("screenshot", request);
            throw;
        }
    }

    private async Task RunNetworkLoopAsync(string machineId, CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(Math.Max(15, _options.NetworkIntervalSeconds)));
        do
        {
            try
            {
                var snapshot = _networkActivityCollector.Capture();
                if (snapshot.TotalSent == 0 && snapshot.TotalRecv == 0 && snapshot.Connections.Count == 0 && snapshot.ListeningPorts.Count == 0)
                {
                    continue;
                }

                var request = new NetworkActivityRequest
                {
                    MachineId = machineId,
                    Timestamp = _clock.UtcNowIso(),
                    BytesSent = snapshot.BytesSent,
                    BytesRecv = snapshot.BytesRecv,
                    TotalSent = snapshot.TotalSent,
                    TotalRecv = snapshot.TotalRecv,
                    ListenCount = snapshot.ListeningPorts.Count,
                    ConnCount = snapshot.Connections.Count,
                    ListeningPorts = snapshot.ListeningPorts,
                    Connections = snapshot.Connections,
                };

                try
                {
                    await _backendClient.SendNetworkActivityAsync(request, cancellationToken);
                }
                catch
                {
                    _offlineEventQueue.Enqueue("network", request);
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogWarning(ex, "Network activity loop iteration failed for {MachineId}", machineId);
            }
        }
        while (await timer.WaitForNextTickAsync(cancellationToken));
    }

    private async Task RunFileLoopAsync(string machineId, CancellationToken cancellationToken)
    {
        using var timer = new PeriodicTimer(TimeSpan.FromSeconds(2));
        do
        {
            try
            {
                var events = _fileActivityCollector.Drain();
                if (events.Count == 0)
                {
                    continue;
                }

                var policy = _runtimePolicyStore.Snapshot();
                foreach (var item in events)
                {
                    var effectivePath = string.IsNullOrWhiteSpace(item.DestinationPath) ? item.Path : item.DestinationPath;
                    var fileName = Path.GetFileName(effectivePath);
                    var extension = Path.GetExtension(effectivePath);

                    // Track cache for move operations
                    if (item.Action == "move" && !string.IsNullOrWhiteSpace(item.DestinationPath))
                    {
                        if (_deleteBackupCache.TryRemove(item.Path, out var cachedData))
                        {
                            _deleteBackupCache[item.DestinationPath] = cachedData;
                        }
                    }

                    // Look up delete backup
                    bool backupAvailable = false;
                    string backupSkipReason = item.Action == "delete" ? "unavailable_at_delete" : "";
                    string? fileData = null;

                    if (item.Action == "delete")
                    {
                        if (_deleteBackupCache.TryRemove(item.Path, out var cachedContent))
                        {
                            backupAvailable = true;
                            backupSkipReason = "";
                            fileData = cachedContent;
                        }
                    }

                    var request = new FileActivityRequest
                    {
                        MachineId = machineId,
                        Timestamp = _clock.UtcNowIso(),
                        Action = item.Action,
                        FilePath = item.Path,
                        FileName = fileName,
                        FileExt = extension,
                        FileSize = item.FileSize,
                        Destination = item.DestinationPath,
                        IsDirectory = item.IsDirectory,
                        BackupAvailable = backupAvailable,
                        BackupSkipReason = backupSkipReason,
                        FileData = fileData,
                        DestinationType = string.IsNullOrWhiteSpace(item.DestinationPath) ? "local" : "move",
                        DestinationLabel = string.IsNullOrWhiteSpace(item.DestinationPath) ? "local" : "path_move",
                        BlockingSupported = false,
                        BlockingMode = "detect_only",
                    };

                    DlpScanResult? dlpResult = null;
                    bool blocked = false;
                    string blockDetail = "";

                    if (!item.IsDirectory && WindowsFileActivityCollector.CanContentScan(effectivePath))
                    {
                        var content = WindowsFileActivityCollector.TryReadContent(effectivePath);
                        if (!string.IsNullOrWhiteSpace(content))
                        {
                            // Cache content for delete backups
                            _deleteBackupCache[effectivePath] = Convert.ToBase64String(Encoding.UTF8.GetBytes(content));

                            dlpResult = _dlpEngine.ScanText(content, policy.Dlp);
                            if (dlpResult.Matched)
                            {
                                // User-mode active blocking
                                if (dlpResult.BlockCandidate && (request.DestinationType == "move" || item.Action == "create" || item.Action == "modify"))
                                {
                                    try
                                    {
                                        if (File.Exists(effectivePath))
                                        {
                                            File.Delete(effectivePath);
                                            blocked = true;
                                            blockDetail = "destination_removed";
                                            _logger.LogWarning("DLP active block: deleted high-risk file {Path}", effectivePath);
                                        }
                                        if (item.Action == "move" && !string.IsNullOrWhiteSpace(item.Path) && !File.Exists(item.Path))
                                        {
                                            if (_deleteBackupCache.TryGetValue(effectivePath, out var cachedB64))
                                            {
                                                File.WriteAllBytes(item.Path, Convert.FromBase64String(cachedB64));
                                                blockDetail = "reverted_to_source";
                                            }
                                        }
                                    }
                                    catch (Exception ex)
                                    {
                                        _logger.LogError(ex, "DLP active block failed for {Path}", effectivePath);
                                        blockDetail = ex.Message;
                                    }

                                    if (blocked)
                                    {
                                        _ = Task.Run(() =>
                                        {
                                            try
                                            {
                                                MessageBoxW(
                                                    IntPtr.Zero,
                                                    $"{dlpResult.RiskLevel.ToUpper()} risk data transfer blocked: policy restrictions prohibit copying/moving sensitive files to {request.DestinationLabel}.",
                                                    "CropSentinel Data Protection",
                                                    0x00200030); // MB_OK | MB_ICONWARNING | MB_SERVICE_NOTIFICATION
                                            }
                                            catch {}
                                        });
                                    }
                                }

                                request = new FileActivityRequest
                                {
                                    MachineId = request.MachineId,
                                    Timestamp = request.Timestamp,
                                    Action = request.Action,
                                    FilePath = request.FilePath,
                                    FileName = request.FileName,
                                    FileExt = request.FileExt,
                                    FileSize = request.FileSize,
                                    Destination = request.Destination,
                                    IsDirectory = request.IsDirectory,
                                    FileData = request.FileData,
                                    BackupAvailable = request.BackupAvailable,
                                    BackupSkipReason = request.BackupSkipReason,
                                    EnterpriseLabel = dlpResult.RiskLevel is "high" ? "Highly Confidential" : "Confidential",
                                    SensitivityScore = dlpResult.RiskScore,
                                    LabelSource = "content_inspection",
                                    LabelReason = dlpResult.LabelReason,
                                    DestinationType = request.DestinationType,
                                    DestinationLabel = request.DestinationLabel,
                                    BlockCandidate = dlpResult.BlockCandidate,
                                    BlockReason = dlpResult.BlockReason,
                                    BlockingSupported = true,
                                    BlockingMode = dlpResult.BlockCandidate ? "agent_enforced" : "detect_only",
                                };
                            }
                        }
                    }

                    try
                    {
                        await _backendClient.SendFileActivityAsync(request, cancellationToken);
                    }
                    catch
                    {
                        _offlineEventQueue.Enqueue("file", request);
                    }

                    if (dlpResult?.Matched == true)
                    {
                        var dlpRequest = new DlpEventRequest
                        {
                            MachineId = machineId,
                            Timestamp = request.Timestamp,
                            FilePath = request.FilePath,
                            FileName = request.FileName,
                            FileExt = request.FileExt,
                            FileSize = (int)Math.Clamp(request.FileSize, 0, int.MaxValue),
                            Risk = dlpResult.RiskLevel,
                            RiskLevel = dlpResult.RiskLevel,
                            RiskScore = dlpResult.RiskScore,
                            Findings = dlpResult.Findings,
                            Destination = string.IsNullOrWhiteSpace(request.Destination) ? "local" : request.Destination,
                            EventType = "file_transfer",
                            Channel = "file",
                            PolicyVersion = policy.Dlp.PolicyVersion,
                            Confidence = Math.Round(Math.Clamp(dlpResult.RiskScore / 10d, 0.1, 0.99), 2),
                            ActionTaken = dlpResult.BlockCandidate ? "block" : "monitor",
                            ActionResult = dlpResult.BlockCandidate ? (blocked ? "blocked" : "block_failed") : "observed",
                            ActorUsername = _options.Username,
                            AppName = "explorer.exe",
                            DestinationType = request.DestinationType,
                            ContentFingerprint = WindowsFileActivityCollector.ComputeFingerprint(dlpResult.LabelReason + request.FilePath),
                            EnterpriseLabel = request.EnterpriseLabel,
                            SensitivityScore = request.SensitivityScore,
                            LabelSource = request.LabelSource,
                            LabelReason = request.LabelReason,
                            BlockCandidate = request.BlockCandidate,
                            BlockReason = request.BlockReason,
                            BlockingSupported = true,
                            BlockingMode = dlpResult.BlockCandidate ? "agent_enforced" : "detect_only",
                        };

                        try
                        {
                            await _backendClient.SendDlpEventAsync(dlpRequest, cancellationToken);
                        }
                        catch (Exception ex) when (ex is not OperationCanceledException)
                        {
                            _logger.LogDebug(ex, "Native DLP file event send failed for {Path}", request.FilePath);
                        }
                    }
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogWarning(ex, "File activity loop iteration failed for {MachineId}", machineId);
            }
        }
        while (await timer.WaitForNextTickAsync(cancellationToken));
    }

    private async Task RunWebSocketLoopAsync(string machineId, CancellationToken cancellationToken)
    {
        try
        {
            using var socket = await _backendClient.ConnectWebSocketAsync(machineId, cancellationToken);
            if (socket.State != WebSocketState.Open)
            {
                return;
            }

            var buffer = new byte[64 * 1024];
            while (!cancellationToken.IsCancellationRequested && socket.State == WebSocketState.Open)
            {
                var result = await socket.ReceiveAsync(buffer.AsMemory(), cancellationToken);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    break;
                }

                var count = result.Count;
                while (!result.EndOfMessage)
                {
                    if (count >= buffer.Length)
                    {
                        break;
                    }
                    result = await socket.ReceiveAsync(buffer.AsMemory(count), cancellationToken);
                    count += result.Count;
                }

                if (result.MessageType != WebSocketMessageType.Text || count == 0)
                {
                    continue;
                }

                var message = Encoding.UTF8.GetString(buffer, 0, count);
                using var document = JsonDocument.Parse(message);
                var root = document.RootElement;
                var msgType = root.TryGetProperty("type", out var typeProperty) ? typeProperty.GetString() ?? "" : "";
                if (string.Equals(msgType, "take_screenshot", StringComparison.OrdinalIgnoreCase))
                {
                    await SendScreenshotAsync(machineId, "manual", cancellationToken);
                }
                else if (string.Equals(msgType, "webrtc_offer_req", StringComparison.OrdinalIgnoreCase))
                {
                    var sessionId = root.TryGetProperty("session_id", out var sessionProperty) ? sessionProperty.GetString() ?? "" : "";
                    var sessionKind = root.TryGetProperty("session_kind", out var sessionKindProperty) ? sessionKindProperty.GetString() ?? "live" : "live";
                    if (!string.IsNullOrWhiteSpace(sessionId))
                    {
                        await _webRtcSessionManager.HandleOfferRequestAsync(
                            sessionId,
                            sessionKind,
                            (payload, token) => SendWebSocketTextAsync(socket, payload, token),
                            cancellationToken);
                    }
                }
                else if (string.Equals(msgType, "webrtc_answer", StringComparison.OrdinalIgnoreCase))
                {
                    var sessionId = root.TryGetProperty("session_id", out var sessionProperty) ? sessionProperty.GetString() ?? "" : "";
                    if (!string.IsNullOrWhiteSpace(sessionId)
                        && root.TryGetProperty("sdp", out var sdpProperty))
                    {
                        var payload = JsonSerializer.Deserialize(
                            sdpProperty.GetRawText(),
                            AgentJsonSerializerContext.Default.WebRtcSessionDescriptionPayload);
                        if (payload is not null)
                        {
                            await _webRtcSessionManager.HandleAnswerAsync(sessionId, payload, cancellationToken);
                        }
                    }
                }
                else if (string.Equals(msgType, "webrtc_ice", StringComparison.OrdinalIgnoreCase))
                {
                    var sessionId = root.TryGetProperty("session_id", out var sessionProperty) ? sessionProperty.GetString() ?? "" : "";
                    if (!string.IsNullOrWhiteSpace(sessionId)
                        && root.TryGetProperty("candidate", out var candidateProperty))
                    {
                        var payload = JsonSerializer.Deserialize(
                            candidateProperty.GetRawText(),
                            AgentJsonSerializerContext.Default.WebRtcIceCandidatePayload);
                        if (payload is not null)
                        {
                            await _webRtcSessionManager.HandleIceAsync(sessionId, payload, cancellationToken);
                        }
                    }
                }
                else if (string.Equals(msgType, "webrtc_end", StringComparison.OrdinalIgnoreCase))
                {
                    var sessionId = root.TryGetProperty("session_id", out var sessionProperty) ? sessionProperty.GetString() ?? "" : "";
                    if (!string.IsNullOrWhiteSpace(sessionId))
                    {
                        await _webRtcSessionManager.HandleEndAsync(sessionId);
                    }
                }
                else if (string.Equals(msgType, "remote_command", StringComparison.OrdinalIgnoreCase))
                {
                    var action = root.TryGetProperty("action", out var actionProperty) ? actionProperty.GetString() ?? "" : "";
                    var value = root.TryGetProperty("value", out var valueProperty) ? valueProperty.GetString() ?? "" : "";
                    var resultPayload = _remoteCommandExecutor.Execute(action, value);
                    var response = JsonSerializer.Serialize(new RemoteCommandResultSignal
                    {
                        Action = resultPayload.Action,
                        Status = resultPayload.Status,
                        Detail = resultPayload.Detail,
                    }, AgentJsonSerializerContext.Default.RemoteCommandResultSignal);
                    await SendWebSocketTextAsync(socket, response, cancellationToken);
                }
            }
        }
        catch (Exception ex) when (ex is WebSocketException or InvalidOperationException or HttpRequestException)
        {
            _logger.LogWarning(ex, "Agent websocket connection failed. HTTP transport remains active.");
        }
    }

    private static Task SendWebSocketTextAsync(ClientWebSocket socket, string payload, CancellationToken cancellationToken)
    {
        var bytes = Encoding.UTF8.GetBytes(payload);
        return socket.SendAsync(bytes, WebSocketMessageType.Text, true, cancellationToken);
    }

    private static void ValidateOptions(AgentOptions options)
    {
        if (string.IsNullOrWhiteSpace(options.AgentApiKey))
        {
            throw new InvalidOperationException("CropSentinelAgent:AgentApiKey must be set.");
        }
    }

    private static string GetLocalIpAddress()
    {
        try
        {
            using var socket = new Socket(AddressFamily.InterNetwork, SocketType.Dgram, 0);
            socket.Connect("8.8.8.8", 65530);
            if (socket.LocalEndPoint is IPEndPoint endPoint)
            {
                return endPoint.Address.ToString();
            }
        }
        catch
        {
            try
            {
                var host = Dns.GetHostEntry(Dns.GetHostName());
                foreach (var ip in host.AddressList)
                {
                    if (ip.AddressFamily == AddressFamily.InterNetwork)
                    {
                        return ip.ToString();
                    }
                }
            }
            catch {}
        }
        return "127.0.0.1";
    }

    private static string GetMacAddress()
    {
        try
        {
            foreach (var nic in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (nic.OperationalStatus == OperationalStatus.Up && nic.NetworkInterfaceType != NetworkInterfaceType.Loopback)
                {
                    var addr = nic.GetPhysicalAddress().ToString();
                    if (!string.IsNullOrWhiteSpace(addr))
                    {
                        return string.Join(":", Enumerable.Range(0, addr.Length / 2).Select(i => addr.Substring(i * 2, 2).ToLowerInvariant()));
                    }
                }
            }
        }
        catch {}
        return "00:00:00:00:00:00";
    }

    private static string GetActiveUsername(string configured)
    {
        if (!string.IsNullOrWhiteSpace(configured))
        {
            return configured.Trim();
        }

        try
        {
            var identity = System.Security.Principal.WindowsIdentity.GetCurrent().Name;
            if (!string.IsNullOrWhiteSpace(identity))
            {
                var idx = identity.IndexOf('\\');
                if (idx >= 0)
                {
                    identity = identity[(idx + 1)..];
                }
                if (!string.Equals(identity, "SYSTEM", StringComparison.OrdinalIgnoreCase))
                {
                    return identity;
                }
            }
        }
        catch {}

        try
        {
            var user = Environment.UserName;
            if (!string.IsNullOrWhiteSpace(user) && !string.Equals(user, "SYSTEM", StringComparison.OrdinalIgnoreCase))
            {
                return user;
            }
        }
        catch {}

        return "Unknown";
    }

    private static string GetHostname()
    {
        try
        {
            var name = Environment.MachineName;
            return string.IsNullOrWhiteSpace(name) ? Dns.GetHostName() : name;
        }
        catch
        {
            return "Unknown-Host";
        }
    }
}
