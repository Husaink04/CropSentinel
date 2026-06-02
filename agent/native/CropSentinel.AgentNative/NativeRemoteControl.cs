using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;

namespace CropSentinel.AgentNative;

public sealed class NativeRemoteInputExecutor
{
    private readonly ILogger<NativeRemoteInputExecutor> _logger;
    private readonly HashSet<ushort> _heldKeys = [];

    public NativeRemoteInputExecutor(ILogger<NativeRemoteInputExecutor> logger)
    {
        _logger = logger;
    }

    public void Execute(JsonElement payload)
    {
        var type = payload.TryGetProperty("type", out var typeProperty) ? typeProperty.GetString() ?? "" : "";
        switch (type)
        {
            case "mousemove":
                SetCursorPos(ReadInt(payload, "x"), ReadInt(payload, "y"));
                break;
            case "mousedown":
                HandleMouseButton(ReadInt(payload, "button"), true);
                break;
            case "mouseup":
                HandleMouseButton(ReadInt(payload, "button"), false);
                break;
            case "dblclick":
                var button = ReadInt(payload, "button");
                HandleMouseButton(button, true);
                HandleMouseButton(button, false);
                HandleMouseButton(button, true);
                HandleMouseButton(button, false);
                break;
            case "scroll":
                HandleScroll(payload);
                break;
            case "keydown":
                HandleKeyDown(payload);
                break;
            case "keyup":
                HandleKeyUp(payload);
                break;
            case "text":
                HandleText(payload.TryGetProperty("text", out var textProperty) ? textProperty.GetString() ?? "" : "");
                break;
            case "command":
                HandleCommand(payload.TryGetProperty("action", out var actionProperty) ? actionProperty.GetString() ?? "" : "");
                break;
            case "shortcut":
                HandleShortcut(payload.TryGetProperty("action", out var shortcutProperty) ? shortcutProperty.GetString() ?? "" : "");
                break;
        }
    }

    public void ReleaseAllKeys()
    {
        foreach (var key in _heldKeys.ToArray())
        {
            SendKeyboardInput(key, true);
            _heldKeys.Remove(key);
        }
    }

    private void HandleMouseButton(int button, bool down)
    {
        var flag = (button, down) switch
        {
            (2, true) => MOUSEEVENTF_RIGHTDOWN,
            (2, false) => MOUSEEVENTF_RIGHTUP,
            (1, true) => MOUSEEVENTF_MIDDLEDOWN,
            (1, false) => MOUSEEVENTF_MIDDLEUP,
            (_, true) => MOUSEEVENTF_LEFTDOWN,
            _ => MOUSEEVENTF_LEFTUP,
        };

        mouse_event(flag, 0, 0, 0, UIntPtr.Zero);
    }

    private static void HandleScroll(JsonElement payload)
    {
        var amount = Math.Clamp(ReadInt(payload, "amount", 1), 1, 20);
        var direction = payload.TryGetProperty("dir", out var dirProperty) ? dirProperty.GetString() ?? "down" : "down";
        var delta = direction switch
        {
            "up" => 120 * amount,
            "down" => -120 * amount,
            "right" => 120 * amount,
            "left" => -120 * amount,
            _ => -120 * amount,
        };

        var flag = direction is "left" or "right" ? MOUSEEVENTF_HWHEEL : MOUSEEVENTF_WHEEL;
        mouse_event(flag, 0, 0, unchecked((uint)delta), UIntPtr.Zero);
    }

    private void HandleKeyDown(JsonElement payload)
    {
        var key = ResolveVirtualKey(payload);
        if (key == 0 || _heldKeys.Contains(key))
        {
            return;
        }

        _heldKeys.Add(key);
        SendKeyboardInput(key, false);
    }

    private void HandleKeyUp(JsonElement payload)
    {
        var key = ResolveVirtualKey(payload);
        if (key == 0)
        {
            return;
        }

        SendKeyboardInput(key, true);
        _heldKeys.Remove(key);
    }

    private void HandleText(string text)
    {
        if (string.IsNullOrEmpty(text))
        {
            return;
        }

        foreach (var ch in text)
        {
            SendUnicodeChar(ch);
        }
    }

    private void HandleCommand(string action)
    {
        if (string.IsNullOrWhiteSpace(action))
        {
            return;
        }

        if (CommandKeys.TryGetValue(action.Trim().ToLowerInvariant(), out var key))
        {
            PressKey(key);
        }
    }

    private void HandleShortcut(string action)
    {
        if (string.IsNullOrWhiteSpace(action))
        {
            return;
        }

        action = action.Trim().ToLowerInvariant();
        if (action.StartsWith("alt_", StringComparison.Ordinal))
        {
            var suffix = action[4..];
            if (TryResolvePrintableVirtualKey(suffix, out var altKey))
            {
                PressCombo(VK_MENU, altKey);
            }
            return;
        }

        if (ShortcutKeys.TryGetValue(action, out var target))
        {
            if (action == "redo")
            {
                PressCombo(VK_CONTROL, target);
            }
            else
            {
                PressCombo(VK_CONTROL, target);
            }
        }
    }

    private static ushort ResolveVirtualKey(JsonElement payload)
    {
        var code = payload.TryGetProperty("code", out var codeProperty) ? codeProperty.GetString() ?? "" : "";
        var key = payload.TryGetProperty("key", out var keyProperty) ? keyProperty.GetString() ?? "" : "";

        if (KeyCodeMap.TryGetValue(code, out var mapped))
        {
            return mapped;
        }

        if (!string.IsNullOrEmpty(key) && TryResolvePrintableVirtualKey(key, out var printable))
        {
            return printable;
        }

        return 0;
    }

    private static bool TryResolvePrintableVirtualKey(string key, out ushort value)
    {
        value = 0;
        if (string.IsNullOrWhiteSpace(key))
        {
            return false;
        }

        var ch = key[0];
        if (char.IsLetter(ch))
        {
            value = (ushort)char.ToUpperInvariant(ch);
            return true;
        }

        if (char.IsDigit(ch))
        {
            value = ch;
            return true;
        }

        return PrintableKeyMap.TryGetValue(ch, out value);
    }

    private static void PressKey(ushort key)
    {
        SendKeyboardInput(key, false);
        SendKeyboardInput(key, true);
    }

    private static void PressCombo(ushort modifier, ushort key)
    {
        SendKeyboardInput(modifier, false);
        SendKeyboardInput(key, false);
        SendKeyboardInput(key, true);
        SendKeyboardInput(modifier, true);
    }

    private static void SendKeyboardInput(ushort key, bool keyUp)
    {
        var input = new INPUT
        {
            type = INPUT_KEYBOARD,
            U = new InputUnion
            {
                ki = new KEYBDINPUT
                {
                    wVk = key,
                    dwFlags = keyUp ? KEYEVENTF_KEYUP : 0,
                },
            },
        };

        SendInput(1, [input], Marshal.SizeOf<INPUT>());
    }

    private static void SendUnicodeChar(char ch)
    {
        var down = new INPUT
        {
            type = INPUT_KEYBOARD,
            U = new InputUnion
            {
                ki = new KEYBDINPUT
                {
                    wScan = ch,
                    dwFlags = KEYEVENTF_UNICODE,
                },
            },
        };

        var up = new INPUT
        {
            type = INPUT_KEYBOARD,
            U = new InputUnion
            {
                ki = new KEYBDINPUT
                {
                    wScan = ch,
                    dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                },
            },
        };

        SendInput(2, [down, up], Marshal.SizeOf<INPUT>());
    }

    private static int ReadInt(JsonElement payload, string property, int fallback = 0)
    {
        return payload.TryGetProperty(property, out var value) && value.TryGetInt32(out var parsed) ? parsed : fallback;
    }

    private static readonly Dictionary<string, ushort> CommandKeys = new(StringComparer.OrdinalIgnoreCase)
    {
        ["enter"] = VK_RETURN,
        ["backspace"] = VK_BACK,
        ["delete"] = VK_DELETE,
        ["tab"] = VK_TAB,
        ["escape"] = VK_ESCAPE,
        ["up"] = VK_UP,
        ["down"] = VK_DOWN,
        ["left"] = VK_LEFT,
        ["right"] = VK_RIGHT,
        ["home"] = VK_HOME,
        ["end"] = VK_END,
        ["pageup"] = VK_PRIOR,
        ["pagedown"] = VK_NEXT,
        ["insert"] = VK_INSERT,
        ["printscreen"] = VK_SNAPSHOT,
        ["capslock"] = VK_CAPITAL,
        ["numlock"] = VK_NUMLOCK,
        ["scrolllock"] = VK_SCROLL,
        ["pause"] = VK_PAUSE,
        ["f1"] = VK_F1,
        ["f2"] = VK_F2,
        ["f3"] = VK_F3,
        ["f4"] = VK_F4,
        ["f5"] = VK_F5,
        ["f6"] = VK_F6,
        ["f7"] = VK_F7,
        ["f8"] = VK_F8,
        ["f9"] = VK_F9,
        ["f10"] = VK_F10,
        ["f11"] = VK_F11,
        ["f12"] = VK_F12,
    };

    private static readonly Dictionary<string, ushort> ShortcutKeys = new(StringComparer.OrdinalIgnoreCase)
    {
        ["copy"] = (ushort)'C',
        ["paste"] = (ushort)'V',
        ["cut"] = (ushort)'X',
        ["undo"] = (ushort)'Z',
        ["redo"] = (ushort)'Y',
        ["selectall"] = (ushort)'A',
        ["save"] = (ushort)'S',
        ["print"] = (ushort)'P',
        ["find"] = (ushort)'F',
        ["closewindow"] = (ushort)'W',
        ["newtab"] = (ushort)'T',
        ["newwindow"] = (ushort)'N',
        ["reload"] = (ushort)'R',
        ["focusbar"] = (ushort)'L',
        ["bookmark"] = (ushort)'D',
    };

    private static readonly Dictionary<char, ushort> PrintableKeyMap = new()
    {
        [' '] = VK_SPACE,
        [';'] = VK_OEM_1,
        ['='] = VK_OEM_PLUS,
        [','] = VK_OEM_COMMA,
        ['-'] = VK_OEM_MINUS,
        ['.'] = VK_OEM_PERIOD,
        ['/'] = VK_OEM_2,
        ['`'] = VK_OEM_3,
        ['['] = VK_OEM_4,
        ['\\'] = VK_OEM_5,
        [']'] = VK_OEM_6,
        ['\''] = VK_OEM_7,
    };

    private static readonly Dictionary<string, ushort> KeyCodeMap = new(StringComparer.Ordinal)
    {
        ["ControlLeft"] = VK_LCONTROL,
        ["ControlRight"] = VK_RCONTROL,
        ["ShiftLeft"] = VK_LSHIFT,
        ["ShiftRight"] = VK_RSHIFT,
        ["AltLeft"] = VK_LMENU,
        ["AltRight"] = VK_RMENU,
        ["MetaLeft"] = VK_LWIN,
        ["MetaRight"] = VK_RWIN,
        ["Enter"] = VK_RETURN,
        ["Tab"] = VK_TAB,
        ["Backspace"] = VK_BACK,
        ["Escape"] = VK_ESCAPE,
        ["Space"] = VK_SPACE,
        ["ArrowUp"] = VK_UP,
        ["ArrowDown"] = VK_DOWN,
        ["ArrowLeft"] = VK_LEFT,
        ["ArrowRight"] = VK_RIGHT,
        ["Home"] = VK_HOME,
        ["End"] = VK_END,
        ["PageUp"] = VK_PRIOR,
        ["PageDown"] = VK_NEXT,
        ["Insert"] = VK_INSERT,
        ["Delete"] = VK_DELETE,
        ["PrintScreen"] = VK_SNAPSHOT,
        ["CapsLock"] = VK_CAPITAL,
        ["NumLock"] = VK_NUMLOCK,
        ["ScrollLock"] = VK_SCROLL,
        ["Pause"] = VK_PAUSE,
        ["F1"] = VK_F1,
        ["F2"] = VK_F2,
        ["F3"] = VK_F3,
        ["F4"] = VK_F4,
        ["F5"] = VK_F5,
        ["F6"] = VK_F6,
        ["F7"] = VK_F7,
        ["F8"] = VK_F8,
        ["F9"] = VK_F9,
        ["F10"] = VK_F10,
        ["F11"] = VK_F11,
        ["F12"] = VK_F12,
    };

    private const uint INPUT_MOUSE = 0;
    private const uint INPUT_KEYBOARD = 1;
    private const uint KEYEVENTF_KEYUP = 0x0002;
    private const uint KEYEVENTF_UNICODE = 0x0004;
    private const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    private const uint MOUSEEVENTF_LEFTUP = 0x0004;
    private const uint MOUSEEVENTF_RIGHTDOWN = 0x0008;
    private const uint MOUSEEVENTF_RIGHTUP = 0x0010;
    private const uint MOUSEEVENTF_MIDDLEDOWN = 0x0020;
    private const uint MOUSEEVENTF_MIDDLEUP = 0x0040;
    private const uint MOUSEEVENTF_WHEEL = 0x0800;
    private const uint MOUSEEVENTF_HWHEEL = 0x01000;

    private const ushort VK_BACK = 0x08;
    private const ushort VK_TAB = 0x09;
    private const ushort VK_RETURN = 0x0D;
    private const ushort VK_SHIFT = 0x10;
    private const ushort VK_CONTROL = 0x11;
    private const ushort VK_MENU = 0x12;
    private const ushort VK_PAUSE = 0x13;
    private const ushort VK_CAPITAL = 0x14;
    private const ushort VK_ESCAPE = 0x1B;
    private const ushort VK_SPACE = 0x20;
    private const ushort VK_PRIOR = 0x21;
    private const ushort VK_NEXT = 0x22;
    private const ushort VK_END = 0x23;
    private const ushort VK_HOME = 0x24;
    private const ushort VK_LEFT = 0x25;
    private const ushort VK_UP = 0x26;
    private const ushort VK_RIGHT = 0x27;
    private const ushort VK_DOWN = 0x28;
    private const ushort VK_SNAPSHOT = 0x2C;
    private const ushort VK_INSERT = 0x2D;
    private const ushort VK_DELETE = 0x2E;
    private const ushort VK_LWIN = 0x5B;
    private const ushort VK_RWIN = 0x5C;
    private const ushort VK_NUMLOCK = 0x90;
    private const ushort VK_SCROLL = 0x91;
    private const ushort VK_LSHIFT = 0xA0;
    private const ushort VK_RSHIFT = 0xA1;
    private const ushort VK_LCONTROL = 0xA2;
    private const ushort VK_RCONTROL = 0xA3;
    private const ushort VK_LMENU = 0xA4;
    private const ushort VK_RMENU = 0xA5;
    private const ushort VK_OEM_1 = 0xBA;
    private const ushort VK_OEM_PLUS = 0xBB;
    private const ushort VK_OEM_COMMA = 0xBC;
    private const ushort VK_OEM_MINUS = 0xBD;
    private const ushort VK_OEM_PERIOD = 0xBE;
    private const ushort VK_OEM_2 = 0xBF;
    private const ushort VK_OEM_3 = 0xC0;
    private const ushort VK_OEM_4 = 0xDB;
    private const ushort VK_OEM_5 = 0xDC;
    private const ushort VK_OEM_6 = 0xDD;
    private const ushort VK_OEM_7 = 0xDE;
    private const ushort VK_F1 = 0x70;
    private const ushort VK_F2 = 0x71;
    private const ushort VK_F3 = 0x72;
    private const ushort VK_F4 = 0x73;
    private const ushort VK_F5 = 0x74;
    private const ushort VK_F6 = 0x75;
    private const ushort VK_F7 = 0x76;
    private const ushort VK_F8 = 0x77;
    private const ushort VK_F9 = 0x78;
    private const ushort VK_F10 = 0x79;
    private const ushort VK_F11 = 0x7A;
    private const ushort VK_F12 = 0x7B;

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern void mouse_event(uint dwFlags, int dx, int dy, uint dwData, UIntPtr dwExtraInfo);

    [StructLayout(LayoutKind.Sequential)]
    private struct INPUT
    {
        public uint type;
        public InputUnion U;
    }

    [StructLayout(LayoutKind.Explicit)]
    private struct InputUnion
    {
        [FieldOffset(0)]
        public KEYBDINPUT ki;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct KEYBDINPUT
    {
        public ushort wVk;
        public ushort wScan;
        public uint dwFlags;
        public uint time;
        public UIntPtr dwExtraInfo;
    }
}

public sealed class NativeRemoteCommandExecutor
{
    private readonly ILogger<NativeRemoteCommandExecutor> _logger;

    public NativeRemoteCommandExecutor(ILogger<NativeRemoteCommandExecutor> logger)
    {
        _logger = logger;
    }

    public RemoteCommandResult Execute(string action, string value)
    {
        action = (action ?? "").Trim().ToLowerInvariant();
        return action switch
        {
            "lock_screen" => Run(action, "rundll32.exe", "user32.dll,LockWorkStation"),
            "show_message" => Run(action, "msg.exe", $"* {value}"),
            "open_url" => Run(action, "cmd.exe", $"/c start \"\" \"{value}\""),
            "sleep" => Run(action, "rundll32.exe", "powrprof.dll,SetSuspendState 0,1,0"),
            "logout_user" => Run(action, "shutdown.exe", "/l"),
            "ctrl_alt_del" => Unsupported(action, "Secure attention sequence is not supported from the native agent."),
            "mute_audio" => Unsupported(action, "Audio mute control is not yet implemented in the native agent."),
            "unmute_audio" => Unsupported(action, "Audio mute control is not yet implemented in the native agent."),
            _ => Unsupported(action, "Unsupported remote command"),
        };
    }

    private RemoteCommandResult Run(string action, string fileName, string arguments)
    {
        try
        {
            using var process = Process.Start(new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            });

            return new RemoteCommandResult(action, "sent", "OK");
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Remote command failed: {Action}", action);
            return new RemoteCommandResult(action, "error", ex.Message);
        }
    }

    private static RemoteCommandResult Unsupported(string action, string detail)
    {
        return new RemoteCommandResult(action, "unsupported", detail);
    }
}

public sealed record RemoteCommandResult(string Action, string Status, string Detail);

public sealed class NativeFileTransferHandler
{
    private const int ChunkSize = 65536;
    private readonly ILogger<NativeFileTransferHandler> _logger;
    private readonly string _downloadDirectory;
    private readonly Dictionary<string, IncomingTransfer> _incoming = new(StringComparer.Ordinal);
    private readonly object _gate = new();

    public NativeFileTransferHandler(ILogger<NativeFileTransferHandler> logger)
    {
        _logger = logger;
        _downloadDirectory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "CropSentinel_Downloads");
    }

    public IEnumerable<(bool IsBinary, byte[] Payload)> OnStringMessage(string message)
    {
        if (string.IsNullOrWhiteSpace(message))
        {
            yield break;
        }

        using var document = JsonDocument.Parse(message);
        var root = document.RootElement;
        var type = root.TryGetProperty("type", out var typeProperty) ? typeProperty.GetString() ?? "" : "";
        if (type == "file_offer")
        {
            var id = root.GetProperty("id").GetString() ?? "";
            var name = root.GetProperty("name").GetString() ?? "file.bin";
            var size = root.TryGetProperty("size", out var sizeProperty) ? sizeProperty.GetInt64() : 0;
            if (!string.IsNullOrWhiteSpace(id))
            {
                Directory.CreateDirectory(_downloadDirectory);
                lock (_gate)
                {
                    _incoming[id] = new IncomingTransfer(id, SanitizeFileName(name), size, _downloadDirectory);
                }

                yield return (false, Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new { type = "file_accept", id })));
            }
        }
        else if (type == "file_complete")
        {
            var id = root.GetProperty("id").GetString() ?? "";
            var sha256 = root.TryGetProperty("sha256", out var hashProperty) ? hashProperty.GetString() ?? "" : "";
            IncomingTransfer? transfer;
            lock (_gate)
            {
                _incoming.TryGetValue(id, out transfer);
                if (transfer is not null)
                {
                    _incoming.Remove(id);
                }
            }

            if (transfer is not null)
            {
                var ok = transfer.FinalizeFile(sha256, out var finalPath);
                _logger.LogInformation("Remote file transfer complete. Ok={Ok} Path={Path}", ok, finalPath);
                yield return (false, Encoding.UTF8.GetBytes(JsonSerializer.Serialize(new { type = ok ? "file_ack" : "file_reject", id })));
            }
        }
    }

    public void OnBinaryMessage(byte[] payload)
    {
        if (payload.Length <= 36)
        {
            return;
        }

        var id = Encoding.ASCII.GetString(payload, 0, 36);
        IncomingTransfer? transfer;
        lock (_gate)
        {
            _incoming.TryGetValue(id, out transfer);
        }

        transfer?.Append(payload.AsSpan(36));
    }

    private static string SanitizeFileName(string name)
    {
        var cleaned = Path.GetFileName(name);
        foreach (var invalid in Path.GetInvalidFileNameChars())
        {
            cleaned = cleaned.Replace(invalid, '_');
        }

        return string.IsNullOrWhiteSpace(cleaned) ? "download.bin" : cleaned;
    }

    private sealed class IncomingTransfer
    {
        private readonly string _fileName;
        private readonly string _tempPath;
        private readonly FileStream _stream;
        private readonly IncrementalHash _hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);

        public IncomingTransfer(string id, string fileName, long size, string downloadDirectory)
        {
            Id = id;
            _fileName = fileName;
            ExpectedSize = size;
            _tempPath = Path.Combine(downloadDirectory, $".ft_{id}.tmp");
            _stream = new FileStream(_tempPath, FileMode.Create, FileAccess.Write, FileShare.None);
        }

        public string Id { get; }
        public long ExpectedSize { get; }
        public long Received { get; private set; }

        public void Append(ReadOnlySpan<byte> data)
        {
            _stream.Write(data);
            _hash.AppendData(data);
            Received += data.Length;
        }

        public bool FinalizeFile(string expectedSha256, out string finalPath)
        {
            _stream.Dispose();
            finalPath = "";
            var actualHash = Convert.ToHexString(_hash.GetHashAndReset()).ToLowerInvariant();
            if (!string.IsNullOrWhiteSpace(expectedSha256) && !string.Equals(actualHash, expectedSha256.Trim().ToLowerInvariant(), StringComparison.Ordinal))
            {
                File.Delete(_tempPath);
                return false;
            }

            finalPath = Path.Combine(Path.GetDirectoryName(_tempPath)!, _fileName);
            var suffix = 1;
            while (File.Exists(finalPath))
            {
                var stem = Path.GetFileNameWithoutExtension(_fileName);
                var ext = Path.GetExtension(_fileName);
                finalPath = Path.Combine(Path.GetDirectoryName(_tempPath)!, $"{stem}_{suffix++}{ext}");
            }

            File.Move(_tempPath, finalPath, overwrite: false);
            return true;
        }
    }
}
