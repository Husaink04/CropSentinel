using System.Collections.Concurrent;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization.Metadata;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using SIPSorcery.Media;
using SIPSorcery.Net;
using SIPSorceryMedia.Abstractions;
using SIPSorceryMedia.Encoders;

namespace CropSentinel.AgentNative;

public sealed class NativeWebRtcSessionManager : IAsyncDisposable
{
    private static readonly List<RTCIceServer> DefaultIceServers =
    [
        new RTCIceServer { urls = "stun:stun.l.google.com:19302" },
        new RTCIceServer { urls = "stun:stun1.l.google.com:19302" },
    ];

    private readonly ConcurrentDictionary<string, LiveWebRtcSession> _sessions = new(StringComparer.Ordinal);
    private readonly IScreenshotProvider _screenshotProvider;
    private readonly NativeRemoteInputExecutor _remoteInputExecutor;
    private readonly NativeFileTransferHandler _fileTransferHandler;
    private readonly AgentOptions _options;
    private readonly ILogger<NativeWebRtcSessionManager> _logger;

    public NativeWebRtcSessionManager(
        IScreenshotProvider screenshotProvider,
        NativeRemoteInputExecutor remoteInputExecutor,
        NativeFileTransferHandler fileTransferHandler,
        IOptions<AgentOptions> options,
        ILogger<NativeWebRtcSessionManager> logger)
    {
        _screenshotProvider = screenshotProvider;
        _remoteInputExecutor = remoteInputExecutor;
        _fileTransferHandler = fileTransferHandler;
        _options = options.Value;
        _logger = logger;
    }

    public async Task HandleOfferRequestAsync(
        string sessionId,
        string sessionKind,
        string turnUrl,
        string turnUsername,
        string turnPassword,
        Func<string, CancellationToken, Task> sendAsync,
        CancellationToken cancellationToken)
    {
        var session = new LiveWebRtcSession(
            sessionId,
            string.Equals(sessionKind, "remote", StringComparison.OrdinalIgnoreCase),
            _screenshotProvider,
            _remoteInputExecutor,
            _fileTransferHandler,
            _options,
            turnUrl,
            turnUsername,
            turnPassword,
            sendAsync,
            _logger);
        if (!_sessions.TryAdd(sessionId, session))
        {
            await session.DisposeAsync();
            return;
        }

        try
        {
            await session.StartAsync(cancellationToken);
        }
        catch
        {
            _sessions.TryRemove(sessionId, out _);
            await session.DisposeAsync();
            throw;
        }
    }

    public Task HandleAnswerAsync(string sessionId, WebRtcSessionDescriptionPayload payload, CancellationToken cancellationToken)
    {
        if (_sessions.TryGetValue(sessionId, out var session))
        {
            return session.ApplyAnswerAsync(payload, cancellationToken);
        }

        return Task.CompletedTask;
    }

    public Task HandleIceAsync(string sessionId, WebRtcIceCandidatePayload payload, CancellationToken cancellationToken)
    {
        if (_sessions.TryGetValue(sessionId, out var session))
        {
            return session.AddIceCandidateAsync(payload, cancellationToken);
        }

        return Task.CompletedTask;
    }

    public async Task HandleEndAsync(string sessionId)
    {
        if (_sessions.TryRemove(sessionId, out var session))
        {
            await session.DisposeAsync();
        }
    }

    public async ValueTask DisposeAsync()
    {
        foreach (var pair in _sessions.ToArray())
        {
            if (_sessions.TryRemove(pair.Key, out var session))
            {
                await session.DisposeAsync();
            }
        }
    }

    private static async Task SendSignalAsync<T>(
        Func<string, CancellationToken, Task> sendAsync,
        T payload,
        JsonTypeInfo<T> typeInfo,
        CancellationToken cancellationToken)
    {
        var json = JsonSerializer.Serialize(payload, typeInfo);
        await sendAsync(json, cancellationToken);
    }

    private sealed class LiveWebRtcSession : IAsyncDisposable
    {
        private readonly string _sessionId;
        private readonly bool _remoteEnabled;
        private readonly IScreenshotProvider _screenshotProvider;
        private readonly NativeRemoteInputExecutor _remoteInputExecutor;
        private readonly NativeFileTransferHandler _fileTransferHandler;
        private readonly AgentOptions _options;
        private readonly Func<string, CancellationToken, Task> _sendAsync;
        private readonly ILogger _logger;
        private readonly CancellationTokenSource _stopCts = new();
        private readonly ScreenVideoSource _videoSource;
        private readonly RTCPeerConnection _peerConnection;
        private Task? _framePumpTask;
        private RTCDataChannel? _inputChannel;
        private RTCDataChannel? _fileTransferChannel;
        private int _disposed;

        public LiveWebRtcSession(
            string sessionId,
            bool remoteEnabled,
            IScreenshotProvider screenshotProvider,
            NativeRemoteInputExecutor remoteInputExecutor,
            NativeFileTransferHandler fileTransferHandler,
            AgentOptions options,
            string turnUrl,
            string turnUsername,
            string turnPassword,
            Func<string, CancellationToken, Task> sendAsync,
            ILogger logger)
        {
            _sessionId = sessionId;
            _remoteEnabled = remoteEnabled;
            _screenshotProvider = screenshotProvider;
            _remoteInputExecutor = remoteInputExecutor;
            _fileTransferHandler = fileTransferHandler;
            _options = options;
            _sendAsync = sendAsync;
            _logger = logger;

            var config = new RTCConfiguration
            {
                iceServers = BuildIceServers(options, turnUrl, turnUsername, turnPassword),
            };

            _peerConnection = new RTCPeerConnection(config);
            _videoSource = new ScreenVideoSource(new VpxVideoEncoder());
        }

        public async Task StartAsync(CancellationToken cancellationToken)
        {
            var videoTrack = new MediaStreamTrack(_videoSource.GetVideoSourceFormats(), MediaStreamStatusEnum.SendOnly);
            _peerConnection.addTrack(videoTrack);
            _videoSource.OnVideoSourceEncodedSample += _peerConnection.SendVideo;
            _peerConnection.OnVideoFormatsNegotiated += formats =>
            {
                if (formats.Count > 0)
                {
                    _videoSource.SetVideoSourceFormat(formats[0]);
                }
            };

            if (_remoteEnabled)
            {
                await ConfigureRemoteChannelsAsync();
            }

            _peerConnection.onicecandidate += async candidate =>
            {
                if (candidate is null || _stopCts.IsCancellationRequested)
                {
                    return;
                }

                await SendSignalAsync(
                    _sendAsync,
                    new WebRtcIceSignal
                    {
                        SessionId = _sessionId,
                        Candidate = new WebRtcIceCandidatePayload
                        {
                            SdpMid = candidate.sdpMid ?? "",
                            SdpMLineIndex = candidate.sdpMLineIndex,
                            Candidate = candidate.candidate ?? "",
                        },
                    },
                    AgentJsonSerializerContext.Default.WebRtcIceSignal,
                    CancellationToken.None);
            };

            _peerConnection.onconnectionstatechange += async state =>
            {
                _logger.LogInformation("Native WebRTC session {SessionId} state changed to {State}", _sessionId, state);
                if (state == RTCPeerConnectionState.connected)
                {
                    await _videoSource.StartVideo();
                    _framePumpTask ??= Task.Run(() => PumpFramesAsync(_stopCts.Token));
                }
                else if (state is RTCPeerConnectionState.failed or RTCPeerConnectionState.closed or RTCPeerConnectionState.disconnected)
                {
                    await DisposeAsync();
                }
            };

            var offer = _peerConnection.createOffer(null);
            await _peerConnection.setLocalDescription(offer);

            await SendSignalAsync(
                _sendAsync,
                new WebRtcOfferSignal
                {
                    SessionId = _sessionId,
                    Sdp = new WebRtcSessionDescriptionPayload
                    {
                        Type = _peerConnection.localDescription?.type.ToString().ToLowerInvariant() ?? "offer",
                        Sdp = _peerConnection.localDescription?.sdp?.ToString() ?? offer.sdp?.ToString() ?? "",
                    },
                },
                AgentJsonSerializerContext.Default.WebRtcOfferSignal,
                cancellationToken);
        }

        public Task ApplyAnswerAsync(WebRtcSessionDescriptionPayload payload, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var result = _peerConnection.setRemoteDescription(
                new RTCSessionDescriptionInit
                {
                    type = ParseSdpType(payload.Type),
                    sdp = payload.Sdp,
                });

            if (result != SetDescriptionResultEnum.OK)
            {
                throw new InvalidOperationException($"Failed to apply remote SDP answer: {result}.");
            }

            return Task.CompletedTask;
        }

        public Task AddIceCandidateAsync(WebRtcIceCandidatePayload payload, CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            _peerConnection.addIceCandidate(
                new RTCIceCandidateInit
                {
                    sdpMid = payload.SdpMid,
                    sdpMLineIndex = (ushort)Math.Max(0, payload.SdpMLineIndex),
                    candidate = payload.Candidate,
                });
            return Task.CompletedTask;
        }

        public async ValueTask DisposeAsync()
        {
            if (Interlocked.Exchange(ref _disposed, 1) != 0)
            {
                return;
            }

            _stopCts.Cancel();

            try
            {
                if (_framePumpTask is not null)
                {
                    await _framePumpTask;
                }
            }
            catch
            {
            }

            try { _inputChannel?.close(); } catch { }
            try { _fileTransferChannel?.close(); } catch { }
            _remoteInputExecutor.ReleaseAllKeys();
            _videoSource.OnVideoSourceEncodedSample -= _peerConnection.SendVideo;
            await _videoSource.CloseVideo();
            _videoSource.Dispose();
            _peerConnection.Close("session_closed");
            _stopCts.Dispose();
        }

        private async Task PumpFramesAsync(CancellationToken cancellationToken)
        {
            var frameDurationMs = (uint)Math.Max(50, 1000 / Math.Max(1, _options.WebRtcFramesPerSecond));
            using var timer = new PeriodicTimer(TimeSpan.FromMilliseconds(frameDurationMs));

            do
            {
                var frame = _screenshotProvider.TryCaptureRawFrame();
                if (frame is null)
                {
                    continue;
                }

                try
                {
                    var packed = PackBgra(frame);
                    _videoSource.ExternalVideoSourceRawSample(frameDurationMs, frame.Width, frame.Height, packed, VideoPixelFormatsEnum.Bgra);
                }
                catch (Exception ex)
                {
                    _logger.LogDebug(ex, "Native WebRTC frame push failed for session {SessionId}", _sessionId);
                }
            }
            while (await timer.WaitForNextTickAsync(cancellationToken));
        }

        private static byte[] PackBgra(RawScreenFrame frame)
        {
            var rowWidth = frame.Width * 4;
            if (frame.Stride == rowWidth)
            {
                return frame.Data;
            }

            var packed = new byte[rowWidth * frame.Height];
            for (var row = 0; row < frame.Height; row++)
            {
                Buffer.BlockCopy(frame.Data, row * frame.Stride, packed, row * rowWidth, rowWidth);
            }
            return packed;
        }

        private static RTCSdpType ParseSdpType(string value)
        {
            return value?.Trim().ToLowerInvariant() switch
            {
                "answer" => RTCSdpType.answer,
                "pranswer" => RTCSdpType.pranswer,
                "rollback" => RTCSdpType.rollback,
                _ => RTCSdpType.offer,
            };
        }

        private static List<RTCIceServer> BuildIceServers(AgentOptions options, string turnUrl, string turnUsername, string turnPassword)
        {
            var servers = new List<RTCIceServer>(DefaultIceServers);
            var url = !string.IsNullOrWhiteSpace(turnUrl) ? turnUrl : options.WebRtcTurnUrl;
            var user = !string.IsNullOrWhiteSpace(turnUrl) ? turnUsername : options.WebRtcTurnUsername;
            var cred = !string.IsNullOrWhiteSpace(turnUrl) ? turnPassword : options.WebRtcTurnPassword;

            if (!string.IsNullOrWhiteSpace(url))
            {
                servers.Add(new RTCIceServer
                {
                    urls = url,
                    username = user ?? "",
                    credential = cred ?? "",
                });
            }

            return servers;
        }

        private async Task ConfigureRemoteChannelsAsync()
        {
            _inputChannel = await _peerConnection.createDataChannel("input");
            _inputChannel.onopen += () =>
            {
                _logger.LogInformation("Remote input data channel open for session {SessionId}", _sessionId);
            };
            _inputChannel.onmessage += (_, protocol, data) =>
            {
                try
                {
                    if (protocol is DataChannelPayloadProtocols.WebRTC_String or DataChannelPayloadProtocols.WebRTC_String_Empty)
                    {
                        using var document = JsonDocument.Parse(Encoding.UTF8.GetString(data));
                        _remoteInputExecutor.Execute(document.RootElement);
                    }
                }
                catch (Exception ex)
                {
                    _logger.LogDebug(ex, "Remote input message failed for session {SessionId}", _sessionId);
                }
            };

            _fileTransferChannel = await _peerConnection.createDataChannel("filetransfer");
            _fileTransferChannel.onopen += () =>
            {
                _logger.LogInformation("Remote file-transfer channel open for session {SessionId}", _sessionId);
            };
            _fileTransferChannel.onmessage += (_, protocol, data) =>
            {
                try
                {
                    if (protocol is DataChannelPayloadProtocols.WebRTC_String or DataChannelPayloadProtocols.WebRTC_String_Empty)
                    {
                        var text = Encoding.UTF8.GetString(data);
                        foreach (var response in _fileTransferHandler.OnStringMessage(text))
                        {
                            if (response.IsBinary)
                            {
                                _fileTransferChannel.send(response.Payload);
                            }
                            else
                            {
                                _fileTransferChannel.send(Encoding.UTF8.GetString(response.Payload));
                            }
                        }
                    }
                    else
                    {
                        _fileTransferHandler.OnBinaryMessage(data);
                    }
                }
                catch (Exception ex)
                {
                    _logger.LogDebug(ex, "Remote file-transfer message failed for session {SessionId}", _sessionId);
                }
            };
        }
    }
}
