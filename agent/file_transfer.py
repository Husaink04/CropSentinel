"""
CropSentinel Agent — File Transfer Handler
======================================
Bidirectional file transfer over WebRTC DataChannel.

Protocol:
  Control messages (JSON string):
    { type:"file_offer",    id, name, size }          — sender offers a file
    { type:"file_accept",   id }                      — receiver accepts
    { type:"file_reject",   id }                      — receiver rejects
    { type:"file_complete", id, sha256 }              — sender finished all chunks
    { type:"file_ack",      id }                      — receiver verified + saved

  Binary frames (ArrayBuffer):
    bytes[0:36]  = transfer ID (ASCII UUID)
    bytes[36:]   = file chunk data (up to 64 KB)

Incoming files are saved to ~/CropSentinel_Downloads/ (created automatically).
"""

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Dict

logger = logging.getLogger("croppro.filetransfer")

CHUNK_SIZE   = 65536   # 64 KB
DOWNLOAD_DIR = Path.home() / "CropSentinel_Downloads"


def _sanitize_filename(name: str) -> str:
    """Remove path traversal and dangerous characters from a filename."""
    # Strip directory components
    name = Path(name).name
    # Remove any remaining path separators or null bytes
    name = re.sub(r'[/\\:\x00]', '_', name)
    # Collapse multiple dots at the start (e.g. "..hidden")
    name = re.sub(r'^\.+', '', name) or 'unnamed'
    # Limit length
    if len(name) > 255:
        stem, ext = os.path.splitext(name)
        name = stem[:255 - len(ext)] + ext
    return name


class _IncomingTransfer:
    """Tracks state for a file being received from the admin."""
    __slots__ = ('id', 'name', 'size', 'tmp_path', 'tmp_file', 'received', 'hasher')

    def __init__(self, transfer_id: str, name: str, size: int):
        self.id       = transfer_id
        self.name     = _sanitize_filename(name)
        self.size     = size
        self.received = 0
        self.hasher   = hashlib.sha256()
        # Write chunks to a temp file to handle large files without eating RAM
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        fd, self.tmp_path = tempfile.mkstemp(dir=DOWNLOAD_DIR, prefix='.ft_')
        self.tmp_file = os.fdopen(fd, 'wb')

    def write_chunk(self, data: bytes):
        self.tmp_file.write(data)
        self.hasher.update(data)
        self.received += len(data)

    def finalize(self, expected_sha256: str) -> tuple[bool, str]:
        """Close temp file, verify hash, move to final path. Returns (ok, final_path)."""
        self.tmp_file.close()
        actual = self.hasher.hexdigest()
        if expected_sha256 and actual != expected_sha256:
            logger.warning(f"SHA-256 mismatch for {self.name}: expected={expected_sha256[:16]}… got={actual[:16]}…")
            try: os.unlink(self.tmp_path)
            except OSError: pass
            return False, ""

        # Move to final location (add suffix if exists)
        final = DOWNLOAD_DIR / self.name
        counter = 1
        while final.exists():
            stem, ext = os.path.splitext(self.name)
            final = DOWNLOAD_DIR / f"{stem}_{counter}{ext}"
            counter += 1
        os.rename(self.tmp_path, str(final))
        logger.info(f"File saved: {final} ({self.received} bytes)")
        return True, str(final)

    def cancel(self):
        try: self.tmp_file.close()
        except Exception: pass
        try: os.unlink(self.tmp_path)
        except OSError: pass


class _OutgoingTransfer:
    """Tracks state for a file being sent to the admin."""
    __slots__ = ('id', 'path', 'size')

    def __init__(self, transfer_id: str, path: str, size: int):
        self.id   = transfer_id
        self.path = path
        self.size = size


class FileTransferHandler:
    """Handles file transfer over a single DataChannel."""

    def __init__(self, dc):
        self._dc = dc
        self._incoming: Dict[str, _IncomingTransfer] = {}
        self._outgoing: Dict[str, _OutgoingTransfer] = {}
        self._lock = threading.Lock()

    def _send_json(self, obj: dict):
        try:
            self._dc.send(json.dumps(obj))
        except Exception as e:
            logger.debug(f"FT send_json: {e}")

    def on_message(self, data):
        """Called by DataChannel on_message — handles both JSON and binary."""
        if isinstance(data, (bytes, bytearray, memoryview)):
            self._handle_binary(bytes(data))
        elif isinstance(data, str):
            self._handle_json(data)
        else:
            # ArrayBuffer from JS comes as bytes
            try:
                self._handle_binary(bytes(data))
            except Exception:
                pass

    def _handle_binary(self, raw: bytes):
        """Process a binary chunk frame: [36-byte ID][chunk data]."""
        if len(raw) < 37:
            return
        transfer_id = raw[:36].decode('ascii', errors='replace')
        chunk_data  = raw[36:]
        with self._lock:
            rx = self._incoming.get(transfer_id)
        if not rx:
            logger.debug(f"FT chunk for unknown transfer {transfer_id[:8]}")
            return
        rx.write_chunk(chunk_data)

    def _handle_json(self, text: str):
        """Process a JSON control message."""
        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type", "")

        if msg_type == "file_offer":
            # Admin wants to send a file to us
            tid  = msg.get("id", "")
            name = msg.get("name", "file")
            size = msg.get("size", 0)
            if not tid:
                return
            # Auto-accept (agent always accepts incoming files)
            rx = _IncomingTransfer(tid, name, size)
            with self._lock:
                self._incoming[tid] = rx
            self._send_json({"type": "file_accept", "id": tid})
            logger.info(f"Accepting incoming file: {rx.name} ({size} bytes)")

        elif msg_type == "file_complete":
            # Admin finished sending all chunks
            tid    = msg.get("id", "")
            sha256 = msg.get("sha256", "")
            with self._lock:
                rx = self._incoming.pop(tid, None)
            if not rx:
                return
            ok, path = rx.finalize(sha256)
            if ok:
                self._send_json({"type": "file_ack", "id": tid})
            else:
                self._send_json({"type": "file_reject", "id": tid})

        elif msg_type == "file_accept":
            # Admin accepted our outgoing file — start sending chunks
            tid = msg.get("id", "")
            with self._lock:
                tx  = self._outgoing.get(tid)
            if tx:
                threading.Thread(target=self._send_file_chunks, args=(tx,), daemon=True).start()

        elif msg_type == "file_reject":
            tid = msg.get("id", "")
            with self._lock:
                self._outgoing.pop(tid, None)
            logger.info(f"File offer rejected: {tid[:8]}")

        elif msg_type == "file_ack":
            tid = msg.get("id", "")
            with self._lock:
                self._outgoing.pop(tid, None)
            logger.info(f"File transfer acknowledged: {tid[:8]}")

    def send_file(self, file_path: str) -> str | None:
        """Initiate sending a file from agent to admin. Returns transfer ID."""
        path = Path(file_path)
        if not path.is_file():
            logger.warning(f"File not found: {file_path}")
            return None

        import uuid
        tid = str(uuid.uuid4())
        size = path.stat().st_size
        with self._lock:
            self._outgoing[tid] = _OutgoingTransfer(tid, str(path), size)
        self._send_json({"type": "file_offer", "id": tid, "name": path.name, "size": size})
        logger.info(f"Offering file: {path.name} ({size} bytes) id={tid[:8]}")
        return tid

    def _send_file_chunks(self, tx: _OutgoingTransfer):
        """Background thread: read file in chunks and send over DataChannel."""
        hasher = hashlib.sha256()
        try:
            with open(tx.path, 'rb') as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    # Build frame: 36-byte ASCII ID + chunk
                    id_bytes = tx.id.encode('ascii')
                    frame = id_bytes + chunk
                    try:
                        self._dc.send(frame)
                    except Exception as e:
                        logger.error(f"FT send chunk error: {e}")
                        return
                    # Simple backpressure: small sleep between chunks
                    import time
                    time.sleep(0.001)

            # All chunks sent — send completion with hash
            self._send_json({
                "type": "file_complete",
                "id": tx.id,
                "sha256": hasher.hexdigest(),
            })
            logger.info(f"File sent: {tx.path} ({tx.size} bytes)")
        except Exception as e:
            logger.error(f"FT send_file_chunks: {e}")
