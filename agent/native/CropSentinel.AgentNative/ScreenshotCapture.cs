using System.Drawing;
using System.Drawing.Imaging;
using Microsoft.Extensions.Logging;

namespace CropSentinel.AgentNative;

public interface IScreenshotProvider
{
    string? TryCaptureBase64Jpeg();
    RawScreenFrame? TryCaptureRawFrame();
}

public sealed partial class WindowsScreenshotProvider : IScreenshotProvider
{
    private readonly ILogger<WindowsScreenshotProvider> _logger;

    public WindowsScreenshotProvider(ILogger<WindowsScreenshotProvider> logger)
    {
        _logger = logger;
    }

    public string? TryCaptureBase64Jpeg()
    {
        try
        {
            using var bitmap = CaptureBitmap();
            if (bitmap is null)
            {
                return null;
            }

            using var stream = new MemoryStream();
            var encoder = ImageCodecInfo.GetImageEncoders().FirstOrDefault(codec => codec.FormatID == ImageFormat.Jpeg.Guid);
            if (encoder is null)
            {
                bitmap.Save(stream, ImageFormat.Jpeg);
            }
            else
            {
                using var parameters = new EncoderParameters(1);
                parameters.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 70L);
                bitmap.Save(stream, encoder, parameters);
            }

            return Convert.ToBase64String(stream.ToArray());
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Native screenshot capture failed.");
            return null;
        }
    }

    public RawScreenFrame? TryCaptureRawFrame()
    {
        try
        {
            using var bitmap = CaptureBitmap();
            if (bitmap is null)
            {
                return null;
            }

            var rect = new Rectangle(0, 0, bitmap.Width, bitmap.Height);
            var data = bitmap.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            try
            {
                var size = Math.Abs(data.Stride) * data.Height;
                var bytes = new byte[size];
                System.Runtime.InteropServices.Marshal.Copy(data.Scan0, bytes, 0, size);
                return new RawScreenFrame(bitmap.Width, bitmap.Height, data.Stride, bytes);
            }
            finally
            {
                bitmap.UnlockBits(data);
            }
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Native raw frame capture failed.");
            return null;
        }
    }

    private static Bitmap? CaptureBitmap()
    {
        var bounds = GetVirtualScreenBounds();
        if (bounds.Width <= 0 || bounds.Height <= 0)
        {
            return null;
        }

        var bitmap = new Bitmap(bounds.Width, bounds.Height, PixelFormat.Format32bppArgb);
        using var graphics = Graphics.FromImage(bitmap);
        graphics.CopyFromScreen(bounds.Left, bounds.Top, 0, 0, bounds.Size);
        return bitmap;
    }

    private static Rectangle GetVirtualScreenBounds()
    {
        var left = GetSystemMetrics(76);
        var top = GetSystemMetrics(77);
        var width = GetSystemMetrics(78);
        var height = GetSystemMetrics(79);
        return new Rectangle(left, top, width, height);
    }

    [System.Runtime.InteropServices.LibraryImport("user32.dll")]
    private static partial int GetSystemMetrics(int nIndex);
}

public sealed record RawScreenFrame(int Width, int Height, int Stride, byte[] Data);
