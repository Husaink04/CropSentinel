using System.Text.Json;

namespace CropSentinel.AgentNative;

public sealed class PhishingVerdict
{
    public string Verdict { get; init; } = "clean";
    public string Severity { get; init; } = "low";
    public double RiskScore { get; init; }
    public double Confidence { get; init; }
    public string ActionTaken { get; init; } = "monitor";
    public string ActionResult { get; init; } = "observed";
    public IReadOnlyList<string> ReasonCodes { get; init; } = Array.Empty<string>();
    public Dictionary<string, object?> Features { get; init; } = new();
    public string UnsupportedReason { get; init; } = "";
}

public sealed class NativePhishingProtection
{
    private static readonly HashSet<string> KnownBadDomains = new(StringComparer.OrdinalIgnoreCase)
    {
        "login-microsoftonline-security.com",
        "okta-authenticate-secure.com",
        "github-verify-login.com",
        "dropbox-shared-docs-login.com",
    };

    public PhishingVerdict Evaluate(BrowserActivityEntry entry, PhishingPolicyState policy, string processName)
    {
        if (!policy.Enabled || string.IsNullOrWhiteSpace(entry.Url))
        {
            return new PhishingVerdict();
        }

        var domain = (entry.Domain ?? "").Trim().ToLowerInvariant();
        if (policy.AllowDomains.Contains(domain))
        {
            return new PhishingVerdict();
        }

        var features = ExtractFeatures(entry.Url, entry.Title);
        var reasonCodes = new List<string>();
        var score = 0d;

        if (policy.BlockDomains.Contains(domain))
        {
            score += 100;
            reasonCodes.Add("blocklisted_domain");
        }
        if (policy.BlockUrlPatterns.Any(pattern => !string.IsNullOrWhiteSpace(pattern) && entry.Url.Contains(pattern, StringComparison.OrdinalIgnoreCase)))
        {
            score += 100;
            reasonCodes.Add("blocklisted_url_pattern");
        }
        if (KnownBadDomains.Contains(domain))
        {
            score += 85;
            reasonCodes.Add("known_malicious_domain");
        }

        var tld = domain.Contains('.') ? domain[(domain.LastIndexOf('.') + 1)..] : "";
        if (policy.SuspiciousTlds.Contains(tld))
        {
            score += 20;
            reasonCodes.Add("suspicious_tld");
        }
        if (features.HasIpHost)
        {
            score += 25;
            reasonCodes.Add("ip_literal_host");
        }
        if (features.HasPunycode)
        {
            score += 20;
            reasonCodes.Add("punycode_host");
        }
        if (features.SubdomainDepth >= 3)
        {
            score += 10;
            reasonCodes.Add("high_subdomain_depth");
        }
        if (features.Entropy >= 3.6)
        {
            score += 10;
            reasonCodes.Add("high_host_entropy");
        }
        if (features.SuspiciousKeywordCount >= 2)
        {
            score += 10;
            reasonCodes.Add("multiple_suspicious_keywords");
        }
        if (!features.UsesHttps)
        {
            score += 10;
            reasonCodes.Add("no_https");
        }
        if (features.HasLoginTitle)
        {
            score += 15;
            reasonCodes.Add("credential_harvest_title");
        }
        if (policy.BrandWatchlist.Any(brand => domain.Contains(brand, StringComparison.OrdinalIgnoreCase) && !domain.StartsWith($"{brand}.", StringComparison.OrdinalIgnoreCase)))
        {
            score += 35;
            reasonCodes.Add("lookalike_brand_domain");
        }
        if (!string.IsNullOrWhiteSpace(processName) && !IsKnownBrowserProcess(processName))
        {
            score += 5;
            reasonCodes.Add("non_browser_open_surface");
        }

        var verdict = "clean";
        var severity = "low";
        if (score >= GetThreshold(policy, "critical", 90))
        {
            verdict = "malicious";
            severity = "critical";
        }
        else if (score >= GetThreshold(policy, "high", 75))
        {
            verdict = "malicious";
            severity = "high";
        }
        else if (score >= GetThreshold(policy, "medium", 55))
        {
            verdict = "suspicious";
            severity = "medium";
        }

        return new PhishingVerdict
        {
            Verdict = verdict,
            Severity = severity,
            RiskScore = score,
            Confidence = score <= 0 ? 0 : Math.Round(Math.Clamp(score / 100d, 0.1, 0.99), 2),
            ActionTaken = verdict == "clean" ? "allow" : policy.RolloutMode == "warn_only" ? "warn_user" : "monitor",
            ActionResult = verdict == "clean" ? "allow" : policy.RolloutMode == "warn_only" ? "warning_requested" : "observed",
            ReasonCodes = reasonCodes,
            Features = new Dictionary<string, object?>
            {
                ["host"] = domain,
                ["url_length"] = entry.Url.Length,
                ["host_length"] = domain.Length,
                ["subdomain_depth"] = features.SubdomainDepth,
                ["dot_count"] = domain.Count(static ch => ch == '.'),
                ["special_char_count"] = entry.Url.Count(static ch => !char.IsLetterOrDigit(ch)),
                ["has_ip_host"] = features.HasIpHost,
                ["has_punycode"] = features.HasPunycode,
                ["uses_https"] = features.UsesHttps,
                ["entropy"] = features.Entropy,
                ["suspicious_keywords"] = features.SuspiciousKeywords,
                ["has_login_title"] = features.HasLoginTitle,
            },
        };
    }

    private static int GetThreshold(PhishingPolicyState policy, string key, int fallback)
    {
        return policy.SeverityThresholds.TryGetValue(key, out var value) ? value : fallback;
    }

    private static bool IsKnownBrowserProcess(string processName)
    {
        var name = processName.Trim().ToLowerInvariant();
        return name is "chrome.exe" or "msedge.exe" or "firefox.exe" or "chrome" or "msedge" or "firefox";
    }

    private static (bool HasIpHost, bool HasPunycode, bool UsesHttps, double Entropy, int SubdomainDepth, int SuspiciousKeywordCount, string[] SuspiciousKeywords, bool HasLoginTitle) ExtractFeatures(string url, string title)
    {
        var parsed = Uri.TryCreate(url, UriKind.Absolute, out var absolute) ? absolute : new Uri($"https://{url}");
        var host = (parsed.Host ?? "").ToLowerInvariant();
        var suspiciousKeywords = new[] { "login", "signin", "verify", "secure", "auth", "password", "update" }
            .Where(keyword => url.Contains(keyword, StringComparison.OrdinalIgnoreCase))
            .ToArray();
        var counts = host.GroupBy(static ch => ch).ToDictionary(group => group.Key, group => group.Count());
        var entropy = counts.Count == 0
            ? 0
            : -counts.Values.Select(count => (double)count / host.Length).Sum(p => p * Math.Log2(p));
        var subdomainDepth = host.Contains('.') ? Math.Max(0, host.Split('.').Length - 2) : 0;
        var hasIpHost = System.Text.RegularExpressions.Regex.IsMatch(host, @"^\d{1,3}(?:\.\d{1,3}){3}$");
        var hasLoginTitle = new[] { "sign in", "login", "verify", "password", "authenticate" }
            .Any(term => title.Contains(term, StringComparison.OrdinalIgnoreCase));

        return (hasIpHost, host.Contains("xn--", StringComparison.Ordinal), parsed.Scheme.Equals("https", StringComparison.OrdinalIgnoreCase), Math.Round(entropy, 3), subdomainDepth, suspiciousKeywords.Length, suspiciousKeywords, hasLoginTitle);
    }
}
