"""P1.0 — the document store. ADR-0009's promises, asserted.

The three properties that make the provenance rule keepable: the key is the content, the
store never overwrites, and a stored object can be proved intact later.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from packages.common.storage import (
    KEY_PREFIX,
    LocalDiskBackend,
    StoredObject,
    sha256_hex,
)

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


# --------------------------------------------------------------------------------------
# Two runs storing the same bytes at once (the 2026-09-16 03:15 stampede)
# --------------------------------------------------------------------------------------


def test_two_threads_storing_the_same_bytes_do_not_fight_over_the_temp_file(
    tmp_path: Path,
) -> None:
    """Every EDGAR job fetches the shared ticker file, so this happens for real.

    On Windows two writers of one shared `.partial` name failed with "the process cannot
    access the file because it is being used by another process", and the job died. Losing
    the race is not a failure: the name IS the hash, so the winner wrote these exact bytes.
    """
    import threading

    store = LocalDiskBackend(tmp_path / "documents")
    data = b'{"0":{"cik_str":320193,"ticker":"AAPL"}}' * 500
    writers = 8
    barrier = threading.Barrier(writers)
    results: list[StoredObject] = []
    errors: list[BaseException] = []

    def put_it() -> None:
        try:
            barrier.wait(timeout=10)
            results.append(store.put(data, media_type="application/json"))
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever escaped
            errors.append(exc)

    threads = [threading.Thread(target=put_it) for _ in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, f"a writer raised: {errors[0]!r}"
    assert len(results) == writers
    assert len({r.sha256 for r in results}) == 1, "one content address"
    # Not "exactly one wrote it": two writers of identical bytes can both complete a
    # replace, and that is harmless - the name is the hash, so neither can write anything
    # the other did not. `newly_written` is a report, not a lock, and locking a
    # content-addressed store against its own content would buy nothing.
    assert any(r.newly_written for r in results), "somebody wrote it"
    assert store.get(results[0].sha256) == data, "the stored bytes are whole"
    leftovers = list((tmp_path / "documents" / "sha256").glob("*.partial"))
    assert leftovers == [], f"temp files left behind: {leftovers}"
