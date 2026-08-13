"""Chunking invariants.

A chunk is the unit that gets retrieved and quoted, so the rules that matter
are about provenance: a chunk must belong to exactly one work, and a podcast
chunk must know the moment it came from.
"""

from __future__ import annotations

import pytest

from data_collection.chunk import chunk_work
from data_collection.schemas import ContentType, Segment, SourceWork


# SourceWork enforces a 300-word floor, so fixtures are padded to be valid
# works. The padding is filler; each test's meaning lives in the segments.
def _filler(n: int) -> str:
    return " ".join(f"word{i}" for i in range(n))


def _article(body_words: int = 1200, segments: list[Segment] | None = None) -> SourceWork:
    body = _filler(max(body_words, 300))
    return SourceWork(
        id="casey-winters--a-post",
        expert="Casey Winters",
        title="A Post",
        url="https://example.com/a-post",
        content_type=ContentType.BLOG,
        word_count=len(body.split()),
        body=body,
        segments=segments if segments is not None else [Segment(text=body, heading_path="A Post")],
    )


def _episode(units: list[tuple[str, int]]) -> SourceWork:
    """Build a valid episode whose segments are exactly `units`.

    `body` is padded independently of the segments so a test can use two short,
    clearly-distinguishable exchanges without tripping the word-count floor.
    """
    body = "\n\n".join(text for text, _ in units)
    padded = f"{body} {_filler(300)}"
    return SourceWork(
        id="shreyas-doshi--ep",
        expert="Shreyas Doshi",
        title="An Episode",
        url="https://www.youtube.com/watch?v=abc123",
        content_type=ContentType.PODCAST_TRANSCRIPT,
        word_count=len(padded.split()),
        body=padded,
        video_id="abc123",
        youtube_url="https://www.youtube.com/watch?v=abc123",
        segments=[Segment(text=text, timestamp_s=ts) for text, ts in units],
    )


def test_every_chunk_belongs_to_its_parent_work() -> None:
    work = _article()
    chunks = chunk_work(work)

    assert chunks
    assert all(c.doc_id == work.id for c in chunks)
    assert all(c.expert == work.expert for c in chunks)
    assert all(c.url == work.url for c in chunks)


def test_chunk_ids_are_unique_and_ordered() -> None:
    chunks = chunk_work(_article())
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids, key=lambda i: int(i.rsplit("#", 1)[1]))


def test_long_article_is_split_into_several_chunks() -> None:
    chunks = chunk_work(_article(body_words=1500))
    assert len(chunks) > 1, "a 1500-word post should not be one chunk"


def test_short_work_stays_a_single_chunk() -> None:
    chunks = chunk_work(_article(body_words=320))
    assert len(chunks) == 1


def test_article_chunks_carry_the_heading_path_and_no_timestamp() -> None:
    chunks = chunk_work(
        _article(segments=[Segment(text=" ".join(["w"] * 400), heading_path="A Post > Part One")])
    )
    assert all(c.heading_path == "A Post > Part One" for c in chunks)
    assert all(c.timestamp_s is None for c in chunks)


def test_podcast_chunks_always_carry_a_timestamp_and_link() -> None:
    work = _episode([("First exchange.", 12), ("Second exchange.", 340)])
    chunks = chunk_work(work)

    assert chunks
    assert all(c.timestamp_s is not None for c in chunks)
    assert all(str(c.youtube_url) == str(work.youtube_url) for c in chunks)


def test_transcript_chunks_never_merge_two_exchanges() -> None:
    """Merging exchanges would attach one moment's timestamp to another's words."""
    work = _episode([("Answer about pricing.", 10), ("Answer about hiring.", 900)])
    chunks = chunk_work(work)

    assert len(chunks) == 2
    assert {c.timestamp_s for c in chunks} == {10, 900}
    for chunk in chunks:
        assert not ("pricing" in chunk.text and "hiring" in chunk.text)


def test_a_long_single_exchange_splits_but_keeps_its_timestamp() -> None:
    long_answer = " ".join(f"word{i}" for i in range(900))
    chunks = chunk_work(_episode([(long_answer, 55)]))

    assert len(chunks) > 1
    assert all(c.timestamp_s == 55 for c in chunks), (
        "split pieces of one answer all start at that answer's moment"
    )


def test_episode_verification_flag_propagates_to_chunks() -> None:
    work = _episode([("An exchange.", 30)]).model_copy(update={"episode_verified": False})
    assert all(c.episode_verified is False for c in chunk_work(work))


def test_topics_propagate_so_metadata_filtering_works_at_chunk_level() -> None:
    work = _article().model_copy(update={"topics": ["growth", "retention"]})
    assert all(c.topics == ["growth", "retention"] for c in chunk_work(work))


@pytest.mark.parametrize("words", [1, 5, 50])
def test_tiny_segments_do_not_produce_empty_chunks(words: int) -> None:
    """A short section still yields one usable chunk, never an empty one."""
    tiny = Segment(text=_filler(words), heading_path="A Post > Aside")
    chunks = chunk_work(_article(segments=[tiny]))
    assert chunks and all(c.text.strip() for c in chunks)
