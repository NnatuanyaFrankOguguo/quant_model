"""Content-addressed, write-once storage for source documents. P1.0, per ADR-0009.

The provenance rule (`CLAUDE.md`) says every original document must be retrievable
**forever** — including after the source website has been redesigned or has vanished, which
`TEAM_BRIEF.md` Part 3 names as a live risk for exactly the Nigerian sources that are the
moat. This module is the thing that makes that promise keepable.

Three properties, and each one is load-bearing rather than tidy:

**Keyed by content hash, never by name.** `documents/sha256/<64-hex>` is flat and
deduplicating, and the key itself is a proof: if the bytes changed, the key would be a
different key. A name-keyed store cannot tell you whether `cbn_mpr_2026.pdf` is the file you
parsed last year.

**Write once.** There is no `delete`, in this class or any subclass, in any phase. A reissued
report is a *new object*, exactly as a corrected figure is a new row (`CLAUDE.md`: no silent
overwrites). Stored files are made read-only, so the rule survives a stray `open(path, "wb")`
as well as good intentions — the same argument `docs/08` §2.16 makes for enforcing the
no-update rule with a database trigger rather than in review.

**Bytes here, metadata in `source_documents`.** `source_documents.sha256` is the join, and
`macro_observations.source_document_id` is `NOT NULL`, so the schema itself refuses to record
a figure whose raw source was never stored. That is what turns "fetch and parse are separate"
from a convention into something the database enforces.
"""

from __future__ import annotations

import hashlib
import stat
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from packages.common.config import get_settings

__all__ = [
    "KEY_PREFIX",
    "LocalDiskBackend",
    "StorageBackend",
    "StoredObject",
    "get_storage",
    "sha256_hex",
]

#: Exactly as `docs/02` §4 specifies, and unchanged when the backend becomes a bucket: the
#: key is portable between backends precisely because it is derived from the content.
KEY_PREFIX = "documents/sha256"

#: Extension by media type. Cosmetic — the key is the hash — but it makes the store
#: browsable by a human at 2am, which is when someone will be looking at it.
_SUFFIXES = {
    "application/pdf": ".pdf",
    "application/json": ".json",
    "text/csv": ".csv",
    "text/html": ".html",
    "text/plain": ".txt",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


def sha256_hex(data: bytes) -> str:
    """The content address. 64 lowercase hex characters, matching `CHAR(64)`."""
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class StoredObject:
    """What the caller needs to write a `source_documents` row."""

    sha256: str
    storage_key: str
    media_type: str
    size_bytes: int
    #: False when the object was already present. Storing the same bytes twice is a
    #: successful no-op, not an error — re-fetching an unchanged page is normal.
    newly_written: bool


class StorageBackend(ABC):
    """The interface. The provider is a swap; this contract is the decision (ADR-0009).

    Deliberately has no `delete`. Adding one later would be a decision to make, and making
    it require an ADR is the point.
    """

    @abstractmethod
    def put(self, data: bytes, *, media_type: str) -> StoredObject:
        """Store bytes under their content address. Idempotent; never overwrites."""

    @abstractmethod
    def get(self, sha256: str) -> bytes:
        """Return the stored bytes. Raises `FileNotFoundError` when absent."""

    @abstractmethod
    def exists(self, sha256: str) -> bool: ...

    def key_for(self, sha256: str, media_type: str) -> str:
        """The storage key for a hash. Identical across backends, by construction."""
        return f"{KEY_PREFIX}/{sha256}{_SUFFIXES.get(media_type, '')}"

    def verify(self, sha256: str) -> bool:
        """Re-hash the stored object and compare it to its address.

        The quarterly check in `docs/REVIEW_CADENCE.md`: storage that is never read back is
        storage nobody knows is intact. Silent bit-rot in a PDF whose source URL has since
        rotated is unrecoverable, and it is invisible until someone re-parses.
        """
        try:
            return sha256_hex(self.get(sha256)) == sha256
        except FileNotFoundError:
            return False


class LocalDiskBackend(StorageBackend):
    """The P1 backend. A remote bucket replaces it at P3 entry, same interface."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _path(self, sha256: str, media_type: str = "") -> Path:
        return self.root / "sha256" / f"{sha256}{_SUFFIXES.get(media_type, '')}"

    def _find(self, sha256: str) -> Path | None:
        """Locate an object by hash regardless of the suffix it was stored with."""
        directory = self.root / "sha256"
        if not directory.is_dir():
            return None
        for candidate in directory.glob(f"{sha256}*"):
            if candidate.is_file():
                return candidate
        return None

    def put(self, data: bytes, *, media_type: str) -> StoredObject:
        digest = sha256_hex(data)
        existing = self._find(digest)
        if existing is not None:
            # Already stored. By construction the bytes are identical — the name IS the
            # hash — so this is a no-op rather than a conflict.
            return StoredObject(
                sha256=digest,
                storage_key=self.key_for(digest, media_type),
                media_type=media_type,
                size_bytes=len(data),
                newly_written=False,
            )
        path = self._path(digest, media_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary name and rename, so a crash mid-write cannot leave a
        # truncated file sitting at a content address that promises it is complete.
        tmp = path.with_suffix(path.suffix + ".partial")
        tmp.write_bytes(data)
        tmp.replace(path)
        _make_read_only(path)
        return StoredObject(
            sha256=digest,
            storage_key=self.key_for(digest, media_type),
            media_type=media_type,
            size_bytes=len(data),
            newly_written=True,
        )

    def get(self, sha256: str) -> bytes:
        path = self._find(sha256)
        if path is None:
            raise FileNotFoundError(f"no stored object for sha256 {sha256}")
        return path.read_bytes()

    def exists(self, sha256: str) -> bool:
        return self._find(sha256) is not None


def _make_read_only(path: Path) -> None:
    """Drop the write bits. Write-once as a file mode, not only as a rule.

    Best effort on purpose: this is defence in depth behind the content-addressed key, and a
    filesystem that will not do it (a network share, a container mount) must not stop an
    ingestion run.
    """
    try:
        mode = path.stat().st_mode
        path.chmod(mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
    except OSError:  # pragma: no cover - platform dependent
        pass


@lru_cache(maxsize=1)
def get_storage() -> StorageBackend:
    """The process-wide document store."""
    root = Path(get_settings().documents_dir)
    if not root.is_absolute():
        root = _repo_root() / root
    return LocalDiskBackend(root)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
