"""Retrieval against the real committed index.

These run on the actual corpus rather than fixtures, because the properties
worth checking — that the expert filter really isolates, that fusion beats
either half alone, that the council cap produces multiple voices — only mean
something against real data. No API key and no network: embedding and reranking
are local.

Skipped cleanly on a fresh clone where the index has not been built yet.
"""

from __future__ import annotations

import pytest

from rag import rerank, retrieve, roster
from rag.config import CHROMA_DIR

pytestmark = pytest.mark.skipif(
    not CHROMA_DIR.exists(), reason="no committed index — run data_collection.build_index"
)

# The situation the product spec opens with.
ROADMAP_QUESTION = "My engineering team keeps pushing back on my roadmap. What should I do?"


def test_roster_is_built_from_the_index() -> None:
    entries = roster.load()
    assert entries, "roster should not be empty"
    assert all(entry.chunk_count > 0 for entry in entries), "no phantom experts"
    assert len(entries) == len({entry.name for entry in entries}), "no duplicate experts"


def test_roster_resolves_partial_names() -> None:
    names = roster.names()
    if "Shreyas Doshi" not in names:
        pytest.skip("Shreyas Doshi not in this corpus")
    assert roster.resolve("Shreyas") == "Shreyas Doshi"
    assert roster.resolve("shreyas doshi") == "Shreyas Doshi"
    assert roster.resolve("Nobody At All") is None


def test_hybrid_search_returns_scored_candidates() -> None:
    results = retrieve.search(ROADMAP_QUESTION)

    assert results, "a central PM question should match the corpus"
    assert all(r.rrf_score > 0 for r in results)
    assert results == sorted(results, key=lambda r: r.rrf_score, reverse=True)
    assert all(r.text for r in results), "every candidate carries its text"


def test_hybrid_search_surfaces_candidates_dense_search_alone_misses() -> None:
    """If fusion never changed the pool, BM25 would be dead weight."""
    hybrid = {r.chunk_id for r in retrieve.search(ROADMAP_QUESTION)}
    dense = {r.chunk_id for r in retrieve.dense_only(ROADMAP_QUESTION)}

    assert hybrid - dense, "sparse retrieval contributed nothing to the fused pool"


def test_every_candidate_carries_what_a_citation_needs() -> None:
    for result in retrieve.search(ROADMAP_QUESTION)[:10]:
        meta = result.metadata
        assert meta.get("expert"), "attribution is mandatory"
        assert meta.get("url"), "a citation must resolve to something"
        assert meta.get("title")
        assert "episode_verified" in meta


def test_expert_filter_isolates_completely() -> None:
    """The guarantee behind Ask an Expert (FR-003, SC-005)."""
    for name in roster.names()[:3]:
        results = retrieve.search(ROADMAP_QUESTION, expert=name)
        assert results, f"no material found for {name}"
        assert {r.expert for r in results} == {name}


def test_content_type_filter_isolates() -> None:
    results = retrieve.search(ROADMAP_QUESTION, content_type="blog")
    if not results:
        pytest.skip("no blog chunks in this corpus")
    assert {r.metadata["content_type"] for r in results} == {"blog"}


def test_reranking_reorders_the_candidate_pool() -> None:
    candidates = retrieve.search(ROADMAP_QUESTION)
    ranked = rerank.rerank(ROADMAP_QUESTION, candidates)

    assert ranked
    assert all(r.rerank_score is not None for r in ranked)
    assert ranked == sorted(ranked, key=lambda r: r.rerank_score, reverse=True)
    assert [r.chunk_id for r in ranked] != [r.chunk_id for r in candidates[: len(ranked)]], (
        "reranking that never changes the order is not doing anything"
    )


def test_council_selection_returns_several_voices() -> None:
    ranked = rerank.rerank(ROADMAP_QUESTION, retrieve.search(ROADMAP_QUESTION))
    selected = rerank.select_for_council(ranked)

    assert selected
    assert len({r.expert for r in selected}) >= 2, "a council needs more than one voice"
    assert rerank.has_coverage(selected, council=True)


def test_council_cap_stops_one_expert_dominating() -> None:
    from rag.config import MAX_CHUNKS_PER_EXPERT

    ranked = rerank.rerank(ROADMAP_QUESTION, retrieve.search(ROADMAP_QUESTION))
    selected = rerank.select_for_council(ranked)

    counts: dict[str, int] = {}
    for result in selected:
        counts[result.expert] = counts.get(result.expert, 0) + 1
    assert max(counts.values()) <= MAX_CHUNKS_PER_EXPERT


def test_expert_selection_stays_within_one_expert() -> None:
    name = roster.names()[0]
    ranked = rerank.rerank(ROADMAP_QUESTION, retrieve.search(ROADMAP_QUESTION, expert=name))
    selected = rerank.select_for_expert(ranked)

    assert selected
    assert {r.expert for r in selected} == {name}
    assert rerank.has_coverage(selected, council=False)


def test_no_coverage_is_reported_rather_than_papered_over() -> None:
    assert rerank.has_coverage([], council=False) is False
    assert rerank.has_coverage([], council=True) is False


def test_single_voice_does_not_satisfy_council_coverage() -> None:
    name = roster.names()[0]
    ranked = rerank.rerank(ROADMAP_QUESTION, retrieve.search(ROADMAP_QUESTION, expert=name))
    selected = rerank.select_for_expert(ranked)

    assert rerank.has_coverage(selected, council=True) is False, (
        "one expert's passages must not be presented as a council"
    )
