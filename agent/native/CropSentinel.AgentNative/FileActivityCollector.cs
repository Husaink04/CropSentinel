using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Extensions.Logging;

namespace CropSentinel.AgentNative;

public sealed class NativeFileActivityEvent
{
    public required string Action { get; init; }
    public required string Path { get; init; }
    public string DestinationPath { get; init; } = "";
    public bool IsDirectory { get; init; }
    public long FileSize { get; init; }
}

public interface IFileActivityCollector : IDisposable
{
    void Start();
    IReadOnlyList<NativeFileActivityEvent> Drain();
}

public sealed class WindowsFileActivityCollector : IFileActivityCollector
{
    private static readonly HashSet<string> ScanExtensions =
    [
        ".txt", ".csv", ".json", ".xml", ".yml", ".yaml", ".log",
        ".env", ".cfg", ".conf", ".ini", ".properties",
        ".sql", ".md", ".rst", ".html", ".htm",
        ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rb", ".php",
        ".sh", ".bash", ".bat", ".ps1", ".cmd",
    ];

    private readonly ConcurrentQueue<NativeFileActivityEvent> _events = new();
    private readonly List<FileSystemWatcher> _watchers = new();
    private readonly ILogger<WindowsFileActivityCollector> _logger;
    private int _started;

    public WindowsFileActivityCollector(ILogger<WindowsFileActivityCollector> logger)
    {
        _logger = logger;
    }

    public void Start()
    {
        if (Interlocked.Exchange(ref _started, 1) == 1)
        {
            return;
        }

        foreach (var path in GetWatchedDirectories())
        {
            try
            {
                var watcher = new FileSystemWatcher(path)
                {
                    IncludeSubdirectories = true,
                    NotifyFilter = NotifyFilters.FileName
                        | NotifyFilters.DirectoryName
                        | NotifyFilters.LastWrite
                        | NotifyFilters.Size
                        | NotifyFilters.CreationTime,
                    EnableRaisingEvents = true,
                };

                watcher.Created += (_, e) => Enqueue("create", e.FullPath, "", Directory.Exists(e.FullPath));
                watcher.Changed += (_, e) => Enqueue("modify", e.FullPath, "", Directory.Exists(e.FullPath));
                watcher.Deleted += (_, e) => Enqueue("delete", e.FullPath, "", false);
                watcher.Renamed += (_, e) => Enqueue("move", e.OldFullPath, e.FullPath, Directory.Exists(e.FullPath));
                watcher.Error += (_, e) => _logger.LogDebug(e.GetException(), "File watcher error on {Path}", path);
                _watchers.Add(watcher);
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Unable to watch file activity path {Path}", path);
            }
        }
    }

    public IReadOnlyList<NativeFileActivityEvent> Drain()
    {
        var items = new List<NativeFileActivityEvent>();
        while (_events.TryDequeue(out var item))
        {
            items.Add(item);
        }
        return items;
    }

    public void Dispose()
    {
        foreach (var watcher in _watchers)
        {
            watcher.Dispose();
        }
        _watchers.Clear();
    }

    public static bool CanContentScan(string path)
    {
        return ScanExtensions.Contains(Path.GetExtension(path ?? "").ToLowerInvariant());
    }

    public static string TryReadContent(string path, long maxBytes = 1_048_576)
    {
        try
        {
            var file = new FileInfo(path);
            if (!file.Exists || file.Length <= 0 || file.Length > maxBytes)
            {
                return "";
            }
            return File.ReadAllText(path);
        }
        catch
        {
            return "";
        }
    }

    public static string ComputeFingerprint(string content)
    {
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(content))).ToLowerInvariant();
    }

    private void Enqueue(string action, string path, string destinationPath, bool isDirectory)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        long size = 0;
        if (!isDirectory && action != "delete")
        {
            try
            {
                size = new FileInfo(destinationPath.Length > 0 ? destinationPath : path).Length;
            }
            catch
            {
            }
        }

        _events.Enqueue(new NativeFileActivityEvent
        {
            Action = action,
            Path = path,
            DestinationPath = destinationPath,
            IsDirectory = isDirectory,
            FileSize = size,
        });
    }

    private static IReadOnlyList<string> GetWatchedDirectories()
    {
        var homes = GetWindowsHomes();
        var candidates = new List<string>();

        foreach (var home in homes)
        {
            AddIfExists(candidates, Path.Combine(home, "Desktop"));
            AddIfExists(candidates, Path.Combine(home, "Documents"));
            AddIfExists(candidates, Path.Combine(home, "Downloads"));

            var oneDrive = Path.Combine(home, "OneDrive");
            AddIfExists(candidates, Path.Combine(oneDrive, "Desktop"));
            AddIfExists(candidates, Path.Combine(oneDrive, "Documents"));
            AddIfExists(candidates, Path.Combine(oneDrive, "Downloads"));
        }

        foreach (var root in GetRemovableRoots())
        {
            AddIfExists(candidates, root);
        }

        return candidates
            .Select(path => NormalizePath(path))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    private static IEnumerable<string> GetWindowsHomes()
    {
        var usersRoot = Path.Combine(Environment.GetEnvironmentVariable("SystemDrive") ?? "C:", "Users");
        if (!Directory.Exists(usersRoot))
        {
            return new[] { Environment.GetFolderPath(Environment.SpecialFolder.UserProfile) };
        }

        var excluded = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "All Users", "Default", "Default User", "DefaultAppPool", "Public", "WDAGUtilityAccount", "defaultuser0",
        };

        try
        {
            return Directory.EnumerateDirectories(usersRoot)
                .Where(path => !excluded.Contains(Path.GetFileName(path)))
                .ToArray();
        }
        catch
        {
            return new[] { Environment.GetFolderPath(Environment.SpecialFolder.UserProfile) };
        }
    }

    private static IEnumerable<string> GetRemovableRoots()
    {
        try
        {
            return DriveInfo.GetDrives()
                .Where(drive => drive.DriveType == DriveType.Removable && drive.IsReady)
                .Select(drive => drive.RootDirectory.FullName)
                .ToArray();
        }
        catch
        {
            return Array.Empty<string>();
        }
    }

    private static void AddIfExists(List<string> target, string path)
    {
        if (Directory.Exists(path))
        {
            target.Add(path);
        }
    }

    private static string NormalizePath(string path)
    {
        try
        {
            return Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar).ToLowerInvariant();
        }
        catch
        {
            return (path ?? "").Trim().ToLowerInvariant();
        }
    }
}
