"""Frozen snapshots: a saved response is reused, never silently refreshed."""

import pytest

from bla.ingest.snapshot import SnapshotMismatch, cached_batches, describe


def test_saved_batches_are_reused_without_fetching(tmp_path):
    calls = []

    def fetch(batch):
        calls.append(batch)
        return b"<xml/>"

    first = cached_batches("batch", [["1", "2"]], tmp_path, fetch, log=lambda _: None)
    again = cached_batches("batch", [["1", "2"]], tmp_path, fetch, log=lambda _: None)
    assert calls == [["1", "2"]]
    assert first[0][1] == again[0][1] == b"<xml/>"


def test_a_different_request_for_a_saved_batch_is_refused(tmp_path):
    cached_batches("batch", [["1"]], tmp_path, lambda b: b"<x/>", log=lambda _: None)
    with pytest.raises(SnapshotMismatch):
        cached_batches("batch", [["2"]], tmp_path, lambda b: b"<x/>", log=lambda _: None)


def test_a_modified_saved_response_is_refused(tmp_path):
    cached_batches("batch", [["1"]], tmp_path, lambda b: b"<x/>", log=lambda _: None)
    (tmp_path / "batch-0001.xml").write_bytes(b"<changed/>")
    with pytest.raises(SnapshotMismatch):
        cached_batches("batch", [["1"]], tmp_path, lambda b: b"<x/>", log=lambda _: None)


def test_describe_handles_single_values():
    assert describe([5]) == {"min": 5, "p50": 5, "p95": 5, "max": 5}
    assert describe([]) is None
