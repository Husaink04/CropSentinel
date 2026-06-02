using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace CropSentinel.AgentNative;

public sealed class DlpScanResult
{
    public bool Matched { get; init; }
    public string RiskLevel { get; init; } = "low";
    public int RiskScore { get; init; }
    public IReadOnlyList<Dictionary<string, object?>> Findings { get; init; } = Array.Empty<Dictionary<string, object?>>();
    public bool BlockCandidate { get; init; }
    public string BlockReason { get; init; } = "";
    public string LabelReason { get; init; } = "";
    public string Fingerprint { get; init; } = "";
}

public sealed class NativeDlpEngine
{
    private static readonly (string Name, Regex Pattern, int Weight)[] Builtins =
    [
        ("email", new Regex(@"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,7}\b", RegexOptions.Compiled), 1),
        ("ssn", new Regex(@"\b\d{3}[\-\s]\d{2}[\-\s]\d{4}\b", RegexOptions.Compiled), 3),
        ("api_key", new Regex(@"(?i)(?:api[_\-]?key|secret[_\-]?key|auth[_\-]?token)\s*[=:]\s*['""]?([A-Za-z0-9\-_\.]{16,128})", RegexOptions.Compiled), 3),
        ("password_in_text", new Regex(@"(?i)(?:password|passwd|pwd|pass)\s{0,5}[=:]\s{0,5}['""]?([^\s'""]{6,64})", RegexOptions.Compiled), 3),
        ("private_key", new Regex(@"-----BEGIN\s(?:RSA\s|EC\s|DSA\s|OPENSSH\s)?PRIVATE\sKEY-----", RegexOptions.Compiled), 3),
    ];

    public DlpScanResult ScanText(string text, DlpPolicyState policy)
    {
        if (!policy.Enabled || string.IsNullOrWhiteSpace(text))
        {
            return new DlpScanResult();
        }

        var findings = new List<Dictionary<string, object?>>();
        var score = 0;

        foreach (var builtin in Builtins)
        {
            var count = builtin.Pattern.Matches(text).Count;
            if (count <= 0)
            {
                continue;
            }
            findings.Add(new Dictionary<string, object?> { ["type"] = builtin.Name, ["count"] = count });
            score += count * builtin.Weight;
        }

        foreach (var keyword in policy.Keywords)
        {
            if (string.IsNullOrWhiteSpace(keyword))
            {
                continue;
            }
            var count = Regex.Matches(text, Regex.Escape(keyword), RegexOptions.IgnoreCase).Count;
            if (count > 0)
            {
                findings.Add(new Dictionary<string, object?> { ["type"] = $"keyword:{keyword}", ["count"] = count });
                score += count;
            }
        }

        foreach (var custom in policy.CustomPatterns)
        {
            try
            {
                var regex = new Regex(custom.Value, RegexOptions.Compiled | RegexOptions.IgnoreCase);
                var count = regex.Matches(text).Count;
                if (count > 0)
                {
                    findings.Add(new Dictionary<string, object?> { ["type"] = custom.Key, ["count"] = count });
                    score += count * 2;
                }
            }
            catch
            {
            }
        }

        if (score <= 0)
        {
            return new DlpScanResult();
        }

        var riskLevel = "low";
        if (score >= GetThreshold(policy, "high", 7))
        {
            riskLevel = "high";
        }
        else if (score >= GetThreshold(policy, "medium", 3))
        {
            riskLevel = "medium";
        }

        return new DlpScanResult
        {
            Matched = true,
            RiskLevel = riskLevel,
            RiskScore = score,
            Findings = findings,
            BlockCandidate = riskLevel is "high",
            BlockReason = riskLevel is "high" ? "high_risk_sensitive_content_detected" : "",
            LabelReason = string.Join(", ", findings.Select(item => $"{item["type"]}({item["count"]})")),
            Fingerprint = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text))).ToLowerInvariant(),
        };
    }

    private static int GetThreshold(DlpPolicyState policy, string key, int fallback)
    {
        return policy.RiskThresholds.TryGetValue(key, out var value) ? value : fallback;
    }
}
