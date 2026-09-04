"""P1.0 — the document store. ADR-0009's promises, asserted.

The three properties that make the provenance rule keepable: the key is the content, the
store never overwrites, and a stored object can be proved intact later.
"""

from __future__ import annotations

import hashlib

import pytest

from packages.common.storage import KEY_PREFIX, LocalDiskBackend, sha256_hex

PDF = b"%PDF-1.7\nnot really a pdf, but bytes are bytes\n"


@pytest.fixture
def store(tmp_path) -> LocalDiskBackend:
    return LocalDiskBackend(tmp_path / "documents")


def test_key_is_the_content_hash(store: LocalDiskBackend) -> None:
    stored = store.put(PDF, media_type="application/pdf")
    assert stored.sha256 == hashlib.sha256(PDF).hexdigest()
    assert stored.storage_key == f"{KEY_PREFIX}/{stored.sha256}.pdf"
    assert stored.newly_written is True


def test_storing_identical_bytes_twice_is_a_no_op(store: LocalDiskBackend) -> None:
    """Re-fetching an unchanged page is normal and must not be an error."""
    first = store.put(PDF, media_type="application/pdf")
    second = store.put(PDF, media_type="application/pdf")
    assert second.sha256 == first.sha256
    assert second.newly_written is False


def test_different_bytes_get_different_keys(store: LocalDiskBackend) -> None:
    a = store.put(b"one", media_type="text/plain")
    b = store.put(b"two", media_type="text/plain")
    assert a.sha256 != b.sha256
    assert store.get(a.sha256) == b"one"
    assert store.get(b.sha256) == b"two"


def test_stored_file_is_read_only(store: LocalDiskBackend, tmp_path) -> None:
    """Write-once as a file mode, not only as a rule (ADR-0009)."""
    stored = store.put(PDF, media_type="application/pdf")
    path = tmp_path / "documents" / "sha256" / f"{stored.sha256}.pdf"
    assert path.exists()
    with pytest.raises(PermissionError):
        path.write_bytes(b"tampered")


def test_the_backend_has_no_delete() -> None:
    """There is no delete path, in this class or any subclass, in any phase.

    Asserted rather than assumed: adding one should require deleting this test, which is a
    decision someone has to make deliberately.
    """
    assert not hasattr(LocalDiskBackend, "delete")
    assert not hasattr(LocalDiskBackend, "remove")


def test_verify_detects_corruption(store: LocalDiskBackend, tmp_path) -> None:
    """The quarterly re-hash check in docs/REVIEW_CADENCE.md, doing its job."""
    stored = store.put(PDF, media_type="application/pdf")
    assert store.verify(stored.sha256) is True

    path = tmp_path / "documents" / "sha256" / f"{stored.sha256}.pdf"
    path.chmod(0o600)  # simulate bit-rot, which does not respect our file modes
    path.write_bytes(b"%PDF-1.7\nsilently corrupted\n")
    assert store.verify(stored.sha256) is False


def test_verify_is_false_for_an_absent_object(store: LocalDiskBackend) -> None:
    assert store.verify(sha256_hex(b"never stored")) is False


def test_get_raises_for_an_absent_object(store: LocalDiskBackend) -> None:
    with pytest.raises(FileNotFoundError):
        store.get(sha256_hex(b"never stored"))
