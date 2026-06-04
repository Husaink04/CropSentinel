using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using SIPSorceryMedia.Abstractions;
using SIPSorceryMedia.Encoders;

namespace CropSentinel.AgentNative;

#pragma warning disable CS8618

public sealed class ScreenVideoSource : IVideoSource, IDisposable
{
    private readonly VpxVideoEncoder _encoder;
    private VideoFormat _format;
    private bool _isClosed;

    public event EncodedSampleDelegate OnVideoSourceEncodedSample;
    public event RawVideoSampleDelegate OnVideoSourceRawSample;
    public event RawVideoSampleFasterDelegate OnVideoSourceRawSampleFaster;
    public event SourceErrorDelegate OnVideoSourceError;

    public ScreenVideoSource(VpxVideoEncoder encoder)
    {
        _encoder = encoder;
        _format = _encoder.SupportedFormats[0];
    }

    public List<VideoFormat> GetVideoSourceFormats()
    {
        return _encoder.SupportedFormats;
    }

    public void SetVideoSourceFormat(VideoFormat format)
    {
        _format = format;
    }

    public Task StartVideo()
    {
        return Task.CompletedTask;
    }

    public Task CloseVideo()
    {
        _isClosed = true;
        return Task.CompletedTask;
    }

    public void ExternalVideoSourceRawSample(uint durationMilliseconds, int width, int height, byte[] sample, VideoPixelFormatsEnum pixelFormat)
    {
        if (_isClosed) return;

        try
        {
            var encoded = _encoder.EncodeVideo(width, height, sample, pixelFormat, _format.Codec);
            if (encoded != null && encoded.Length > 0)
            {
                OnVideoSourceEncodedSample?.Invoke(durationMilliseconds, encoded);
            }
        }
        catch (Exception ex)
        {
            OnVideoSourceError?.Invoke(ex.Message);
        }
    }

    public void ExternalVideoSourceRawSampleFaster(uint durationMilliseconds, RawImage rawImage)
    {
    }

    public Task PauseVideo() => Task.CompletedTask;
    public Task ResumeVideo() => Task.CompletedTask;
    public void RestrictFormats(Func<VideoFormat, bool> filter) {}
    public void ForceKeyFrame() => _encoder.ForceKeyFrame();
    public bool HasEncodedVideoSubscribers() => OnVideoSourceEncodedSample != null;
    public bool IsVideoSourcePaused() => false;

    public void Dispose()
    {
        _encoder.Dispose();
    }
}
