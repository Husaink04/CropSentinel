using System.Security.Cryptography;
using System.Text;
using Microsoft.Extensions.Options;

namespace CropSentinel.AgentNative;

public interface IMachineIdentityProvider
{
    string GetMachineId();
}

public sealed class MachineIdentityProvider : IMachineIdentityProvider
{
    private readonly AgentOptions _options;

    public MachineIdentityProvider(IOptions<AgentOptions> options)
    {
        _options = options.Value;
    }

    public string GetMachineId()
    {
        if (!string.IsNullOrWhiteSpace(_options.MachineId))
        {
            return _options.MachineId.Trim();
        }

        var dir = _options.ResolveDataDirectory();
        Directory.CreateDirectory(dir);
        var path = Path.Combine(dir, "machine-id.txt");
        if (File.Exists(path))
        {
            var persisted = File.ReadAllText(path).Trim();
            if (!string.IsNullOrWhiteSpace(persisted))
            {
                return persisted;
            }
        }

        var seed = $"{Environment.MachineName}|{Environment.UserDomainName}|{Environment.OSVersion.VersionString}";
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(seed));
        var generated = $"m-native-{Convert.ToHexString(hash)[..16].ToLowerInvariant()}";
        File.WriteAllText(path, generated);
        return generated;
    }
}
