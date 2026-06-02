using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.ServiceProcess;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace CropSentinel.AgentNativeService;

[SupportedOSPlatform("windows")]
public sealed partial class ActiveSessionAgentSupervisorService : BackgroundService
{
    private const string AgentServiceName = "CropSentinelAgent";
    private const string WorkerExeName = "cropsentinel-agent-native.exe";
    private const string ServiceExeName = "cropsentinel-agent-service.exe";
    private const string WorkerArgs = "--service-worker";
    private const string PayloadManifestName = "payload-manifest.json";
    private const int CheckIntervalSeconds = 5;
    private const int IntegrityCheckEveryTicks = 12;

    private static readonly string ProgramDataDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
        "CropSentinel");
    private static readonly string ConfigPath = Path.Combine(ProgramDataDir, "config.env");
    private static readonly string PayloadManifestPath = Path.Combine(ProgramDataDir, PayloadManifestName);
    private static readonly string PayloadCacheDir = Path.Combine(ProgramDataDir, "payload-cache");

    private readonly ILogger<ActiveSessionAgentSupervisorService> _logger;
    private Process? _worker;
    private uint? _sessionId;
    private int _tickCounter;

    public ActiveSessionAgentSupervisorService(ILogger<ActiveSessionAgentSupervisorService> logger)
    {
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                EnsureConfigPresent();
                EnsureServiceHealthy();
                if (++_tickCounter % IntegrityCheckEveryTicks == 0)
                {
                    EnsurePayloadIntegrity();
                }

                await EnsureWorkerMatchesActiveSessionAsync(stoppingToken);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogWarning(ex, "Native watchdog loop failed.");
            }

            await Task.Delay(TimeSpan.FromSeconds(CheckIntervalSeconds), stoppingToken);
        }

        StopWorker();
    }

    private Task EnsureWorkerMatchesActiveSessionAsync(CancellationToken cancellationToken)
    {
        var activeSession = WTSGetActiveConsoleSessionId();
        if (activeSession == 0xFFFFFFFF)
        {
            StopWorker();
            return Task.CompletedTask;
        }

        if (_worker is not null && !_worker.HasExited && _sessionId == activeSession)
        {
            return Task.CompletedTask;
        }

        StopWorker();
        LaunchWorker(activeSession);
        return Task.CompletedTask;
    }

    private void EnsureConfigPresent()
    {
        if (!File.Exists(ConfigPath))
        {
            _logger.LogWarning("Watchdog detected missing config at {ConfigPath}", ConfigPath);
            return;
        }

        var content = File.ReadAllText(ConfigPath);
        if (string.IsNullOrWhiteSpace(content))
        {
            _logger.LogWarning("Watchdog detected empty config at {ConfigPath}", ConfigPath);
            return;
        }

        if (!content.Contains("CROPSENTINEL_ENROLL_TOKEN", StringComparison.OrdinalIgnoreCase))
        {
            _logger.LogWarning("Watchdog detected missing CROPSENTINEL_ENROLL_TOKEN in {ConfigPath}", ConfigPath);
        }
    }

    private void EnsureServiceHealthy()
    {
        using var controller = new ServiceController(AgentServiceName);
        try
        {
            _ = controller.Status;
        }
        catch (InvalidOperationException ex)
        {
            _logger.LogWarning(ex, "Agent service registration is missing or unreadable.");
            return;
        }

        if (controller.Status == ServiceControllerStatus.Running)
        {
            return;
        }

        try
        {
            controller.Start();
            controller.WaitForStatus(ServiceControllerStatus.Running, TimeSpan.FromSeconds(20));
            _logger.LogInformation("Restarted {ServiceName} service from native watchdog.", AgentServiceName);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to restart {ServiceName} service from native watchdog.", AgentServiceName);
        }
    }

    private void EnsurePayloadIntegrity()
    {
        if (!File.Exists(PayloadManifestPath))
        {
            _logger.LogWarning("Payload manifest is missing at {ManifestPath}", PayloadManifestPath);
            return;
        }

        PayloadManifest? manifest;
        try
        {
            manifest = JsonSerializer.Deserialize(
                File.ReadAllText(PayloadManifestPath),
                WatchdogJsonSerializerContext.Default.PayloadManifest);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to read payload manifest at {ManifestPath}", PayloadManifestPath);
            return;
        }

        if (manifest?.Files is null || manifest.Files.Count == 0)
        {
            _logger.LogWarning("Payload manifest at {ManifestPath} is empty.", PayloadManifestPath);
            return;
        }

        foreach (var entry in manifest.Files)
        {
            if (string.IsNullOrWhiteSpace(entry.Path) || string.IsNullOrWhiteSpace(entry.Sha256))
            {
                _logger.LogWarning("Payload manifest contains an invalid entry.");
                continue;
            }

            var relativePath = entry.Path.Replace('/', Path.DirectorySeparatorChar);
            var installFile = Path.Combine(AppContext.BaseDirectory, relativePath);
            var cacheFile = Path.Combine(PayloadCacheDir, relativePath);

            var installValid = TryMatchHash(installFile, entry.Sha256);
            var cacheValid = TryMatchHash(cacheFile, entry.Sha256);

            if (!cacheValid && installValid)
            {
                RestoreFile(installFile, cacheFile, "cache");
                cacheValid = TryMatchHash(cacheFile, entry.Sha256);
            }

            if (!installValid && cacheValid)
            {
                RestoreFile(cacheFile, installFile, "install");
                installValid = TryMatchHash(installFile, entry.Sha256);
            }

            if (!installValid && !cacheValid)
            {
                _logger.LogCritical(
                    "Payload file is unrecoverable. RelativePath={RelativePath} Install={InstallFile} Cache={CacheFile}",
                    entry.Path,
                    installFile,
                    cacheFile);
            }
        }
    }

    private void RestoreFile(string source, string destination, string targetKind)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            File.Copy(source, destination, overwrite: true);
            _logger.LogWarning("Restored {TargetKind} payload file {Destination} from {Source}", targetKind, destination, source);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to restore {TargetKind} payload file {Destination} from {Source}", targetKind, destination, source);
        }
    }

    private static bool TryMatchHash(string path, string expectedSha256)
    {
        if (!File.Exists(path))
        {
            return false;
        }

        try
        {
            using var stream = File.OpenRead(path);
            var hash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
            return string.Equals(hash, expectedSha256.Trim().ToLowerInvariant(), StringComparison.Ordinal);
        }
        catch
        {
            return false;
        }
    }

    private void LaunchWorker(uint sessionId)
    {
        var workerPath = Path.Combine(AppContext.BaseDirectory, WorkerExeName);
        if (!File.Exists(workerPath))
        {
            throw new FileNotFoundException($"Native worker executable not found: {workerPath}");
        }

        if (!WTSQueryUserToken(sessionId, out var userToken))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "WTSQueryUserToken failed");
        }

        try
        {
            if (!DuplicateTokenEx(
                userToken,
                0x02000000,
                IntPtr.Zero,
                2,
                1,
                out var primaryToken))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "DuplicateTokenEx failed");
            }

            try
            {
                if (!CreateEnvironmentBlock(out var environment, primaryToken, false))
                {
                    environment = IntPtr.Zero;
                }

                try
                {
                    var startupInfo = new STARTUPINFO
                    {
                        cb = Marshal.SizeOf<STARTUPINFO>(),
                        lpDesktop = @"winsta0\default",
                        dwFlags = 0x00000001,
                        wShowWindow = 0,
                    };

                    var commandLine = $"\"{workerPath}\" {WorkerArgs}";
                    if (!CreateProcessAsUser(
                        primaryToken,
                        workerPath,
                        commandLine,
                        IntPtr.Zero,
                        IntPtr.Zero,
                        false,
                        0x00000400,
                        environment,
                        Path.GetDirectoryName(workerPath)!,
                        ref startupInfo,
                        out var processInfo))
                    {
                        throw new Win32Exception(Marshal.GetLastWin32Error(), "CreateProcessAsUser failed");
                    }

                    try
                    {
                        _worker = Process.GetProcessById((int)processInfo.dwProcessId);
                        _sessionId = sessionId;
                        _logger.LogInformation("Native worker launched in session {SessionId} with pid {Pid}", sessionId, processInfo.dwProcessId);
                    }
                    finally
                    {
                        CloseHandle(processInfo.hThread);
                        CloseHandle(processInfo.hProcess);
                    }
                }
                finally
                {
                    if (environment != IntPtr.Zero)
                    {
                        DestroyEnvironmentBlock(environment);
                    }
                }
            }
            finally
            {
                CloseHandle(primaryToken);
            }
        }
        finally
        {
            CloseHandle(userToken);
        }
    }

    private void StopWorker()
    {
        if (_worker is not null)
        {
            try
            {
                if (!_worker.HasExited)
                {
                    _worker.Kill(entireProcessTree: true);
                    _worker.WaitForExit(5000);
                }
            }
            catch
            {
            }
            finally
            {
                _worker.Dispose();
                _worker = null;
                _sessionId = null;
            }
        }
    }

    [DllImport("kernel32.dll")]
    private static extern uint WTSGetActiveConsoleSessionId();

    [DllImport("Wtsapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool WTSQueryUserToken(uint sessionId, out nint token);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DuplicateTokenEx(
        nint existingTokenHandle,
        uint desiredAccess,
        nint tokenAttributes,
        int impersonationLevel,
        int tokenType,
        out nint duplicateTokenHandle);

    [DllImport("userenv.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateEnvironmentBlock(out nint environment, nint token, [MarshalAs(UnmanagedType.Bool)] bool inherit);

    [DllImport("userenv.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DestroyEnvironmentBlock(nint environment);

    [DllImport("advapi32.dll", EntryPoint = "CreateProcessAsUserW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcessAsUser(
        nint token,
        string applicationName,
        string commandLine,
        nint processAttributes,
        nint threadAttributes,
        [MarshalAs(UnmanagedType.Bool)] bool inheritHandles,
        uint creationFlags,
        nint environment,
        string currentDirectory,
        ref STARTUPINFO startupInfo,
        out PROCESS_INFORMATION processInformation);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(nint handle);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO
    {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public nint lpReserved2;
        public nint hStdInput;
        public nint hStdOutput;
        public nint hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public nint hProcess;
        public nint hThread;
        public uint dwProcessId;
        public uint dwThreadId;
    }
}

internal sealed class PayloadManifest
{
    [JsonPropertyName("files")]
    public List<PayloadManifestEntry> Files { get; init; } = [];
}

internal sealed class PayloadManifestEntry
{
    [JsonPropertyName("path")]
    public string Path { get; init; } = "";

    [JsonPropertyName("sha256")]
    public string Sha256 { get; init; } = "";
}
