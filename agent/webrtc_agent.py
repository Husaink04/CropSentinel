"""
CropSentinel Agent — WebRTC Screen Broadcaster  (v3, frame delivery fixed)
======================================================================
Key changes from v2:
  - Frame queue uses threading.Queue (thread-safe) instead of asyncio.Queue
  - recv() uses loop.run_in_executor to block on threading.Queue.get() without
    holding the event loop — this is the correct pattern for aiortc custom tracks
  - asyncio.Queue was being filled from a non-async thread via put_nowait()
    which is NOT thread-safe; threading.Queue is safe to call from any thread
  - ScreenGrabber now uses mss context manager per-grab to avoid stale state

Screen capture order:
  1. mss            — fastest, zero-copy, all platforms
  2. PIL.ImageGrab  — fallback Windows / macOS
  3. scrot          — Linux subprocess fallback
"""

import asyncio
import fractions
import json
import logging
import os
import platform
import queue          # threading.Queue — thread-safe, no event loop needed
import threading
import time
from typing import Dict, Optional, Callable

logger = logging.getLogger("croppro.webrtc")

# ── config ────────────────────────────────────────────────────────────────────
WEBRTC_FPS = int(os.environ.get("WEBRTC_FPS", "10"))
ICE_SERVERS = [{"urls": ["stun:stun.l.google.com:19302",
                          "stun:stun1.l.google.com:19302"]}]
_TURN_URL  = os.environ.get("WEBRTC_TURN_URL",  "")
_TURN_USER = os.environ.get("WEBRTC_TURN_USER", "")
_TURN_PASS = os.environ.get("WEBRTC_TURN_PASS", "")

OS = platform.system()

# ── dependency check ──────────────────────────────────────────────────────────
def _check_deps():
    missing = []
    for pkg in ("aiortc", "av", "numpy"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        return False, f"Missing: {', '.join(missing)} — run: pip install aiortc av numpy mss"
    return True, ""

_DEPS_OK, _DEPS_REASON = _check_deps()


# ── Linux display detection ──────────────────────────────────────────────────

def _ensure_linux_display():
    """
    On Linux, screen capture requires DISPLAY (X11) or WAYLAND_DISPLAY.
    If the agent is started from a service/SSH without inheriting the display,
    auto-detect it from running X/Wayland sessions.
    """
    if OS != "Linux":
        return

    # Already set — nothing to do
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return

    # Try to find DISPLAY from existing X sessions
    try:
        import subprocess
        # Method 1: Check /tmp/.X11-unix for X sockets
        x11_dir = "/tmp/.X11-unix"
        if os.path.isdir(x11_dir):
            sockets = sorted(os.listdir(x11_dir))
            for s in sockets:
                if s.startswith("X"):
                    display = f":{s[1:]}"
                    os.environ["DISPLAY"] = display
                    logger.info(f"Auto-detected DISPLAY={display}")
                    return

        # Method 2: Parse from running processes
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "Xorg" in line or "Xwayland" in line:
                for part in line.split():
                    if part.startswith(":") and part[1:].split(".")[0].isdigit():
                        os.environ["DISPLAY"] = part
                        logger.info(f"Auto-detected DISPLAY={part} from process list")
                        return

        # Method 3: Check XDG_SESSION_TYPE for Wayland
        session_type = os.environ.get("XDG_SESSION_TYPE", "")
        if session_type == "wayland":
            os.environ.setdefault("WAYLAND_DISPLAY", "wayland-0")
            logger.info("Set WAYLAND_DISPLAY=wayland-0")
            return

        # Method 4: Default fallback
        os.environ["DISPLAY"] = ":0"
        logger.info("Defaulting DISPLAY=:0 (no session detected)")

    except Exception as e:
        os.environ["DISPLAY"] = ":0"
        logger.info(f"Defaulting DISPLAY=:0 (detection error: {e})")


# Run display detection at module load time
_ensure_linux_display()


# ── Linux XAUTHORITY detection ───────────────────────────────────────────────

def _ensure_xauthority():
    """
    On Linux, mss/scrot also need XAUTHORITY to authenticate with X server.
    If not set, find it from the current desktop user session.
    """
    if OS != "Linux":
        return
    if os.environ.get("XAUTHORITY"):
        return

    try:
        # Check common locations
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or "root"
        candidates = [
            f"/home/{user}/.Xauthority",
            f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*" if hasattr(os, 'getuid') else "",
            "/root/.Xauthority",
        ]
        for path in candidates:
            if path and os.path.exists(path):
                os.environ["XAUTHORITY"] = path
                logger.info(f"Auto-detected XAUTHORITY={path}")
                return

        # Glob for Xwayland auth
        import glob
        uid = os.getuid() if hasattr(os, 'getuid') else 0
        for pattern in [f"/run/user/{uid}/.mutter-Xwaylandauth.*",
                        f"/run/user/{uid}/xauth_*"]:
            matches = glob.glob(pattern)
            if matches:
                os.environ["XAUTHORITY"] = matches[0]
                logger.info(f"Auto-detected XAUTHORITY={matches[0]}")
                return

    except Exception as e:
        logger.debug(f"XAUTHORITY detection: {e}")


_ensure_xauthority()


# ── Screen grabber ────────────────────────────────────────────────────────────

class ScreenGrabber:
    """Grab full-screen frames as numpy RGB arrays. Auto-detects best backend."""

    def __init__(self):
        self._backend = self._detect()
        self._lock = threading.Lock()
        self._fail_count = 0
        logger.info(f"ScreenGrabber initialized: backend={self._backend}, "
                     f"DISPLAY={os.environ.get('DISPLAY','(unset)')}, "
                     f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY','(unset)')}")

    @staticmethod
    def _detect() -> str:
        # ── Try mss (fastest, all platforms) ─────────────────────────────────
        try:
            import mss as _m
            with _m.mss() as sct:
                # Test grab — catches X11 auth / display issues immediately
                mon = sct.monitors[1]
                sct.grab(mon)
            logger.info("Screen capture backend: mss (verified)")
            return "mss"
        except Exception as e:
            logger.warning(f"mss unavailable: {e}")

        # ── Try Pillow ImageGrab (works on all platforms with pyscreenshot) ──
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            if img:
                logger.info("Screen capture backend: pillow")
                return "pillow"
        except Exception as e:
            logger.debug(f"Pillow ImageGrab: {e}")

        # ── Try gnome-screenshot (common on Kali/GNOME/XFCE) ────────────────
        if OS == "Linux":
            import shutil
            for tool in ["gnome-screenshot", "xfce4-screenshooter", "scrot", "import"]:
                if shutil.which(tool):
                    logger.info(f"Screen capture backend: {tool}")
                    return tool

        # ── Fallback ─────────────────────────────────────────────────────────
        logger.warning("No working screen capture backend found!")
        return "none"

    def grab_rgb(self):
        """Return (ndarray[H,W,3], w, h) or (None, 0, 0)."""
        import numpy as np
        with self._lock:
            try:
                if self._backend == "mss":
                    import mss as _mss
                    with _mss.mss() as sct:
                        mon = sct.monitors[1]
                        shot = sct.grab(mon)
                        arr  = np.frombuffer(shot.raw, dtype=np.uint8).reshape(
                            shot.height, shot.width, 4)
                        # BGRA → RGB
                        self._fail_count = 0
                        return arr[:, :, 2::-1].copy(), shot.width, shot.height

                elif self._backend == "pillow":
                    from PIL import ImageGrab
                    img = ImageGrab.grab().convert("RGB")
                    self._fail_count = 0
                    return np.array(img), img.width, img.height

                elif self._backend in ("scrot", "gnome-screenshot",
                                        "xfce4-screenshooter", "import"):
                    return self._grab_linux_tool(np)

                elif self._backend == "none":
                    pass

            except Exception as e:
                self._fail_count += 1
                # Log first 3 failures at warning level, then reduce to debug
                if self._fail_count <= 3:
                    logger.warning(f"grab_rgb ({self._backend}): {e}")
                else:
                    logger.debug(f"grab_rgb ({self._backend}): {e}")

                # After 10 consecutive failures, try re-detecting backend
                if self._fail_count == 10:
                    logger.warning("10 consecutive grab failures — re-detecting backend")
                    self._backend = self._detect()
                    self._fail_count = 0

        return None, 0, 0

    def _grab_linux_tool(self, np):
        """Capture screen using a Linux CLI screenshot tool."""
        import subprocess, tempfile
        from PIL import Image

        tmp = tempfile.mktemp(suffix=".png")
        try:
            if self._backend == "gnome-screenshot":
                subprocess.run(
                    ["gnome-screenshot", "-f", tmp],
                    capture_output=True, timeout=5,
                    env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
                )
            elif self._backend == "xfce4-screenshooter":
                subprocess.run(
                    ["xfce4-screenshooter", "-f", "-s", tmp],
                    capture_output=True, timeout=5,
                    env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
                )
            elif self._backend == "scrot":
                subprocess.run(
                    ["scrot", tmp],
                    capture_output=True, timeout=5,
                    env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
                )
            elif self._backend == "import":
                # ImageMagick import
                subprocess.run(
                    ["import", "-window", "root", tmp],
                    capture_output=True, timeout=5,
                    env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
                )

            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                img = Image.open(tmp).convert("RGB")
                arr = np.array(img)
                self._fail_count = 0
                return arr, img.width, img.height

        finally:
            try: os.unlink(tmp)
            except OSError: pass

        return None, 0, 0


# ── Screen VideoStreamTrack ───────────────────────────────────────────────────

def _make_screen_track(fps: int = WEBRTC_FPS):
    """
    Factory — imports aiortc/av lazily.
    Returns a VideoStreamTrack instance that delivers live screen frames.

    Frame delivery uses threading.Queue + loop.run_in_executor:
      • _capture() thread fills a threading.Queue from any thread safely
      • recv() awaits loop.run_in_executor(None, q.get, timeout) — this
        blocks a thread-pool worker, NOT the event loop, and returns when
        a frame is ready; aiortc calls recv() to get the next frame to encode
    """
    from aiortc.mediastreams import MediaStreamError, VideoStreamTrack
    import av as _av

    class _ScreenTrack(VideoStreamTrack):
        kind = "video"

        def __init__(self):
            super().__init__()
            self._fps      = fps
            self._pts      = 0
            self._tb       = fractions.Fraction(1, 90_000)
            # threading.Queue is safe to write from any thread and read from any
            self._q: queue.Queue = queue.Queue(maxsize=4)
            self._grabber  = ScreenGrabber()
            self._running  = True
            self._thread   = threading.Thread(target=self._capture, daemon=True)
            self._thread.start()
            logger.info(f"ScreenTrack started at {fps} fps")

        def _capture(self):
            """Background thread: grab screen → encode → push to queue."""
            interval = 1.0 / self._fps
            while self._running:
                t0 = time.monotonic()
                arr, w, h = self._grabber.grab_rgb()
                if arr is not None and w and h:
                    try:
                        frame = _av.VideoFrame.from_ndarray(arr, format="rgb24")
                        frame = frame.reformat(format="yuv420p")
                        # Drop oldest frame if queue is full (keep latency low)
                        if self._q.full():
                            try: self._q.get_nowait()
                            except queue.Empty: pass
                        self._q.put_nowait(frame)
                    except Exception as e:
                        logger.debug(f"Frame encode error: {e}")
                elapsed = time.monotonic() - t0
                remaining = interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)

        def _blocking_get(self):
            """Called in a thread-pool executor — blocks until a frame is ready."""
            frame = self._q.get(timeout=5.0)   # raises queue.Empty on timeout
            if frame is None:
                raise MediaStreamError
            return frame

        async def recv(self):
            """
            Called by aiortc on the event loop to get the next frame.
            We offload the blocking queue.get() to a thread-pool worker so we
            never block the event loop.
            """
            step = int(90_000 / self._fps)
            loop = asyncio.get_event_loop()

            while True:
                try:
                    frame = await loop.run_in_executor(None, self._blocking_get)
                    break
                except MediaStreamError:
                    raise
                except queue.Empty:
                    # Capture thread slow or not started yet — retry
                    if not self._running:
                        raise MediaStreamError
                    logger.debug("recv: frame timeout, retrying")

            frame.pts       = self._pts
            frame.time_base = self._tb
            self._pts      += step
            return frame

        def stop(self):
            self._running = False
            try: self._q.put_nowait(None)   # unblock any waiting get()
            except Exception: pass
            self._grabber  # keep ref alive
            super().stop()
            logger.info("ScreenTrack stopped")

    return _ScreenTrack()


# ── Audio loopback track ─────────────────────────────────────────────────────

def _find_loopback_device():
    """Detect system audio loopback device (platform-specific). Returns device index or None."""
    try:
        import sounddevice as sd
    except ImportError:
        logger.info("sounddevice not installed — remote audio disabled. pip install sounddevice")
        return None

    if OS == "Windows":
        # WASAPI loopback devices have "(loopback)" in name
        try:
            hostapis = sd.query_hostapis()
            wasapi_idx = None
            for i, api in enumerate(hostapis):
                if "wasapi" in api["name"].lower():
                    wasapi_idx = i
                    break
            if wasapi_idx is None:
                return None
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                if d["hostapi"] == wasapi_idx and d["max_input_channels"] > 0:
                    if "loopback" in d["name"].lower() or "stereo mix" in d["name"].lower():
                        return i
            # Fallback: default WASAPI loopback
            for i, d in enumerate(devices):
                if d["hostapi"] == wasapi_idx and d["max_input_channels"] > 0:
                    return i
        except Exception as e:
            logger.debug(f"WASAPI loopback detection: {e}")
        return None

    elif OS == "Linux":
        # PulseAudio monitor source
        try:
            import subprocess
            result = subprocess.run(
                ["pactl", "list", "short", "sources"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if ".monitor" in line:
                    # Return the source name — we'll use it with sounddevice
                    parts = line.split()
                    if len(parts) >= 2:
                        return parts[1]  # source name like "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"
        except Exception as e:
            logger.debug(f"PulseAudio monitor detection: {e}")
        return None

    elif OS == "Darwin":
        # macOS: check for BlackHole or Soundflower virtual audio device
        try:
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                name_lower = d["name"].lower()
                if d["max_input_channels"] > 0 and ("blackhole" in name_lower or "soundflower" in name_lower):
                    return i
        except Exception:
            pass
        return None

    return None


def _make_audio_track(sample_rate=48000, channels=2, frame_duration_ms=20):
    """
    Factory — creates an AudioStreamTrack that captures system audio loopback.
    Same pattern as _make_screen_track(): background thread → threading.Queue → recv().
    Returns None if audio capture is unavailable.
    """
    device = _find_loopback_device()
    if device is None:
        logger.info("No loopback audio device found — audio track disabled")
        return None

    try:
        import sounddevice as sd
    except ImportError:
        return None

    from aiortc.mediastreams import AudioStreamTrack, MediaStreamError
    import av as _av
    import numpy as np

    samples_per_frame = int(sample_rate * frame_duration_ms / 1000)  # 960 for 20ms @ 48kHz

    class _AudioTrack(AudioStreamTrack):
        kind = "audio"

        def __init__(self):
            super().__init__()
            self._pts      = 0
            self._tb       = fractions.Fraction(1, sample_rate)
            self._q: queue.Queue = queue.Queue(maxsize=10)
            self._running  = True
            self._device   = device
            self._thread   = threading.Thread(target=self._capture, daemon=True)
            self._thread.start()
            logger.info(f"AudioTrack started (device={device}, {sample_rate}Hz, {channels}ch)")

        def _capture(self):
            """Background thread: capture audio from loopback and push to queue."""
            try:
                def callback(indata, frames, time_info, status):
                    if not self._running:
                        return
                    if status:
                        logger.debug(f"Audio capture status: {status}")
                    # indata is float32 numpy array [frames, channels]
                    # Convert to int16 for av.AudioFrame
                    audio_data = (indata * 32767).astype(np.int16).tobytes()
                    try:
                        if self._q.full():
                            try: self._q.get_nowait()
                            except queue.Empty: pass
                        self._q.put_nowait(audio_data)
                    except Exception:
                        pass

                with sd.InputStream(
                    device=self._device,
                    samplerate=sample_rate,
                    channels=channels,
                    dtype='float32',
                    blocksize=samples_per_frame,
                    callback=callback,
                ):
                    while self._running:
                        time.sleep(0.1)
            except Exception as e:
                logger.error(f"Audio capture error: {e}")
                self._running = False

        def _blocking_get(self):
            data = self._q.get(timeout=5.0)
            if data is None:
                raise MediaStreamError
            return data

        async def recv(self):
            import numpy as np
            loop = asyncio.get_event_loop()

            while True:
                try:
                    audio_bytes = await loop.run_in_executor(None, self._blocking_get)
                    break
                except MediaStreamError:
                    raise
                except queue.Empty:
                    if not self._running:
                        raise MediaStreamError

            # Build av.AudioFrame from raw int16 bytes
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
            # Reshape to [channels, samples] for av
            if channels > 1:
                audio_array = audio_array.reshape(-1, channels).T
            else:
                audio_array = audio_array.reshape(1, -1)

            frame = _av.AudioFrame.from_ndarray(audio_array, format='s16', layout='stereo' if channels == 2 else 'mono')
            frame.sample_rate = sample_rate
            frame.pts  = self._pts
            frame.time_base = self._tb
            self._pts += samples_per_frame
            return frame

        def stop(self):
            self._running = False
            try: self._q.put_nowait(None)
            except Exception: pass
            super().stop()
            logger.info("AudioTrack stopped")

    try:
        return _AudioTrack()
    except Exception as e:
        logger.error(f"AudioTrack creation failed: {e}")
        return None


# ── WebRTC session ────────────────────────────────────────────────────────────

class WebRTCSession:
    """One RTCPeerConnection per admin viewer. All async methods run on the agent's event loop."""

    def __init__(self, session_id: str, send_fn: Callable[[dict], None], session_kind: str = "live"):
        self.session_id = session_id
        self._send      = send_fn
        self.session_kind = str(session_kind or "live").lower()
        self._control_enabled = self.session_kind == "remote"
        self._pc        = None
        self._track     = None
        self._audio     = None
        self._ft_handler= None   # file transfer handler
        self._closed    = False

    def _ws(self, msg: dict):
        try:
            self._send(msg)
        except Exception as e:
            logger.debug(f"WebRTC ws send: {e}")

    async def start(self):
        if not _DEPS_OK:
            self._ws({
                "type": "webrtc_end",
                "session_id": self.session_id,
                "reason": f"agent_missing_deps: {_DEPS_REASON}",
            })
            return

        from aiortc import RTCPeerConnection, RTCIceServer, RTCConfiguration

        ice = list(ICE_SERVERS)
        if _TURN_URL:
            ice.append({"urls": [_TURN_URL], "username": _TURN_USER, "credential": _TURN_PASS})

        self._pc = RTCPeerConnection(
            configuration=RTCConfiguration(iceServers=[RTCIceServer(urls=s["urls"]) for s in ice])
        )

        try:
            self._track = _make_screen_track()
        except Exception as e:
            logger.error(f"Screen track creation failed: {e}")
            self._ws({"type": "webrtc_end", "session_id": self.session_id, "reason": str(e)})
            return

        self._pc.addTrack(self._track)
        logger.info(f"Screen track added to PC [{self.session_id[:8]}]")

        if self._control_enabled:
            # ── Audio track (optional — won't block video if unavailable) ──────
            try:
                self._audio = _make_audio_track()
                if self._audio:
                    self._pc.addTrack(self._audio)
                    logger.info(f"Audio track added to PC [{self.session_id[:8]}]")
            except Exception as e:
                logger.info(f"Audio track skipped: {e}")
                self._audio = None

            # ── File Transfer DataChannel ──────────────────────────────────────
            try:
                from file_transfer import FileTransferHandler
                ft_dc = self._pc.createDataChannel("filetransfer", ordered=True)
                self._ft_handler = FileTransferHandler(ft_dc)

                @ft_dc.on("open")
                def on_ft_open():
                    logger.info(f"File transfer DataChannel open [{self.session_id[:8]}]")

                @ft_dc.on("message")
                def on_ft_msg(message):
                    if self._ft_handler:
                        self._ft_handler.on_message(message)
            except ImportError:
                logger.info("file_transfer module not found — file transfer disabled")
            except Exception as e:
                logger.debug(f"File transfer DC setup: {e}")

            # ── DataChannel for receiving mouse/keyboard input from admin ──────
            try:
                dc = self._pc.createDataChannel("input", ordered=True)

                @dc.on("open")
                def on_dc_open():
                    logger.info(f"Input DataChannel open [{self.session_id[:8]}]")

                @dc.on("message")
                def on_dc_msg(message):
                    try:
                        input_executor.execute(json.loads(message))
                    except Exception as e:
                        logger.debug(f"Input DC msg: {e}")
            except Exception as e:
                logger.debug(f"DataChannel create: {e}")

            # Accept DCs opened by the browser (unified handler for both input + filetransfer)
            @self._pc.on("datachannel")
            def on_datachannel(channel):
                if channel.label == "input":
                    @channel.on("message")
                    def on_msg(message):
                        try:
                            input_executor.execute(json.loads(message))
                        except Exception as e:
                            logger.debug(f"Input DC (remote): {e}")
                elif channel.label == "filetransfer" and self._ft_handler is None:
                    try:
                        from file_transfer import FileTransferHandler
                        self._ft_handler = FileTransferHandler(channel)
                        @channel.on("message")
                        def on_ft_msg(message):
                            self._ft_handler.on_message(message)
                    except Exception:
                        pass

        @self._pc.on("icecandidate")
        async def on_ice(candidate):
            if candidate and not self._closed:
                self._ws({
                    "type":       "webrtc_ice",
                    "session_id": self.session_id,
                    "candidate": {
                        "sdpMid":        candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex,
                        "candidate":     candidate.candidate,
                    },
                })

        @self._pc.on("connectionstatechange")
        async def on_state():
            state = self._pc.connectionState if self._pc else "closed"
            logger.info(f"PC state [{self.session_id[:8]}]: {state}")
            if state in ("failed", "closed", "disconnected") and not self._closed:
                await self.stop()

        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)

        self._ws({
            "type":       "webrtc_offer",
            "session_id": self.session_id,
            "sdp": {
                "type": self._pc.localDescription.type,
                "sdp":  self._pc.localDescription.sdp,
            },
        })
        logger.info(f"SDP offer sent [{self.session_id[:8]}]")

    async def set_answer(self, sdp_obj: dict, ice_restart: bool = False):
        if not self._pc or self._closed:
            return
        from aiortc import RTCSessionDescription
        await self._pc.setRemoteDescription(
            RTCSessionDescription(sdp=sdp_obj["sdp"], type=sdp_obj["type"])
        )
        if ice_restart:
            logger.info(f"ICE restart applied [{self.session_id[:8]}]")
        else:
            logger.info(f"Answer applied [{self.session_id[:8]}]")

    async def add_ice_candidate(self, cand: dict):
        if not self._pc or self._closed or not cand:
            return
        from aiortc import RTCIceCandidate
        try:
            await self._pc.addIceCandidate(RTCIceCandidate(
                sdpMid        = cand.get("sdpMid"),
                sdpMLineIndex = cand.get("sdpMLineIndex", 0),
                candidate     = cand.get("candidate", ""),
            ))
        except Exception as e:
            logger.debug(f"ICE candidate: {e}")

    async def stop(self):
        if self._closed:
            return
        self._closed = True
        # Release any held keys before tearing down
        input_executor.release_all_keys()
        if self._track:
            try: self._track.stop()
            except Exception: pass
            self._track = None
        if self._audio:
            try: self._audio.stop()
            except Exception: pass
            self._audio = None
        self._ft_handler = None
        if self._pc:
            try: await self._pc.close()
            except Exception: pass
            self._pc = None
        logger.info(f"Session stopped [{self.session_id[:8]}]")


# ── Registry ──────────────────────────────────────────────────────────────────

class WebRTCRegistry:
    def __init__(self):
        self._sessions: Dict[str, WebRTCSession] = {}

    async def handle_offer_req(self, session_id: str, send_fn: Callable, session_kind: str = "live"):
        if session_id in self._sessions:
            logger.warning(f"Duplicate session: {session_id[:8]}")
            return
        sess = WebRTCSession(session_id, send_fn, session_kind=session_kind)
        self._sessions[session_id] = sess
        await sess.start()

    async def handle_answer(self, session_id: str, sdp: dict, ice_restart: bool = False):
        sess = self._sessions.get(session_id)
        if sess:
            await sess.set_answer(sdp, ice_restart=ice_restart)

    async def handle_ice(self, session_id: str, candidate: dict):
        sess = self._sessions.get(session_id)
        if sess:
            await sess.add_ice_candidate(candidate)

    async def handle_end(self, session_id: str):
        sess = self._sessions.pop(session_id, None)
        if sess:
            await sess.stop()

    async def stop_all(self):
        for sess in list(self._sessions.values()):
            await sess.stop()
        self._sessions.clear()

    def active_count(self) -> int:
        return len(self._sessions)


# ── Input executor ────────────────────────────────────────────────────────────

class InputExecutor:
    """
    Text + command + raw key model input executor.

    Event protocol (matches RemoteAccess.jsx):

      -- Raw keyboard (v2 — preferred) --

      { type:"keydown", code:"KeyA", key:"a", ctrl:false, shift:false, alt:false, meta:false }
      { type:"keyup",   code:"KeyA", key:"a" }
          → Raw keydown/keyup using browser KeyboardEvent.code.
            Supports held keys, arbitrary modifier combos, full keyboard.

      -- Legacy text/command model --

      { type:"text",     text:"hello world" }
          → Types the string on the remote machine via clipboard paste (unicode-safe)
            or pyautogui.write() fallback.

      { type:"command",  action:"enter"|"backspace"|"tab"|"escape"|"delete"|
                                "up"|"down"|"left"|"right"|"home"|"end"|
                                "pageup"|"pagedown"|"insert"|"printscreen"|
                                "capslock"|"numlock"|"f1"…"f12" }
          → Presses a single named special key.

      { type:"shortcut", action:"copy"|"paste"|"cut"|"undo"|"redo"|"selectall"|
                                "save"|"print"|"find"|"closewindow"|"newtab"|
                                "newwindow"|"reload"|"focusbar"|"bookmark"|
                                "alt_<char>" (e.g. "alt_f4" → Alt+F4) }
          → Executes the OS-native shortcut for the named action.
            Platform-aware: uses Cmd on macOS, Ctrl on Windows/Linux.

      { type:"scroll",   dir:"up"|"down"|"left"|"right", amount:int, x:int, y:int }
          → Scrolls amount steps in the given direction at (x,y).

      { type:"mousemove", x:int, y:int }
      { type:"mousedown", button:0|1|2, x:int, y:int }
      { type:"mouseup",   button:0|1|2, x:int, y:int }
      { type:"dblclick",  button:0|1|2, x:int, y:int }
    """

    # ── Named command → pyautogui key ─────────────────────────────────────────
    _COMMAND_KEYS = {
        "enter":       "enter",
        "backspace":   "backspace",
        "delete":      "delete",
        "tab":         "tab",
        "escape":      "escape",
        "up":          "up",
        "down":        "down",
        "left":        "left",
        "right":       "right",
        "home":        "home",
        "end":         "end",
        "pageup":      "pageup",
        "pagedown":    "pagedown",
        "insert":      "insert",
        "printscreen": "printscreen",
        "capslock":    "capslock",
        "numlock":     "numlock",
        "scrolllock":  "scrolllock",
        "pause":       "pause",
        "f1":"f1","f2":"f2","f3":"f3","f4":"f4","f5":"f5","f6":"f6",
        "f7":"f7","f8":"f8","f9":"f9","f10":"f10","f11":"f11","f12":"f12",
    }

    # ── Named shortcut → (modifier, key) or callable ──────────────────────────
    # Platform-aware: _ctrl() returns "ctrl" on Windows/Linux, "command" on macOS
    @staticmethod
    def _ctrl():
        return "command" if platform.system() == "Darwin" else "ctrl"

    _SHORTCUT_MAP = {
        "copy":        lambda c: (c, "c"),
        "paste":       lambda c: (c, "v"),
        "cut":         lambda c: (c, "x"),
        "undo":        lambda c: (c, "z"),
        "redo":        lambda c: (c, "y"),    # Win/Linux; macOS uses cmd+shift+z
        "selectall":   lambda c: (c, "a"),
        "save":        lambda c: (c, "s"),
        "print":       lambda c: (c, "p"),
        "find":        lambda c: (c, "f"),
        "closewindow": lambda c: (c, "w"),
        "newtab":      lambda c: (c, "t"),
        "newwindow":   lambda c: (c, "n"),
        "reload":      lambda c: (c, "r"),
        "focusbar":    lambda c: (c, "l"),
        "bookmark":    lambda c: (c, "d"),
    }

    def __init__(self):
        self._ready = False
        self._pag   = None
        self._clip  = None
        self._held_keys: set = set()   # tracks currently held keys for raw keydown/keyup

        try:
            import pyautogui as _pag
            _pag.FAILSAFE = False
            _pag.PAUSE    = 0
            self._pag   = _pag
            self._ready = True
            logger.info("InputExecutor ready (pyautogui)")
        except Exception as exc:
            logger.warning(f"Remote input disabled: pyautogui unavailable in current session ({exc})")

        try:
            import pyperclip as _clip
            self._clip = _clip
            logger.info("InputExecutor: pyperclip ready")
        except Exception as exc:
            logger.info(f"pyperclip unavailable — clipboard text input disabled ({exc})")

        # Lazy-import key mapping
        try:
            from key_mapping import resolve_key, is_modifier
            self._resolve_key = resolve_key
            self._is_modifier = is_modifier
        except ImportError:
            self._resolve_key = None
            self._is_modifier = None
            logger.warning("key_mapping module not found — raw keyboard input disabled")

    # ── Public entry point ────────────────────────────────────────────────────

    def execute(self, ev: dict):
        if not self._ready:
            return
        t = ev.get("type", "")
        try:
            handler = getattr(self, f"_ev_{t}", None)
            if handler:
                handler(ev)
            else:
                logger.debug(f"InputExecutor: unknown event '{t}'")
        except Exception as e:
            logger.debug(f"InputExecutor({t}): {e}")

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def _ev_mousemove(self, ev):
        self._pag.moveTo(int(ev["x"]), int(ev["y"]), duration=0)

    def _ev_mousedown(self, ev):
        btn = {0:"left",1:"middle",2:"right"}.get(ev.get("button",0),"left")
        self._pag.mouseDown(int(ev["x"]), int(ev["y"]), button=btn)

    def _ev_mouseup(self, ev):
        btn = {0:"left",1:"middle",2:"right"}.get(ev.get("button",0),"left")
        self._pag.mouseUp(int(ev["x"]), int(ev["y"]), button=btn)

    def _ev_dblclick(self, ev):
        btn = {0:"left",1:"middle",2:"right"}.get(ev.get("button",0),"left")
        self._pag.doubleClick(int(ev["x"]), int(ev["y"]), button=btn)

    # ── Scroll — direction + integer steps ────────────────────────────────────

    def _ev_scroll(self, ev):
        """
        { dir: "up"|"down"|"left"|"right", amount: int, x: int, y: int }
        amount = number of scroll steps (1 step = 1 wheel click)
        pyautogui.scroll(): positive = up, negative = down
        """
        x      = int(ev.get("x", 0))
        y      = int(ev.get("y", 0))
        amount = max(1, min(20, int(ev.get("amount", 1))))
        d      = ev.get("dir", "down")

        if d == "up":
            self._pag.scroll(amount, x=x, y=y)
        elif d == "down":
            self._pag.scroll(-amount, x=x, y=y)
        elif d in ("left", "right"):
            try:
                clicks = amount if d == "right" else -amount
                self._pag.hscroll(clicks, x=x, y=y)
            except AttributeError:
                pass   # hscroll not on all versions

    # ── Text — clipboard-paste or character-by-character ─────────────────────

    def _ev_text(self, ev):
        """
        Type a text string on the remote machine.
        Strategy:
          1. pyperclip.copy(text) + Ctrl/Cmd+V  — handles ALL unicode, fastest
          2. pyautogui.write(text)               — ASCII only fallback
        """
        text = ev.get("text", "")
        if not text:
            return

        if self._clip:
            try:
                # Save current clipboard content so we can restore it
                try:    prev = self._clip.paste()
                except: prev = ""

                self._clip.copy(text)
                self._pag.hotkey(self._ctrl(), "v")
                logger.debug(f"text via clipboard: {len(text)} chars")

                # Restore previous clipboard after short delay
                import threading
                def _restore():
                    import time; time.sleep(0.3)
                    try: self._clip.copy(prev)
                    except: pass
                threading.Thread(target=_restore, daemon=True).start()
                return
            except Exception as e:
                logger.debug(f"clipboard paste failed: {e}")

        # Fallback — works for ASCII only
        try:
            self._pag.write(text, interval=0.01)
        except Exception as e:
            logger.debug(f"write fallback failed: {e}")

    # ── Command — single named special key ────────────────────────────────────

    def _ev_command(self, ev):
        """
        { action: "enter" | "backspace" | "tab" | "up" | … }
        Presses and releases a single named special key.
        """
        action = ev.get("action", "").lower()
        key    = self._COMMAND_KEYS.get(action)
        if key:
            self._pag.press(key)
            logger.debug(f"command: {action}")
        else:
            logger.debug(f"command: unknown action '{action}'")

    # ── Shortcut — named OS action ────────────────────────────────────────────

    def _ev_shortcut(self, ev):
        """
        { action: "copy" | "paste" | "undo" | … | "alt_f" | "alt_4" }
        Maps named actions to platform-correct key combos.
        """
        action = ev.get("action", "").lower()
        ctrl   = self._ctrl()

        # alt_<key> → Alt + key
        if action.startswith("alt_"):
            key = action[4:]
            if key:
                self._pag.hotkey("alt", key)
                logger.debug(f"shortcut alt+{key}")
            return

        # Named shortcuts
        fn = self._SHORTCUT_MAP.get(action)
        if fn:
            combo = fn(ctrl)
            self._pag.hotkey(*combo)
            logger.debug(f"shortcut: {action} → {'+'.join(combo)}")
            return

        # macOS redo = Cmd+Shift+Z
        if action == "redo" and platform.system() == "Darwin":
            self._pag.hotkey("command", "shift", "z")
            return

        logger.debug(f"shortcut: unknown action '{action}'")

    # ── Raw keydown / keyup (v2 protocol) ─────────────────────────────────────

    def _ev_keydown(self, ev):
        """
        { code:"KeyA", key:"a", ctrl:false, shift:false, alt:false, meta:false }
        Presses and holds a single key using its browser KeyboardEvent.code.
        """
        if not self._resolve_key:
            return
        code = ev.get("code", "")
        key  = ev.get("key", "")
        pag_key = self._resolve_key(code, key)
        if not pag_key:
            logger.debug(f"keydown: unmapped code={code} key={key}")
            return
        self._held_keys.add(pag_key)
        self._pag.keyDown(pag_key)
        logger.debug(f"keydown: {code} → {pag_key}")

    def _ev_keyup(self, ev):
        """
        { code:"KeyA", key:"a" }
        Releases a held key.
        """
        if not self._resolve_key:
            return
        code = ev.get("code", "")
        key  = ev.get("key", "")
        pag_key = self._resolve_key(code, key)
        if not pag_key:
            logger.debug(f"keyup: unmapped code={code} key={key}")
            return
        self._held_keys.discard(pag_key)
        self._pag.keyUp(pag_key)
        logger.debug(f"keyup: {code} → {pag_key}")

    def release_all_keys(self):
        """Release all currently held keys — call on session stop / disconnect."""
        if not self._pag:
            return
        for k in list(self._held_keys):
            try:
                self._pag.keyUp(k)
            except Exception:
                pass
        self._held_keys.clear()
        logger.debug("Released all held keys")


# ── Module singletons ─────────────────────────────────────────────────────────

registry       = WebRTCRegistry()
input_executor = InputExecutor()
