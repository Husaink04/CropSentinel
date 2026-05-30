"""Hybrid-ready object storage abstraction for evidence and large blobs."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("cropsentinel.object_storage")


def _writable_dir_candidates(requested: Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    if requested is not None:
        candidates.append(requested)
    home = Path.home()
    candidates.extend(
        [
            home / ".cropsentinel" / "evidence",
            Path("/tmp/cropsentinel/evidence"),
        ]
    )
    seen: list[Path] = []
    for path in candidates:
        resolved = path.expanduser().resolve()
        if resolved not in seen:
            seen.append(resolved)
    return seen


def _resolve_writable_root(requested: Path | None = None) -> Path:
    last_error: Exception | None = None
    for candidate in _writable_dir_candidates(requested):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-test"
            probe.write_bytes(b"ok")
            probe.unlink(missing_ok=True)
            if requested is not None and candidate != requested:
                logger.warning("Evidence storage fallback activated: requested=%s fallback=%s", requested, candidate)
            return candidate
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"No writable evidence storage directory is available: {last_error}") from last_error


def _storage_root() -> Path:
    raw = os.environ.get("EVIDENCE_STORAGE_DIR", "").strip()
    if raw:
        return _resolve_writable_root(Path(raw))
    return _resolve_writable_root((Path(__file__).resolve().parents[1] / "storage" / "evidence"))


def _storage_backend() -> str:
    return (os.environ.get("OBJECT_STORAGE_BACKEND", "filesystem").strip().lower() or "filesystem")


@dataclass(slots=True)
class StoredObject:
    storage_key: str
    sha256: str
    size_bytes: int
    backend: str


class FilesystemObjectStorage:
    backend_name = "filesystem"

    def __init__(self, root: Path | None = None) -> None:
        self.root = _resolve_writable_root(root or _storage_root())

    def _path_for_key(self, storage_key: str) -> Path:
        safe_key = storage_key.replace("\\", "/").lstrip("/")
        return self.root / safe_key

    def store_bytes(self, *, raw_bytes: bytes, storage_key: str) -> StoredObject:
        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        target = self._path_for_key(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(raw_bytes)
        return StoredObject(
            storage_key=storage_key,
            sha256=sha256,
            size_bytes=len(raw_bytes),
            backend=self.backend_name,
        )

    def load_bytes(self, storage_key: str) -> bytes:
        return self._path_for_key(storage_key).read_bytes()

    def delete(self, storage_key: str) -> None:
        path = self._path_for_key(storage_key)
        if path.exists():
            path.unlink()
        parent = path.parent
        for _ in range(4):
            try:
                if parent == self.root or any(parent.iterdir()):
                    break
                parent.rmdir()
                parent = parent.parent
            except Exception:
                break


class S3CompatibleObjectStorage:
    backend_name = "s3-compatible"

    def __init__(self) -> None:
        self.bucket = os.environ.get("OBJECT_STORAGE_BUCKET", "cropsentinel-evidence").strip()
        endpoint = os.environ.get("OBJECT_STORAGE_ENDPOINT", "").strip()
        region = os.environ.get("OBJECT_STORAGE_REGION", "us-east-1").strip()
        access_key = os.environ.get("OBJECT_STORAGE_ACCESS_KEY", "").strip()
        secret_key = os.environ.get("OBJECT_STORAGE_SECRET_KEY", "").strip()
        if not endpoint:
            raise RuntimeError("OBJECT_STORAGE_ENDPOINT is required for s3 backend")
        import boto3  # noqa: PLC0415

        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
        )

    def store_bytes(self, *, raw_bytes: bytes, storage_key: str) -> StoredObject:
        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        self.client.put_object(Bucket=self.bucket, Key=storage_key, Body=raw_bytes)
        return StoredObject(
            storage_key=storage_key,
            sha256=sha256,
            size_bytes=len(raw_bytes),
            backend=self.backend_name,
        )

    def load_bytes(self, storage_key: str) -> bytes:
        obj = self.client.get_object(Bucket=self.bucket, Key=storage_key)
        return obj["Body"].read()

    def delete(self, storage_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=storage_key)


class Base64EvidenceStorage:
    def __init__(self) -> None:
        backend = _storage_backend()
        self.root = _storage_root()
        if backend == "s3":
            self._store = S3CompatibleObjectStorage()
        else:
            self._store = FilesystemObjectStorage(root=self.root)

    def store_bytes(
        self,
        *,
        raw_bytes: bytes,
        tenant_id: int,
        category: str,
        machine_id: str = "",
        filename_hint: str = "",
    ) -> StoredObject:
        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        ext = Path(filename_hint).suffix[:16] if filename_hint else ""
        normalized_machine = machine_id or "shared"
        storage_key = (
            f"tenant_{tenant_id}/{category}/{normalized_machine}/"
            f"{sha256[:2]}/{sha256}-{secrets.token_hex(4)}{ext}"
        )
        return self._store.store_bytes(raw_bytes=raw_bytes, storage_key=storage_key)

    def store_base64(
        self,
        *,
        base64_data: str,
        tenant_id: int,
        machine_id: str,
        category: str,
        filename_hint: str = "",
    ) -> StoredObject:
        raw_bytes = base64.b64decode((base64_data or "").encode("ascii"), validate=False)
        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        ext = Path(filename_hint).suffix[:16] if filename_hint else ""
        storage_key = (
            f"tenant_{tenant_id}/{category}/{machine_id}/"
            f"{sha256[:2]}/{sha256}-{secrets.token_hex(4)}{ext}"
        )
        return self._store.store_bytes(raw_bytes=raw_bytes, storage_key=storage_key)

    def load_base64(self, storage_key: str) -> str:
        return base64.b64encode(self._store.load_bytes(storage_key)).decode("ascii")

    def delete(self, storage_key: str) -> None:
        self._store.delete(storage_key)

    def load_bytes(self, storage_key: str) -> bytes:
        return self._store.load_bytes(storage_key)


object_storage = Base64EvidenceStorage()
evidence_storage = Base64EvidenceStorage()
