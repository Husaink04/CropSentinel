using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Extensions.Logging;

namespace CropSentinel.AgentNative;

public sealed class HeartbeatSignalSnapshot
{
    public double CpuPercent { get; init; }
    public double MemoryPercent { get; init; }
    public string ActiveApp { get; init; } = "";
    public string ProcessName { get; init; } = "";
    public string WindowTitle { get; init; } = "";
    public string ActiveBrowser { get; init; } = "";
    public string ActiveUrl { get; init; } = "";
    public int IdleSeconds { get; init; }
}

public interface IHeartbeatSignalProvider
{
    HeartbeatSignalSnapshot Capture();
}

public sealed partial class WindowsHeartbeatSignalProvider : IHeartbeatSignalProvider
{
    private readonly ILogger<WindowsHeartbeatSignalProvider> _logger;
    private readonly object _cpuLock = new();
    private ulong _lastIdleTime;
    private ulong _lastKernelTime;
    private ulong _lastUserTime;
    private bool _cpuInitialized;

    public WindowsHeartbeatSignalProvider(ILogger<WindowsHeartbeatSignalProvider> logger)
    {
        _logger = logger;
    }

    public HeartbeatSignalSnapshot Capture()
    {
        var foreground = GetForegroundWindowSnapshot();
        return new HeartbeatSignalSnapshot
        {
            CpuPercent = GetCpuPercent(),
            MemoryPercent = GetMemoryPercent(),
            ActiveApp = foreground.AppName,
            ProcessName = foreground.ProcessName,
            WindowTitle = foreground.WindowTitle,
            ActiveBrowser = "",
            ActiveUrl = "",
            IdleSeconds = GetIdleSeconds(),
        };
    }

    private double GetCpuPercent()
    {
        try
        {
            if (!GetSystemTimes(out var idle, out var kernel, out var user))
            {
                return 0;
            }

            var idleTime = FileTimeToUInt64(idle);
            var kernelTime = FileTimeToUInt64(kernel);
            var userTime = FileTimeToUInt64(user);

            lock (_cpuLock)
            {
                if (!_cpuInitialized)
                {
                    _lastIdleTime = idleTime;
                    _lastKernelTime = kernelTime;
                    _lastUserTime = userTime;
                    _cpuInitialized = true;
                    return 0;
                }

                var idleDelta = idleTime - _lastIdleTime;
                var kernelDelta = kernelTime - _lastKernelTime;
                var userDelta = userTime - _lastUserTime;
                var totalDelta = kernelDelta + userDelta;

                _lastIdleTime = idleTime;
                _lastKernelTime = kernelTime;
                _lastUserTime = userTime;

                if (totalDelta == 0)
                {
                    return 0;
                }

                var busy = totalDelta - idleDelta;
                var percent = (double)busy * 100.0 / totalDelta;
                return Math.Clamp(percent, 0, 100);
            }
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Failed to capture CPU percent for native heartbeat.");
            return 0;
        }
    }

    private static double GetMemoryPercent()
    {
        var status = new MemoryStatusEx();
        status.Init();
        if (!GlobalMemoryStatusEx(ref status) || status.TotalPhys == 0)
        {
            return 0;
        }

        var used = status.TotalPhys - status.AvailPhys;
        return Math.Clamp((double)used * 100.0 / status.TotalPhys, 0, 100);
    }

    private int GetIdleSeconds()
    {
        try
        {
            var info = new LastInputInfo();
            info.Init();
            if (!GetLastInputInfo(ref info))
            {
                return 0;
            }

            var now = GetTickCount64();
            if (now < info.dwTime)
            {
                return 0;
            }
            return (int)((now - info.dwTime) / 1000UL);
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Failed to capture idle time for native heartbeat.");
            return 0;
        }
    }

    private ForegroundWindowSnapshot GetForegroundWindowSnapshot()
    {
        try
        {
            var hwnd = GetForegroundWindow();
            if (hwnd == IntPtr.Zero)
            {
                return ForegroundWindowSnapshot.Unknown;
            }

            _ = GetWindowText(hwnd, out var windowTitle);
            _ = GetWindowThreadProcessId(hwnd, out var processId);
            if (processId == 0)
            {
                return new ForegroundWindowSnapshot("Unknown", "unknown", windowTitle);
            }

            using var process = Process.GetProcessById((int)processId);
            var appName = process.ProcessName;
            if (string.IsNullOrWhiteSpace(appName))
            {
                appName = "Unknown";
            }
            var processName = process.ProcessName;
            if (!string.IsNullOrWhiteSpace(processName) && !processName.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
            {
                processName += ".exe";
            }
            return new ForegroundWindowSnapshot(appName, processName, windowTitle);
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Failed to capture active application for native heartbeat.");
            return ForegroundWindowSnapshot.Unknown;
        }
    }

    private static ulong FileTimeToUInt64(FileTime value)
    {
        return ((ulong)(uint)value.dwHighDateTime << 32) | (uint)value.dwLowDateTime;
    }

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool GetSystemTimes(out FileTime idleTime, out FileTime kernelTime, out FileTime userTime);

    [LibraryImport("kernel32.dll")]
    private static partial ulong GetTickCount64();

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool GlobalMemoryStatusEx(ref MemoryStatusEx buffer);

    [LibraryImport("user32.dll")]
    private static partial IntPtr GetForegroundWindow();

    [LibraryImport("user32.dll", SetLastError = true)]
    private static partial uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [LibraryImport("user32.dll", EntryPoint = "GetWindowTextW", StringMarshalling = StringMarshalling.Utf16)]
    private static partial int GetWindowTextW(IntPtr hWnd, Span<char> text, int maxCount);

    [LibraryImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool GetLastInputInfo(ref LastInputInfo plii);

    private static string GetWindowText(IntPtr hwnd, out string title)
    {
        Span<char> buffer = stackalloc char[512];
        var length = GetWindowTextW(hwnd, buffer, buffer.Length);
        title = length > 0 ? new string(buffer[..length]) : "";
        return title;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FileTime
    {
        public int dwLowDateTime;
        public int dwHighDateTime;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct LastInputInfo
    {
        public uint cbSize;
        public uint dwTime;

        public void Init()
        {
            cbSize = (uint)Marshal.SizeOf<LastInputInfo>();
        }
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
    private struct MemoryStatusEx
    {
        public uint dwLength;
        public uint MemoryLoad;
        public ulong TotalPhys;
        public ulong AvailPhys;
        public ulong TotalPageFile;
        public ulong AvailPageFile;
        public ulong TotalVirtual;
        public ulong AvailVirtual;
        public ulong AvailExtendedVirtual;

        public void Init()
        {
            dwLength = (uint)Marshal.SizeOf<MemoryStatusEx>();
        }
    }

    private sealed record ForegroundWindowSnapshot(string AppName, string ProcessName, string WindowTitle)
    {
        public static readonly ForegroundWindowSnapshot Unknown = new("Unknown", "unknown", "");
    }
}
