namespace CropSentinel.AgentNative;

public sealed class NoopBrowserActivityReader : IBrowserActivityReader
{
    public IReadOnlyList<BrowserActivityEntry> ReadRecent(DateTimeOffset sinceUtc)
    {
        return Array.Empty<BrowserActivityEntry>();
    }
}

public sealed class NoopInputActivityTracker : IInputActivityTracker
{
    public void Start()
    {
    }

    public InputBucketSnapshot FlushBucket()
    {
        return new InputBucketSnapshot();
    }

    public void Dispose()
    {
    }
}

public sealed class NoopScreenshotProvider : IScreenshotProvider
{
    public string? TryCaptureBase64Jpeg()
    {
        return null;
    }

    public RawScreenFrame? TryCaptureRawFrame()
    {
        return null;
    }
}

public sealed class NoopNetworkActivityCollector : INetworkActivityCollector
{
    public NetworkSnapshot Capture()
    {
        return new NetworkSnapshot();
    }
}

public sealed class NoopFileActivityCollector : IFileActivityCollector
{
    public void Start()
    {
    }

    public IReadOnlyList<NativeFileActivityEvent> Drain()
    {
        return Array.Empty<NativeFileActivityEvent>();
    }

    public void Dispose()
    {
    }
}
