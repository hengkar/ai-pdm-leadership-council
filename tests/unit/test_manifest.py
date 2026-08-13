"""Fetch manifest: re-running the pipeline must not duplicate or re-download.

Backs US5 acceptance scenario 3 — an unchanged corpus rebuilds to an identical
corpus, which is what makes the collection process auditable.
"""

from __future__ import annotations

from pathlib import Path

from data_collection.fetch import Manifest, content_hash


def test_content_hash_is_stable_and_content_sensitive() -> None:
    assert content_hash("same text") == content_hash("same text")
    assert content_hash("same text") != content_hash("same text.")


def test_unchanged_content_is_skipped_on_the_second_run(tmp_path: Path) -> None:
    manifest = Manifest(tmp_path / "manifest.json")
    url = "https://example.com/a-post"
    body = "an article body"

    assert manifest.should_fetch(url, content_hash(body)) is True
    manifest.record(url, content_hash(body), local_path="raw/a-post.html")

    # Second run, nothing changed upstream.
    assert manifest.should_fetch(url, content_hash(body)) is False


def test_changed_content_is_refetched(tmp_path: Path) -> None:
    manifest = Manifest(tmp_path / "manifest.json")
    url = "https://example.com/a-post"
    manifest.record(url, content_hash("v1"), local_path="raw/a-post.html")

    assert manifest.should_fetch(url, content_hash("v2")) is True


def test_force_overrides_the_skip(tmp_path: Path) -> None:
    manifest = Manifest(tmp_path / "manifest.json", force=True)
    url = "https://example.com/a-post"
    digest = content_hash("unchanged")
    manifest.record(url, digest, local_path="raw/a-post.html")

    assert manifest.should_fetch(url, digest) is True


def test_manifest_round_trips_through_disk(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    first = Manifest(path)
    first.record("https://example.com/x", content_hash("body"), local_path="raw/x.html")
    first.save()

    reloaded = Manifest(path)
    assert reloaded.should_fetch("https://example.com/x", content_hash("body")) is False
    assert len(reloaded.entries) == 1


def test_recording_the_same_url_twice_updates_rather_than_appends(tmp_path: Path) -> None:
    manifest = Manifest(tmp_path / "manifest.json")
    url = "https://example.com/x"

    manifest.record(url, content_hash("v1"), local_path="raw/x.html")
    manifest.record(url, content_hash("v2"), local_path="raw/x.html")

    assert len(manifest.entries) == 1, "one entry per URL — no duplicate works"
    assert manifest.entries[url].content_hash == content_hash("v2")
