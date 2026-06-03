using System.Collections.Concurrent;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Runtime.Versioning;
using Microsoft.Extensions.Logging;

namespace CropSentinel.AgentNative;

public sealed class InputBucketSnapshot
{
    public int KeyEventCount { get; init; }
    public int MouseClickCount { get; init; }
    public int MouseScrollCount { get; init; }
    public IReadOnlyList<string> PatternHashes { get; init; } = Array.Empty<string>();
}

public interface IInputActivityTracker : IDisposable
{
    void Start();
    InputBucketSnapshot FlushBucket();
}

[SupportedOSPlatform("windows")]
public sealed partial class WindowsInputActivityTracker : IInputActivityTracker
{
    private const int WhKeyboardLl = 13;
    private const int WhMouseLl = 14;
    private const int WmKeyDown = 0x0100;
    private const int WmSysKeyDown = 0x0104;
    private const int WmLButtonDown = 0x0201;
    private const int WmRButtonDown = 0x0204;
    private const int WmMButtonDown = 0x0207;
    private const int WmMouseWheel = 0x020A;
    private const int WmMouseHWheel = 0x020E;
    private const int NgramSize = 8;

    private readonly ILogger<WindowsInputActivityTracker> _logger;
    private readonly object _sync = new();
    private readonly List<int> _codes = new();
    private int _keyCount;
    private int _clickCount;
    private int _scrollCount;
    private Thread? _hookThread;
    private uint _hookThreadId;
    private nint _keyboardHook;
    private nint _mouseHook;
    private HookProc? _keyboardProc;
    private HookProc? _mouseProc;
    private readonly ManualResetEventSlim _started = new(false);
    private bool _disposed;

    public WindowsInputActivityTracker(ILogger<WindowsInputActivityTracker> logger)
    {
        _logger = logger;
    }

    public void Start()
    {
        if (_hookThread is not null)
        {
            return;
        }

        _hookThread = new Thread(HookThreadMain)
        {
            IsBackground = true,
            Name = "CropSentinelNativeInputHooks",
        };
        _hookThread.SetApartmentState(ApartmentState.STA);
        _hookThread.Start();
        _started.Wait(TimeSpan.FromSeconds(5));
    }

    public InputBucketSnapshot FlushBucket()
    {
        lock (_sync)
        {
            var hashes = ComputeHashes(_codes);
            var snapshot = new InputBucketSnapshot
            {
                KeyEventCount = _keyCount,
                MouseClickCount = _clickCount,
                MouseScrollCount = _scrollCount,
                PatternHashes = hashes,
            };

            _codes.Clear();
            _keyCount = 0;
            _clickCount = 0;
            _scrollCount = 0;
            return snapshot;
        }
    }

    private void HookThreadMain()
    {
        _hookThreadId = GetCurrentThreadId();
        _keyboardProc = KeyboardHookCallback;
        _mouseProc = MouseHookCallback;
        _keyboardHook = SetWindowsHookEx(WhKeyboardLl, _keyboardProc, IntPtr.Zero, 0);
        _mouseHook = SetWindowsHookEx(WhMouseLl, _mouseProc, IntPtr.Zero, 0);
        _started.Set();

        try
        {
            while (GetMessage(out var msg, IntPtr.Zero, 0, 0) > 0)
            {
                TranslateMessage(in msg);
                DispatchMessage(in msg);
            }
        }
        finally
        {
            if (_keyboardHook != 0)
            {
                UnhookWindowsHookEx(_keyboardHook);
                _keyboardHook = 0;
            }
            if (_mouseHook != 0)
            {
                UnhookWindowsHookEx(_mouseHook);
                _mouseHook = 0;
            }
        }
    }

    private nint KeyboardHookCallback(int code, nuint wParam, nint lParam)
    {
        if (code >= 0 && (wParam == WmKeyDown || wParam == WmSysKeyDown))
        {
            var info = Marshal.PtrToStructure<KbdLlHookStruct>(lParam);
            lock (_sync)
            {
                _keyCount++;
                _codes.Add(unchecked((int)info.vkCode) & 0xFFFF);
            }
        }

        return CallNextHookEx(IntPtr.Zero, code, wParam, lParam);
    }

    private nint MouseHookCallback(int code, nuint wParam, nint lParam)
    {
        if (code >= 0)
        {
            lock (_sync)
            {
                if (wParam is WmLButtonDown or WmRButtonDown or WmMButtonDown)
                {
                    _clickCount++;
                }
                else if (wParam is WmMouseWheel or WmMouseHWheel)
                {
                    _scrollCount++;
                }
            }
        }

        return CallNextHookEx(IntPtr.Zero, code, wParam, lParam);
    }

    private static IReadOnlyList<string> ComputeHashes(List<int> codes)
    {
        if (codes.Count == 0)
        {
            return Array.Empty<string>();
        }

        var hashes = new List<string>();
        var index = 0;
        while (index + NgramSize <= codes.Count)
        {
            hashes.Add(HashCodeChunk(codes.GetRange(index, NgramSize)));
            index += NgramSize;
        }

        var rest = codes.Count - index;
        if (rest >= 4)
        {
            hashes.Add(HashCodeChunk(codes.GetRange(index, rest), partial: true));
        }

        return hashes;
    }

    private static string HashCodeChunk(List<int> codes, bool partial = false)
    {
        var prefix = partial ? "partial:" : "";
        var payload = $"{prefix}{string.Join(",", codes)}";
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(payload));
        return Convert.ToHexString(bytes).ToLowerInvariant()[..32];
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        if (_hookThreadId != 0)
        {
            PostThreadMessage(_hookThreadId, 0x0012, UIntPtr.Zero, IntPtr.Zero);
        }
        if (_hookThread is not null && _hookThread.IsAlive)
        {
            _hookThread.Join(TimeSpan.FromSeconds(5));
        }
        _started.Dispose();
    }

    private delegate nint HookProc(int code, nuint wParam, nint lParam);

    [LibraryImport("user32.dll", EntryPoint = "SetWindowsHookExW", SetLastError = true)]
    private static partial nint SetWindowsHookEx(int idHook, HookProc lpfn, IntPtr hMod, uint dwThreadId);

    [LibraryImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool UnhookWindowsHookEx(nint hhk);

    [LibraryImport("user32.dll")]
    private static partial nint CallNextHookEx(IntPtr hhk, int nCode, nuint wParam, nint lParam);

    [LibraryImport("user32.dll", EntryPoint = "GetMessageW")]
    private static partial sbyte GetMessage(out Msg lpMsg, IntPtr hWnd, uint wMsgFilterMin, uint wMsgFilterMax);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool TranslateMessage(in Msg lpMsg);

    [LibraryImport("user32.dll", EntryPoint = "DispatchMessageW")]
    private static partial nint DispatchMessage(in Msg lpMsg);

    [LibraryImport("kernel32.dll")]
    private static partial uint GetCurrentThreadId();

    [LibraryImport("user32.dll", EntryPoint = "PostThreadMessageW", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool PostThreadMessage(uint idThread, uint msg, UIntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    private struct Point
    {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Msg
    {
        public IntPtr hwnd;
        public uint message;
        public UIntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public Point pt;
        public uint lPrivate;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct KbdLlHookStruct
    {
        public uint vkCode;
        public uint scanCode;
        public uint flags;
        public uint time;
        public UIntPtr dwExtraInfo;
    }
}
