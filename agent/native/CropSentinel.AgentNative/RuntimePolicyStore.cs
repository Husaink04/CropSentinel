using System.Text.Json;

namespace CropSentinel.AgentNative;

public sealed class RuntimePolicyStore
{
    private readonly object _sync = new();
    private RuntimePolicySnapshot _snapshot = RuntimePolicySnapshot.Default;

    public RuntimePolicySnapshot Snapshot()
    {
        lock (_sync)
        {
            return _snapshot;
        }
    }

    public void UpdateFromHeartbeatConfig(JsonElement config)
    {
        if (config.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null)
        {
            return;
        }

        var current = Snapshot();
        var next = new RuntimePolicySnapshot
        {
            Dlp = ParseDlpPolicy(config, current.Dlp),
            Phishing = ParsePhishingPolicy(config, current.Phishing),
        };

        lock (_sync)
        {
            _snapshot = next;
        }
    }

    private static DlpPolicyState ParseDlpPolicy(JsonElement config, DlpPolicyState fallback)
    {
        var state = fallback;
        if (config.TryGetProperty("dlp_enabled", out var dlpEnabled) && (dlpEnabled.ValueKind == JsonValueKind.True || dlpEnabled.ValueKind == JsonValueKind.False))
        {
            state = state with { Enabled = dlpEnabled.GetBoolean() };
        }

        if (config.TryGetProperty("dlp_keywords", out var keywordsEl) && keywordsEl.ValueKind == JsonValueKind.Array)
        {
            state = state with
            {
                Keywords = keywordsEl.EnumerateArray()
                    .Where(item => item.ValueKind == JsonValueKind.String)
                    .Select(item => item.GetString() ?? "")
                    .Where(item => !string.IsNullOrWhiteSpace(item))
                    .ToArray()
            };
        }

        if (config.TryGetProperty("dlp_custom_patterns", out var patternsEl) && patternsEl.ValueKind == JsonValueKind.Object)
        {
            var patterns = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var property in patternsEl.EnumerateObject())
            {
                if (property.Value.ValueKind == JsonValueKind.String)
                {
                    patterns[property.Name] = property.Value.GetString() ?? "";
                }
            }
            state = state with { CustomPatterns = patterns };
        }

        if (config.TryGetProperty("dlp_risk_thresholds", out var thresholdsEl) && thresholdsEl.ValueKind == JsonValueKind.Object)
        {
            var thresholds = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            foreach (var property in thresholdsEl.EnumerateObject())
            {
                if (property.Value.ValueKind == JsonValueKind.Number && property.Value.TryGetInt32(out var value))
                {
                    thresholds[property.Name] = value;
                }
            }
            state = state with { RiskThresholds = thresholds };
        }

        if (config.TryGetProperty("dlp_policy_version", out var versionEl) && versionEl.ValueKind == JsonValueKind.Number && versionEl.TryGetInt32(out var version))
        {
            state = state with { PolicyVersion = version };
        }

        if (config.TryGetProperty("dlp_policy_hash", out var hashEl) && hashEl.ValueKind == JsonValueKind.String)
        {
            state = state with { PolicyHash = hashEl.GetString() ?? "" };
        }

        return state;
    }

    private static PhishingPolicyState ParsePhishingPolicy(JsonElement config, PhishingPolicyState fallback)
    {
        var state = fallback;
        if (config.TryGetProperty("phishing_policy_version", out var versionEl) && versionEl.ValueKind == JsonValueKind.Number && versionEl.TryGetInt32(out var version))
        {
            state = state with { PolicyVersion = version };
        }
        if (config.TryGetProperty("phishing_policy_hash", out var hashEl) && hashEl.ValueKind == JsonValueKind.String)
        {
            state = state with { PolicyHash = hashEl.GetString() ?? "" };
        }
        if (config.TryGetProperty("phishing_policy", out var policyEl) && policyEl.ValueKind == JsonValueKind.Object)
        {
            state = state with
            {
                Enabled = GetBool(policyEl, "phishing_enabled", state.Enabled),
                RolloutMode = GetString(policyEl, "rollout_mode", state.RolloutMode),
                SeverityThresholds = GetIntMap(policyEl, "severity_thresholds", state.SeverityThresholds),
                AllowDomains = GetNestedStringSet(policyEl, "allowlists", "domains", state.AllowDomains),
                BlockDomains = GetNestedStringSet(policyEl, "blocklists", "domains", state.BlockDomains),
                BlockUrlPatterns = GetNestedStringSet(policyEl, "blocklists", "url_patterns", state.BlockUrlPatterns),
                SuspiciousTlds = GetStringSet(policyEl, "suspicious_tlds", state.SuspiciousTlds),
                BrandWatchlist = GetStringSet(policyEl, "brand_watchlist", state.BrandWatchlist),
            };
        }
        return state;
    }

    private static bool GetBool(JsonElement parent, string name, bool fallback)
    {
        return parent.TryGetProperty(name, out var value) && (value.ValueKind == JsonValueKind.True || value.ValueKind == JsonValueKind.False)
            ? value.GetBoolean()
            : fallback;
    }

    private static string GetString(JsonElement parent, string name, string fallback)
    {
        return parent.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? fallback
            : fallback;
    }

    private static IReadOnlyDictionary<string, int> GetIntMap(JsonElement parent, string name, IReadOnlyDictionary<string, int> fallback)
    {
        if (!parent.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Object)
        {
            return fallback;
        }
        var result = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (var property in value.EnumerateObject())
        {
            if (property.Value.ValueKind == JsonValueKind.Number && property.Value.TryGetInt32(out var item))
            {
                result[property.Name] = item;
            }
        }
        return result;
    }

    private static ISet<string> GetStringSet(JsonElement parent, string name, ISet<string> fallback)
    {
        if (!parent.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
        {
            return fallback;
        }

        return value.EnumerateArray()
            .Where(item => item.ValueKind == JsonValueKind.String)
            .Select(item => (item.GetString() ?? "").Trim().ToLowerInvariant())
            .Where(item => item.Length > 0)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
    }

    private static ISet<string> GetNestedStringSet(JsonElement parent, string objectName, string key, ISet<string> fallback)
    {
        if (!parent.TryGetProperty(objectName, out var nested) || nested.ValueKind != JsonValueKind.Object)
        {
            return fallback;
        }
        return GetStringSet(nested, key, fallback);
    }
}

public sealed record RuntimePolicySnapshot
{
    public static readonly RuntimePolicySnapshot Default = new();

    public DlpPolicyState Dlp { get; init; } = DlpPolicyState.Default;
    public PhishingPolicyState Phishing { get; init; } = PhishingPolicyState.Default;
}

public sealed record DlpPolicyState
{
    public static readonly DlpPolicyState Default = new();

    public bool Enabled { get; init; } = true;
    public IReadOnlyList<string> Keywords { get; init; } = Array.Empty<string>();
    public IReadOnlyDictionary<string, string> CustomPatterns { get; init; } = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    public IReadOnlyDictionary<string, int> RiskThresholds { get; init; } = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
    {
        ["low"] = 1,
        ["medium"] = 3,
        ["high"] = 7,
    };
    public int PolicyVersion { get; init; } = 1;
    public string PolicyHash { get; init; } = "";
}

public sealed record PhishingPolicyState
{
    public static readonly PhishingPolicyState Default = new();

    public bool Enabled { get; init; } = true;
    public string RolloutMode { get; init; } = "warn_only";
    public IReadOnlyDictionary<string, int> SeverityThresholds { get; init; } = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
    {
        ["medium"] = 55,
        ["high"] = 75,
        ["critical"] = 90,
    };
    public ISet<string> AllowDomains { get; init; } = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    public ISet<string> BlockDomains { get; init; } = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    public ISet<string> BlockUrlPatterns { get; init; } = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    public ISet<string> SuspiciousTlds { get; init; } = new HashSet<string>(new[] { "zip", "click", "work" }, StringComparer.OrdinalIgnoreCase);
    public ISet<string> BrandWatchlist { get; init; } = new HashSet<string>(new[] { "microsoft", "google", "okta" }, StringComparer.OrdinalIgnoreCase);
    public int PolicyVersion { get; init; } = 1;
    public string PolicyHash { get; init; } = "";
}
