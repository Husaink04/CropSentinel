"""
CropSentinel — USB Device Tracker
Monitors USB device insert/remove events on Windows using WMI.
Falls back gracefully on non-Windows platforms.
"""
import time
import string
import logging
import platform
from datetime import datetime, timezone

logger = logging.getLogger("croppro.usb")

OS = platform.system()


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def _get_removable_drives():
    """Return set of drive letters that are removable (USB sticks, etc.)."""
    drives = set()
    if OS != "Windows":
        return drives
    try:
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if bitmask & (1 << i):
                drive = f"{letter}:\\"
                dtype = ctypes.windll.kernel32.GetDriveTypeW(drive)
                if dtype == 2:  # DRIVE_REMOVABLE
                    drives.add(letter)
    except Exception:
        pass
    return drives


class USBTracker:
    """Polls for USB drive changes by comparing removable drive letters."""

    def __init__(self, machine_id: str, enqueue_fn, interval: int = 5):
        self.machine_id = machine_id
        self.enqueue = enqueue_fn
        self.interval = interval
        self.running = True
        self.known_drives = set()

    def run(self):
        if OS != "Windows":
            logger.info("USB tracking only supported on Windows — skipping")
            return

        logger.info("USB tracker started")
        self.known_drives = _get_removable_drives()

        while self.running:
            try:
                self._check()
            except Exception as e:
                logger.debug(f"USB check error: {e}")
            time.sleep(self.interval)

    def _check(self):
        current = _get_removable_drives()

        # New drives inserted
        for drive in current - self.known_drives:
            device_name = self._get_volume_label(drive)
            data = {
                "machine_id": self.machine_id,
                "timestamp": _utcnow_iso(),
                "action": "insert",
                "device_name": device_name,
                "device_id": "",
                "drive_letter": drive,
            }
            self.enqueue("usb", data)
            logger.info(f"USB inserted: {drive}: ({device_name})")

        # Drives removed
        for drive in self.known_drives - current:
            data = {
                "machine_id": self.machine_id,
                "timestamp": _utcnow_iso(),
                "action": "remove",
                "device_name": "",
                "device_id": "",
                "drive_letter": drive,
            }
            self.enqueue("usb", data)
            logger.info(f"USB removed: {drive}:")

        self.known_drives = current

    def _get_volume_label(self, drive_letter: str) -> str:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(256)
            ctypes.windll.kernel32.GetVolumeInformationW(
                f"{drive_letter}:\\", buf, 256, None, None, None, None, 0
            )
            return buf.value or f"USB Drive ({drive_letter}:)"
        except Exception:
            return f"USB Drive ({drive_letter}:)"

    def stop(self):
        self.running = False
