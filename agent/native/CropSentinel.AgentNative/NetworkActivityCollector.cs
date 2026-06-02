using System.Net.NetworkInformation;
using System.Net.Sockets;
using Microsoft.Extensions.Logging;

namespace CropSentinel.AgentNative;

public sealed class NetworkSnapshot
{
    public long BytesSent { get; init; }
    public long BytesRecv { get; init; }
    public long TotalSent { get; init; }
    public long TotalRecv { get; init; }
    public IReadOnlyList<NetworkPortInfo> ListeningPorts { get; init; } = Array.Empty<NetworkPortInfo>();
    public IReadOnlyList<NetworkConnectionInfo> Connections { get; init; } = Array.Empty<NetworkConnectionInfo>();
}

public interface INetworkActivityCollector
{
    NetworkSnapshot Capture();
}

public sealed class WindowsNetworkActivityCollector : INetworkActivityCollector
{
    private const int MaxConnections = 512;
    private const int MaxPorts = 256;
    private readonly ILogger<WindowsNetworkActivityCollector> _logger;
    private readonly Dictionary<string, string> _reverseDnsCache = new(StringComparer.OrdinalIgnoreCase);
    private long _lastSent;
    private long _lastRecv;
    private bool _initialized;

    public WindowsNetworkActivityCollector(ILogger<WindowsNetworkActivityCollector> logger)
    {
        _logger = logger;
    }

    public NetworkSnapshot Capture()
    {
        try
        {
            var properties = IPGlobalProperties.GetIPGlobalProperties();
            var ipv4 = properties.GetIPv4GlobalStatistics();
            var totalSent = ipv4.OutputPacketRequests;
            var totalRecv = ipv4.ReceivedPackets;
            if (!_initialized)
            {
                _lastSent = totalSent;
                _lastRecv = totalRecv;
                _initialized = true;
            }

            var deltaSent = Math.Max(0, totalSent - _lastSent);
            var deltaRecv = Math.Max(0, totalRecv - _lastRecv);
            _lastSent = totalSent;
            _lastRecv = totalRecv;

            var listeningPorts = properties.GetActiveTcpListeners()
                .Take(MaxPorts)
                .Select(endpoint => new NetworkPortInfo
                {
                    Port = endpoint.Port,
                    Protocol = "tcp",
                    Address = endpoint.Address.ToString(),
                })
                .ToList();

            foreach (var endpoint in properties.GetActiveUdpListeners().Take(Math.Max(0, MaxPorts - listeningPorts.Count)))
            {
                listeningPorts.Add(new NetworkPortInfo
                {
                    Port = endpoint.Port,
                    Protocol = "udp",
                    Address = endpoint.Address.ToString(),
                });
            }

            var connections = properties.GetActiveTcpConnections()
                .Where(conn => conn.State == TcpState.Established)
                .Where(conn => conn.RemoteEndPoint is not null)
                .Where(conn => !conn.RemoteEndPoint.Address.ToString().StartsWith("127.", StringComparison.Ordinal))
                .Take(MaxConnections)
                .Select(conn => new NetworkConnectionInfo
                {
                    RemoteIp = conn.RemoteEndPoint.Address.ToString(),
                    RemotePort = conn.RemoteEndPoint.Port,
                    Protocol = "tcp",
                    Domain = ResolveHost(conn.RemoteEndPoint.Address.ToString()),
                })
                .ToArray();

            return new NetworkSnapshot
            {
                BytesSent = deltaSent,
                BytesRecv = deltaRecv,
                TotalSent = totalSent,
                TotalRecv = totalRecv,
                ListeningPorts = listeningPorts,
                Connections = connections,
            };
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Native network activity capture failed.");
            return new NetworkSnapshot();
        }
    }

    private string ResolveHost(string ip)
    {
        if (_reverseDnsCache.TryGetValue(ip, out var cached))
        {
            return cached;
        }

        try
        {
            var host = System.Net.Dns.GetHostEntry(ip).HostName;
            _reverseDnsCache[ip] = host;
            if (_reverseDnsCache.Count > 1024)
            {
                _reverseDnsCache.Clear();
            }
            return host;
        }
        catch (SocketException)
        {
            _reverseDnsCache[ip] = ip;
            return ip;
        }
        catch
        {
            return ip;
        }
    }
}
