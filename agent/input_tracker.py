"""
Tier B input activity (Windows + macOS): keycode n-gram hashes, mouse counts,
foreground window context. No raw keystroke text is transmitted.
"""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Callable, List, Optional

NGRAM_SIZE = 8


def _key_code_for_ngram(key) -> int:
    """Map pynput key to a numeric code for local hashing only (not sent raw)."""
    try:
        from pynput.keyboard import Key, KeyCode

        if isinstance(key, KeyCode):
            if key.vk is not None:
                return int(key.vk) & 0xFFFF
            if key.char:
                c = key.char[0]
                return 0x8000 + (ord(c) & 0xFF)
            return 0xC0FF
        name = getattr(key, "name", None) or repr(key)
        return 0xD000 + (hash(name) % 4096)
    except Exception:
        return 0xC0FF


def _ngrams_to_hashes(codes: List[int]) -> List[str]:
    hashes: List[str] = []
    i = 0
    n = len(codes)
    while i + NGRAM_SIZE <= n:
        chunk = tuple(codes[i : i + NGRAM_SIZE])
        i += NGRAM_SIZE
        h = hashlib.sha256(repr(chunk).encode()).hexdigest()[:32]
        hashes.append(h)
    rest = codes[i:]
    if len(rest) >= 4:
        h = hashlib.sha256(repr(("partial", tuple(rest))).encode()).hexdigest()[:32]
        hashes.append(h)
    return hashes


class InputTracker:
    """
    Background thread: pynput listeners + periodic bucket flush via enqueue_fn.
    """

    def __init__(
        self,
        machine_id: str,
        utc_iso_fn: Callable[[], str],
        get_window_fn: Callable[[], tuple],
        enqueue_fn: Callable[[str, dict], None],
        bucket_seconds: int = 30,
    ):
        self.machine_id = machine_id
        self._utc_iso = utc_iso_fn
        self._get_window = get_window_fn
        self._enqueue = enqueue_fn
        self.bucket_seconds = max(10, min(300, int(bucket_seconds)))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._codes: List[int] = []
        self._key_count = 0
        self._clicks = 0
        self._scrolls = 0
        self._prev_bucket_end: Optional[str] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="CropProInputTracker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        try:
            from pynput import keyboard, mouse
        except ImportError:
            return

        def on_press(key):
            try:
                with self._lock:
                    self._key_count += 1
                    self._codes.append(_key_code_for_ngram(key))
            except Exception:
                pass

        def on_click(_x, _y, _button, pressed):
            if not pressed:
                return
            try:
                with self._lock:
                    self._clicks += 1
            except Exception:
                pass

        def on_scroll(*_a):
            try:
                with self._lock:
                    self._scrolls += 1
            except Exception:
                pass

        k_listener = keyboard.Listener(on_press=on_press)
        m_listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
        k_listener.start()
        m_listener.start()

        try:
            while not self._stop.wait(self.bucket_seconds):
                self._flush()
            self._flush()
        finally:
            try:
                k_listener.stop()
            except Exception:
                pass
            try:
                m_listener.stop()
            except Exception:
                pass

    def _flush(self) -> None:
        with self._lock:
            codes = self._codes[:]
            self._codes.clear()
            kc = self._key_count
            self._key_count = 0
            clicks = self._clicks
            self._clicks = 0
            scrolls = self._scrolls
            self._scrolls = 0

        if kc == 0 and clicks == 0 and scrolls == 0:
            return

        pattern_hashes = _ngrams_to_hashes(codes)
        bucket_end = self._utc_iso()
        bucket_start = self._prev_bucket_end or bucket_end
        self._prev_bucket_end = bucket_end

        try:
            app_name, title, proc = self._get_window()
        except Exception:
            app_name, title, proc = "Unknown", "", "unknown"

        payload = {
            "machine_id": self.machine_id,
            "timestamp": bucket_end,
            "bucket_start": bucket_start,
            "bucket_end": bucket_end,
            "process_name": (proc or app_name or "")[:200],
            "window_title": (title or "")[:200],
            "key_event_count": kc,
            "mouse_click_count": clicks,
            "mouse_scroll_count": scrolls,
            "pattern_hashes": pattern_hashes,
            "ngram_size": NGRAM_SIZE,
        }
        self._enqueue("input", payload)


def supported_platform() -> bool:
    import platform

    return platform.system() in ("Windows", "Darwin")
