using System.Globalization;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Logging;

namespace CropSentinel.AgentNative;

public sealed class BrowserActivityEntry
{
    public required string Browser { get; init; }
    public required string Url { get; init; }
    public string Title { get; init; } = "";
    public string Domain { get; init; } = "";
    public required string Timestamp { get; init; }
}

public interface IBrowserActivityReader
{
    IReadOnlyList<BrowserActivityEntry> ReadRecent(DateTimeOffset sinceUtc);
}

public sealed class WindowsBrowserActivityReader : IBrowserActivityReader
{
    private readonly ILogger<WindowsBrowserActivityReader> _logger;

    public WindowsBrowserActivityReader(ILogger<WindowsBrowserActivityReader> logger)
    {
        _logger = logger;
    }

    public IReadOnlyList<BrowserActivityEntry> ReadRecent(DateTimeOffset sinceUtc)
    {
        var entries = new List<BrowserActivityEntry>();
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var roaming = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);

        ReadChromiumProfiles(Path.Combine(local, "Google", "Chrome", "User Data"), "Chrome", sinceUtc, entries);
        ReadChromiumProfiles(Path.Combine(local, "Microsoft", "Edge", "User Data"), "Edge", sinceUtc, entries);
        ReadFirefoxProfiles(Path.Combine(roaming, "Mozilla", "Firefox", "Profiles"), "Firefox", sinceUtc, entries);

        return entries
            .OrderBy(entry => entry.Timestamp, StringComparer.Ordinal)
            .ToList();
    }

    private void ReadChromiumProfiles(string userDataDir, string browserName, DateTimeOffset sinceUtc, List<BrowserActivityEntry> entries)
    {
        foreach (var profile in GetChromiumProfiles(userDataDir))
        {
            var historyPath = Path.Combine(profile, "History");
            if (!File.Exists(historyPath))
            {
                continue;
            }

            var tempPath = Path.Combine(Path.GetTempPath(), $"cropsentinel-{Guid.NewGuid():N}.db");
            try
            {
                File.Copy(historyPath, tempPath, overwrite: true);
                using var connection = new SqliteConnection($"Data Source={tempPath}");
                connection.Open();

                var command = connection.CreateCommand();
                command.CommandText = """
                    SELECT url, title, last_visit_time
                    FROM urls
                    WHERE last_visit_time > $sinceChrome
                    ORDER BY last_visit_time DESC
                    LIMIT 50
                    """;
                command.Parameters.AddWithValue("$sinceChrome", ToChromiumTimestamp(sinceUtc));

                using var reader = command.ExecuteReader();
                while (reader.Read())
                {
                    var url = reader.IsDBNull(0) ? "" : reader.GetString(0);
                    if (string.IsNullOrWhiteSpace(url))
                    {
                        continue;
                    }

                    var title = reader.IsDBNull(1) ? "" : reader.GetString(1);
                    var chromiumTime = reader.IsDBNull(2) ? 0L : reader.GetInt64(2);
                    var timestamp = FromChromiumTimestamp(chromiumTime);

                    entries.Add(new BrowserActivityEntry
                    {
                        Browser = browserName,
                        Url = url,
                        Title = title,
                        Domain = TryGetHost(url),
                        Timestamp = timestamp.ToString("O", CultureInfo.InvariantCulture),
                    });
                }
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Browser history read failed for {Browser} profile {Profile}", browserName, profile);
            }
            finally
            {
                TryDelete(tempPath);
            }
        }
    }

    private void ReadFirefoxProfiles(string profilesRoot, string browserName, DateTimeOffset sinceUtc, List<BrowserActivityEntry> entries)
    {
        if (!Directory.Exists(profilesRoot))
        {
            return;
        }

        foreach (var profile in Directory.EnumerateDirectories(profilesRoot))
        {
            var placesPath = Path.Combine(profile, "places.sqlite");
            if (!File.Exists(placesPath))
            {
                continue;
            }

            var tempPath = Path.Combine(Path.GetTempPath(), $"cropsentinel-{Guid.NewGuid():N}.db");
            try
            {
                File.Copy(placesPath, tempPath, overwrite: true);
                using var connection = new SqliteConnection($"Data Source={tempPath}");
                connection.Open();

                var command = connection.CreateCommand();
                command.CommandText = """
                    SELECT p.url, p.title, h.visit_date
                    FROM moz_historyvisits h
                    JOIN moz_places p ON h.place_id = p.id
                    WHERE h.visit_date > $sinceFirefox
                    ORDER BY h.visit_date DESC
                    LIMIT 50
                    """;
                command.Parameters.AddWithValue("$sinceFirefox", sinceUtc.ToUnixTimeMilliseconds() * 1000L);

                using var reader = command.ExecuteReader();
                while (reader.Read())
                {
                    var url = reader.IsDBNull(0) ? "" : reader.GetString(0);
                    if (string.IsNullOrWhiteSpace(url))
                    {
                        continue;
                    }

                    var title = reader.IsDBNull(1) ? "" : reader.GetString(1);
                    var visitDate = reader.IsDBNull(2) ? 0L : reader.GetInt64(2);
                    var timestamp = DateTimeOffset.FromUnixTimeMilliseconds(visitDate / 1000L);

                    entries.Add(new BrowserActivityEntry
                    {
                        Browser = browserName,
                        Url = url,
                        Title = title,
                        Domain = TryGetHost(url),
                        Timestamp = timestamp.ToString("O", CultureInfo.InvariantCulture),
                    });
                }
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Firefox history read failed for profile {Profile}", profile);
            }
            finally
            {
                TryDelete(tempPath);
            }
        }
    }

    private static IEnumerable<string> GetChromiumProfiles(string userDataDir)
    {
        if (!Directory.Exists(userDataDir))
        {
            yield break;
        }

        foreach (var dir in Directory.EnumerateDirectories(userDataDir))
        {
            var name = Path.GetFileName(dir);
            if (string.Equals(name, "Default", StringComparison.OrdinalIgnoreCase)
                || name.StartsWith("Profile ", StringComparison.OrdinalIgnoreCase))
            {
                yield return dir;
            }
        }
    }

    private static long ToChromiumTimestamp(DateTimeOffset timestamp)
    {
        return (timestamp.ToUnixTimeSeconds() + 11644473600L) * 1_000_000L;
    }

    private static DateTimeOffset FromChromiumTimestamp(long chromiumTimestamp)
    {
        var unixSeconds = (chromiumTimestamp - 11644473600000000L) / 1_000_000L;
        return DateTimeOffset.FromUnixTimeSeconds(unixSeconds);
    }

    private static string TryGetHost(string url)
    {
        return Uri.TryCreate(url, UriKind.Absolute, out var uri) ? uri.Host : "";
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch
        {
        }
    }
}
