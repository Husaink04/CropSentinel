"""
Browser KeyboardEvent.code -> pyautogui key name mapping.
Comprehensive cross-platform mapping for raw keyboard input over WebRTC.
"""
import platform

_IS_MAC = platform.system() == "Darwin"

# Meta key differs per platform
_META = "command" if _IS_MAC else "win"

# Maps browser KeyboardEvent.code values to pyautogui key names
BROWSER_CODE_TO_KEY: dict[str, str] = {
    # ── Letters ───────────────────────────────────────────────────────────────
    "KeyA": "a", "KeyB": "b", "KeyC": "c", "KeyD": "d", "KeyE": "e",
    "KeyF": "f", "KeyG": "g", "KeyH": "h", "KeyI": "i", "KeyJ": "j",
    "KeyK": "k", "KeyL": "l", "KeyM": "m", "KeyN": "n", "KeyO": "o",
    "KeyP": "p", "KeyQ": "q", "KeyR": "r", "KeyS": "s", "KeyT": "t",
    "KeyU": "u", "KeyV": "v", "KeyW": "w", "KeyX": "x", "KeyY": "y",
    "KeyZ": "z",

    # ── Digits ────────────────────────────────────────────────────────────────
    "Digit0": "0", "Digit1": "1", "Digit2": "2", "Digit3": "3",
    "Digit4": "4", "Digit5": "5", "Digit6": "6", "Digit7": "7",
    "Digit8": "8", "Digit9": "9",

    # ── Function keys ─────────────────────────────────────────────────────────
    "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4", "F5": "f5",
    "F6": "f6", "F7": "f7", "F8": "f8", "F9": "f9", "F10": "f10",
    "F11": "f11", "F12": "f12", "F13": "f13", "F14": "f14", "F15": "f15",
    "F16": "f16", "F17": "f17", "F18": "f18", "F19": "f19", "F20": "f20",
    "F21": "f21", "F22": "f22", "F23": "f23", "F24": "f24",

    # ── Modifiers ─────────────────────────────────────────────────────────────
    "ShiftLeft": "shiftleft", "ShiftRight": "shiftright",
    "ControlLeft": "ctrlleft", "ControlRight": "ctrlright",
    "AltLeft": "altleft", "AltRight": "altright",
    "MetaLeft": _META, "MetaRight": _META,

    # ── Navigation ────────────────────────────────────────────────────────────
    "ArrowUp": "up", "ArrowDown": "down",
    "ArrowLeft": "left", "ArrowRight": "right",
    "Home": "home", "End": "end",
    "PageUp": "pageup", "PageDown": "pagedown",

    # ── Editing ───────────────────────────────────────────────────────────────
    "Backspace": "backspace", "Delete": "delete",
    "Enter": "enter", "NumpadEnter": "enter",
    "Tab": "tab", "Escape": "escape",
    "Insert": "insert",

    # ── Whitespace / special ──────────────────────────────────────────────────
    "Space": "space",
    "CapsLock": "capslock",
    "NumLock": "numlock",
    "ScrollLock": "scrolllock",
    "PrintScreen": "printscreen",
    "Pause": "pause",
    "ContextMenu": "apps",

    # ── Punctuation / symbols ─────────────────────────────────────────────────
    "Backquote": "`", "Minus": "-", "Equal": "=",
    "BracketLeft": "[", "BracketRight": "]",
    "Backslash": "\\", "Semicolon": ";", "Quote": "'",
    "Comma": ",", "Period": ".", "Slash": "/",
    "IntlBackslash": "\\",

    # ── Numpad ────────────────────────────────────────────────────────────────
    "Numpad0": "num0", "Numpad1": "num1", "Numpad2": "num2",
    "Numpad3": "num3", "Numpad4": "num4", "Numpad5": "num5",
    "Numpad6": "num6", "Numpad7": "num7", "Numpad8": "num8",
    "Numpad9": "num9",
    "NumpadAdd": "add", "NumpadSubtract": "subtract",
    "NumpadMultiply": "multiply", "NumpadDivide": "divide",
    "NumpadDecimal": "decimal",
}

# Modifier code → pyautogui modifier name (for building hotkeys)
MODIFIER_CODES: dict[str, str] = {
    "ControlLeft": "ctrl", "ControlRight": "ctrl",
    "ShiftLeft": "shift", "ShiftRight": "shift",
    "AltLeft": "alt", "AltRight": "alt",
    "MetaLeft": _META, "MetaRight": _META,
}


def resolve_key(code: str, key: str = "") -> str | None:
    """
    Resolve a browser KeyboardEvent to a pyautogui key name.
    Falls back to the 'key' value for unmapped codes.
    Returns None if the key can't be mapped.
    """
    mapped = BROWSER_CODE_TO_KEY.get(code)
    if mapped:
        return mapped
    # Fallback: use the key value if it's a single printable character
    if key and len(key) == 1:
        return key
    return None


def is_modifier(code: str) -> bool:
    """Check if a browser code is a modifier key."""
    return code in MODIFIER_CODES
