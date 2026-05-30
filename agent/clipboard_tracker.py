"""
CropSentinel - Clipboard Activity Tracker
Monitors clipboard text changes and forwards them to the agent DLP handler.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger("croppro.clipboard")


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


class ClipboardTracker:
    def __init__(self, on_text_fn, interval: float = 1.5, min_chars: int = 8):
        self._on_text = on_text_fn
        self.interval = max(0.5, float(interval))
        self.min_chars = max(1, int(min_chars))
        self.running = True
        self._last_digest = ""

    def run(self):
        try:
            import pyperclip  # type: ignore
        except Exception as exc:
            logger.info("Clipboard tracker unavailable: %s", exc)
            return

        logger.info("Clipboard tracker started")
        while self.running:
            try:
                text = pyperclip.paste()
                if isinstance(text, str):
                    normalized = text.strip()
                    if len(normalized) >= self.min_chars:
                        digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()
                        if digest != self._last_digest:
                            self._last_digest = digest
                            self._on_text(
                                {
                                    "timestamp": _utcnow_iso(),
                                    "text": normalized,
                                    "content_fingerprint": digest,
                                }
                            )
            except Exception as exc:
                logger.debug("Clipboard tracker poll error: %s", exc)
            time.sleep(self.interval)

    def stop(self):
        self.running = False
