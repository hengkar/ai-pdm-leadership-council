"""Citations must be constructible only from retrieved material.

A fabricated citation is worse than none: it carries the authority of a source
without the substance. So the rule is mechanical — a citation is built from a
retrieved chunk's metadata, never from anything the model wrote.
"""

from __future__ import annotations

import pytest

from rag.pipeline import Citation, _citation_for, _dedupe_citations
from rag.retrieve import RetrievalResult


def _result(**overrides) -> RetrievalResult:
    meta = {
        "expert": "Shreyas Doshi",
        "title": "An Episode",
        "url": "https://www.youtube.com/watch?v=abc123",
        "youtube_url": "https://www.youtube.com/watch?v=abc123",
        "content_type": "podcast_transcript",
        "timestamp_s": 872,
        "episode_verified": True,
        "doc_id": "shreyas-doshi--ep",
    }
    meta.update(overrides)
    return RetrievalResult(chunk_id="c1", text="passage", metadata=meta)


def test_podcast_citation_deep_links_to_the_moment() -> None:
    citation = _citation_for(_result())
    assert citation.link.endswith("&t=872")
    assert "(14:32)" in citation.display


def test_timestamp_is_rendered_as_minutes_and_seconds() -> None:
    assert "(0:07)" in _citation_for(_result(timestamp_s=7)).display
    assert "(1:05)" in _citation_for(_result(timestamp_s=65)).display
    assert "(60:00)" in _citation_for(_result(timestamp_s=3600)).display


def test_unverified_episodes_lose_the_title_and_the_deep_link() -> None:
    """The decision behind episode_verified: claim only what we can stand behind."""
    citation = _citation_for(_result(episode_verified=False))

    assert "t=" not in citation.link
    assert "An Episode" not in citation.display
    assert "Shreyas Doshi" in citation.display
    assert "Lenny's Podcast" in citation.display


def test_article_citations_carry_title_and_plain_link() -> None:
    citation = _citation_for(
        _result(
            content_type="blog",
            title="A Post",
            url="https://example.com/a-post",
            youtube_url=None,
            timestamp_s=None,
            expert="Casey Winters",
        )
    )
    assert citation.display == "📄 Casey Winters — A Post"
    assert citation.link == "https://example.com/a-post"


def test_icons_distinguish_the_two_source_kinds() -> None:
    assert _citation_for(_result()).display.startswith("🎙")
    assert _citation_for(
        _result(content_type="blog", youtube_url=None, timestamp_s=None)
    ).display.startswith("📄")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://youtu.be/abc", "https://youtu.be/abc?t=30"),
        ("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc&t=30"),
    ],
)
def test_deep_link_joins_correctly_whatever_the_url_shape(url: str, expected: str) -> None:
    citation = Citation(
        expert="X", title="T", url=url, is_podcast=True, timestamp_s=30
    )
    assert citation.link == expected


def test_one_citation_per_source_work() -> None:
    """Several passages from one article should cite it once, not five times."""
    results = [
        _result(doc_id="doc-a"),
        _result(doc_id="doc-a"),
        _result(doc_id="doc-b", expert="Julie Zhuo"),
    ]
    citations = _dedupe_citations(results)

    assert len(citations) == 2
    assert [c.expert for c in citations] == ["Shreyas Doshi", "Julie Zhuo"]


def test_dedupe_preserves_ranking_order() -> None:
    results = [
        _result(doc_id="doc-b", expert="Julie Zhuo"),
        _result(doc_id="doc-a", expert="Shreyas Doshi"),
    ]
    assert [c.expert for c in _dedupe_citations(results)] == ["Julie Zhuo", "Shreyas Doshi"]


def test_no_retrieved_passages_means_no_citations() -> None:
    assert _dedupe_citations([]) == ()


def test_every_citation_resolves_somewhere() -> None:
    for result in (_result(), _result(episode_verified=False),
                   _result(content_type="blog", youtube_url=None, timestamp_s=None)):
        citation = _citation_for(result)
        assert citation.link.startswith("http"), "a citation must point at something real"
        assert citation.expert, "a citation must name who said it"
