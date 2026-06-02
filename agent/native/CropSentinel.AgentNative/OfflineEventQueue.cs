using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Options;

namespace CropSentinel.AgentNative;

public sealed class OfflineQueueItem
{
    public long Id { get; init; }
    public string QueueId { get; init; } = "";
    public string EventType { get; init; } = "";
    public JsonElement Data { get; init; }
}

public sealed class OfflineEventQueue
{
    private readonly string _dbPath;
    private readonly string _keyPath;
    private readonly byte[] _key;
    private readonly object _sync = new();

    public OfflineEventQueue(IOptions<AgentOptions> options)
    {
        var root = options.Value.ResolveDataDirectory();
        Directory.CreateDirectory(root);
        _dbPath = Path.Combine(root, "offline-events.db");
        _keyPath = Path.Combine(root, "offline-events.key");
        _key = LoadOrCreateKey(_keyPath);
        Initialize();
    }

    public void Enqueue(string eventType, object payload)
    {
        var json = SerializePayload(payload);
        var encrypted = Protect(json);

        lock (_sync)
        {
            using var connection = Open();
            connection.Open();
            using var command = connection.CreateCommand();
            command.CommandText = """
                INSERT INTO offline_events(queue_id, event_type, payload, created_at)
                VALUES ($queueId, $eventType, $payload, $createdAt)
                """;
            command.Parameters.AddWithValue("$queueId", Guid.NewGuid().ToString("N"));
            command.Parameters.AddWithValue("$eventType", eventType);
            command.Parameters.AddWithValue("$payload", encrypted);
            command.Parameters.AddWithValue("$createdAt", DateTimeOffset.UtcNow.ToString("O"));
            command.ExecuteNonQuery();
        }
    }

    public IReadOnlyList<OfflineQueueItem> DequeueBatch(int maxCount)
    {
        lock (_sync)
        {
            using var connection = Open();
            connection.Open();
            using var command = connection.CreateCommand();
            command.CommandText = """
                SELECT id, queue_id, event_type, payload
                FROM offline_events
                ORDER BY id ASC
                LIMIT $limit
                """;
            command.Parameters.AddWithValue("$limit", maxCount);

            using var reader = command.ExecuteReader();
            var items = new List<OfflineQueueItem>();
            while (reader.Read())
            {
                var json = Unprotect(reader.GetString(3));
                using var document = JsonDocument.Parse(json);
                items.Add(new OfflineQueueItem
                {
                    Id = reader.GetInt64(0),
                    QueueId = reader.GetString(1),
                    EventType = reader.GetString(2),
                    Data = document.RootElement.Clone(),
                });
            }
            return items;
        }
    }

    public void Acknowledge(IEnumerable<long> ids)
    {
        var idList = ids.Distinct().ToArray();
        if (idList.Length == 0)
        {
            return;
        }

        lock (_sync)
        {
            using var connection = Open();
            connection.Open();
            using var transaction = connection.BeginTransaction();
            foreach (var id in idList)
            {
                using var command = connection.CreateCommand();
                command.Transaction = transaction;
                command.CommandText = "DELETE FROM offline_events WHERE id = $id";
                command.Parameters.AddWithValue("$id", id);
                command.ExecuteNonQuery();
            }
            transaction.Commit();
        }
    }

    private void Initialize()
    {
        lock (_sync)
        {
            using var connection = Open();
            connection.Open();
            using var command = connection.CreateCommand();
            command.CommandText = """
                CREATE TABLE IF NOT EXISTS offline_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    queue_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """;
            command.ExecuteNonQuery();
        }
    }

    private SqliteConnection Open()
    {
        return new SqliteConnection($"Data Source={_dbPath}");
    }

    private static string SerializePayload(object payload)
    {
        return payload switch
        {
            HeartbeatRequest value => JsonSerializer.Serialize(value, AgentJsonSerializerContext.Default.HeartbeatRequest),
            AppActivityRequest value => JsonSerializer.Serialize(value, AgentJsonSerializerContext.Default.AppActivityRequest),
            BrowserActivityRequest value => JsonSerializer.Serialize(value, AgentJsonSerializerContext.Default.BrowserActivityRequest),
            InputActivityRequest value => JsonSerializer.Serialize(value, AgentJsonSerializerContext.Default.InputActivityRequest),
            ScreenshotRequest value => JsonSerializer.Serialize(value, AgentJsonSerializerContext.Default.ScreenshotRequest),
            FileActivityRequest value => JsonSerializer.Serialize(value, AgentJsonSerializerContext.Default.FileActivityRequest),
            NetworkActivityRequest value => JsonSerializer.Serialize(value, AgentJsonSerializerContext.Default.NetworkActivityRequest),
            PhishingEventRequest value => JsonSerializer.Serialize(value, AgentJsonSerializerContext.Default.PhishingEventRequest),
            DlpEventRequest value => JsonSerializer.Serialize(value, AgentJsonSerializerContext.Default.DlpEventRequest),
            _ => throw new InvalidOperationException($"Unsupported offline queue payload type: {payload.GetType().FullName}"),
        };
    }

    private string Protect(string plaintext)
    {
        var bytes = Encoding.UTF8.GetBytes(plaintext);
        var nonce = RandomNumberGenerator.GetBytes(12);
        var cipher = new byte[bytes.Length];
        var tag = new byte[16];
        using var aes = new AesGcm(_key, 16);
        aes.Encrypt(nonce, bytes, cipher, tag);

        var payload = new byte[nonce.Length + tag.Length + cipher.Length];
        Buffer.BlockCopy(nonce, 0, payload, 0, nonce.Length);
        Buffer.BlockCopy(tag, 0, payload, nonce.Length, tag.Length);
        Buffer.BlockCopy(cipher, 0, payload, nonce.Length + tag.Length, cipher.Length);
        return Convert.ToBase64String(payload);
    }

    private string Unprotect(string payload)
    {
        var bytes = Convert.FromBase64String(payload);
        var nonce = bytes.AsSpan(0, 12);
        var tag = bytes.AsSpan(12, 16);
        var cipher = bytes.AsSpan(28);
        var plaintext = new byte[cipher.Length];
        using var aes = new AesGcm(_key, 16);
        aes.Decrypt(nonce, cipher, tag, plaintext);
        return Encoding.UTF8.GetString(plaintext);
    }

    private static byte[] LoadOrCreateKey(string path)
    {
        if (File.Exists(path))
        {
            return Convert.FromBase64String(File.ReadAllText(path));
        }

        var key = RandomNumberGenerator.GetBytes(32);
        File.WriteAllText(path, Convert.ToBase64String(key));
        return key;
    }
}
