"""Durable artifact storage for checkpoints and published results.

Layout (relative to ``artifact_dir``; a named Docker volume in development)::

    cache/tiles/blobs/<sha256>.json.gz        immutable, content-addressed NASA tile payloads (shared)
    cache/tiles/index/<request_hash>.json     latest verified blob for one exact NASA request
    jobs/<job_id>/input.json                  accepted request incl. polygon geometry (owner-only)
    jobs/<job_id>/work/...                    stage checkpoints (overlaps, grid, regional, cell chunks)
    jobs/<job_id>/staging-<n>/                results being written (never served)
    jobs/<job_id>/result/                     published results; appears atomically (directory rename)

Every write goes to a temporary file in the same directory, is flushed and
fsync'ed, then renamed over the target (atomic on POSIX and NTFS). Readers
verify SHA-256 checksums recorded in PostgreSQL or in the result manifest, so a
torn or tampered file is detected instead of being served.

Production deployments can replace this class with an object-storage backend
offering the same methods (write-then-commit semantics, checksums).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.utils.errors import EarthScopeError

BACKEND_DIR = Path(__file__).resolve().parents[2]


class ArtifactError(EarthScopeError):
    status_code = 503
    error = "ARTIFACT_STORAGE_ERROR"
    retryable = True


class ArtifactCorruptError(ArtifactError):
    error = "ARTIFACT_CORRUPT"


class StorageFullError(ArtifactError):
    error = "STORAGE_FULL"


def _json_default(o: Any) -> Any:
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(f"Not JSON serialisable: {type(o).__name__}")


def dumps(obj: Any) -> bytes:
    """Deterministic JSON (floats round-trip exactly via repr; NaN kept for internal checkpoints)."""
    return json.dumps(obj, default=_json_default, separators=(",", ":"), sort_keys=False, allow_nan=True).encode("utf-8")


def gz(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=6, mtime=0)   # mtime=0: identical input -> identical bytes / checksum


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_json(obj: Any) -> Any:
    """Replace non-finite floats by None (for files a user downloads)."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: strict_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [strict_json(v) for v in obj]
    if isinstance(obj, np.generic):
        return strict_json(obj.item())
    return obj


class ArtifactStore:
    def __init__(self, root: Path, min_free_mb: int = 0):
        self.root = root
        self.min_free_mb = min_free_mb
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ArtifactError("Invalid artifact path.")
        return p

    def exists(self, rel: str) -> bool:
        return self.path(rel).exists()

    # ----------------------------------------------------------------- writes
    def _check_space(self, need: int) -> None:
        if not self.min_free_mb:
            return
        free = shutil.disk_usage(self.root).free
        if free - need < self.min_free_mb * 1_000_000:
            raise StorageFullError(
                "The result storage is almost full; the analysis was paused before writing incomplete files.",
                [f"Free space {free / 1e6:.0f} MB is below the configured reserve of {self.min_free_mb} MB."],
            )

    def write_bytes(self, rel: str, data: bytes) -> tuple[str, int]:
        """Atomically write ``data``; returns (sha256, size)."""
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._check_space(len(data))
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            if getattr(exc, "errno", None) == 28:   # ENOSPC
                raise StorageFullError("The result storage is full; no incomplete result was published.") from exc
            raise ArtifactError("A result file could not be written to durable storage.") from exc
        return sha256_bytes(data), len(data)

    def write_json_gz(self, rel: str, obj: Any) -> tuple[str, int]:
        return self.write_bytes(rel, gz(dumps(obj)))

    # ------------------------------------------------------------------ reads
    def read_bytes(self, rel: str, sha256: str | None = None) -> bytes:
        try:
            data = self.path(rel).read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactCorruptError("A stored checkpoint or result file is missing.", [rel]) from exc
        except OSError as exc:
            raise ArtifactError("A stored file could not be read.", [rel]) from exc
        if sha256 is not None and sha256_bytes(data) != sha256:
            raise ArtifactCorruptError("A stored file failed its checksum verification.", [rel])
        return data

    def read_json_gz(self, rel: str, sha256: str | None = None) -> Any:
        return json.loads(gzip.decompress(self.read_bytes(rel, sha256)))

    def verify(self, rel: str, sha256: str | None) -> bool:
        if not sha256:
            return False
        try:
            self.read_bytes(rel, sha256)
            return True
        except ArtifactError:
            return False

    # ------------------------------------------------------ shared tile cache
    @staticmethod
    def blob_ref(sha256: str) -> str:
        return f"cache/tiles/blobs/{sha256[:2]}/{sha256}.json.gz"

    def put_tile_blob(self, payload: dict[str, Any]) -> tuple[str, int]:
        data = gz(dumps(payload))
        sha = sha256_bytes(data)
        ref = self.blob_ref(sha)
        if not self.verify(ref, sha):   # immutable: an existing verified blob is never rewritten
            self.write_bytes(ref, data)
        return sha, len(data)

    def get_tile_blob(self, sha256: str) -> dict[str, Any]:
        return self.read_json_gz(self.blob_ref(sha256), sha256)

    def index_tile(self, request_hash: str, entry: dict[str, Any]) -> None:
        self.write_bytes(f"cache/tiles/index/{request_hash}.json", dumps(entry))

    def lookup_tile(self, request_hash: str) -> dict[str, Any] | None:
        p = self.path(f"cache/tiles/index/{request_hash}.json")
        try:
            entry = json.loads(p.read_bytes())
        except (OSError, ValueError):
            return None
        return entry if self.verify(self.blob_ref(entry.get("sha256", "")), entry.get("sha256")) else None

    # ---------------------------------------------------------- directories
    def job_prefix(self, job_id: str) -> str:
        return f"jobs/{job_id}"

    def remove_tree(self, rel: str) -> None:
        p = self.path(rel)
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    def tree_bytes(self, rel: str) -> int:
        p = self.path(rel)
        if not p.exists():
            return 0
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

    def publish_dir(self, staging_rel: str, final_rel: str) -> None:
        """Atomically make ``staging_rel`` visible as ``final_rel`` (single directory rename)."""
        src, dst = self.path(staging_rel), self.path(final_rel)
        if dst.exists():
            raise ArtifactError("A published result already exists for this job.")
        for attempt in range(5):
            try:
                os.replace(src, dst)
                return
            except PermissionError:   # Windows: a virus scanner / indexer may hold a handle briefly
                if attempt == 4:
                    raise
                time.sleep(0.5 * (attempt + 1))

    def gc_tile_blobs(self, older_than_seconds: float, keep: set[str]) -> int:
        """Delete shared tile blobs not modified recently and not referenced by a live job."""
        base = self.path("cache/tiles/blobs")
        if not base.exists():
            return 0
        cutoff = time.time() - older_than_seconds
        removed = 0
        for f in base.rglob("*.json.gz"):
            sha = f.name.split(".")[0]
            try:
                if sha not in keep and f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                continue
        return removed


@lru_cache
def get_store() -> ArtifactStore:
    s = get_settings()
    root = Path(s.artifact_dir) if s.artifact_dir else BACKEND_DIR / "var" / "artifacts"
    if not root.is_absolute():
        root = BACKEND_DIR / root
    return ArtifactStore(root, s.job_min_free_disk_mb)
