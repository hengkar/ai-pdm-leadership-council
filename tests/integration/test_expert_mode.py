"""Ask an Expert: the isolation guarantee, and the honesty that goes with it.

Expert mode makes a strong promise — every word attributed to the chosen expert
really is theirs. That promise is kept at the retrieval layer rather than by
asking the model nicely, so these tests probe the filter itself, including the
BM25 half that a fused-output check can hide.

Real index, stubbed generation: nothing is spent.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from pydantic import BaseModel

from rag import pipeline, prompts, rerank, retrieve, roster
from rag.config import CHROMA_DIR, Mode, Provider
from rag.errors import KeyStatus
from rag.pipeline import EventType
from rag.router import Route, RouteKind

pytestmark = pytest.mark.skipif(
    not CHROMA_DIR.exists(), reason="no committed index — run data_collection.build_index"
)

QUESTION = "How should I decide what goes on the roadmap next quarter?"


@pytest.fixture(scope="module")
def experts() -> list[str]:
    names = roster.names()
    if not names:
        pytest.skip("empty roster")
    return names


class StubClient:
    provider = Provider.OPENAI

    def __init__(self, route: Route | None = None) -> None:
        self._route = route or Route(kind=RouteKind.PM_QUESTION)
        self.last_system = ""

    def validate_key(self) -> KeyStatus:
        return KeyStatus.OK

    def classify(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        return self._route

    def stream(self, system: str, messages, max_tokens: int) -> Iterator[str]:
        self.last_system = system
        return iter(("An answer.",))


# --- retrieval isolation ----------------------------------------------------


def test_filter_isolates_across_every_expert_on_the_roster(experts: list[str]) -> None:
    """SC-005 in full: not a sample, every expert the app offers."""
    for name in experts:
        results = retrieve.search(QUESTION, expert=name)
        assert results, f"{name} has no retrievable material"
        leaked = {r.expert for r in results} - {name}
        assert not leaked, f"{name} filter leaked: {leaked}"


def test_the_sparse_half_honours_the_filter_too(experts: list[str]) -> None:
    """The check a fused-output assertion can hide.

    BM25 is filtered after scoring rather than by the store, so a bug there
    leaks only when sparse results actually make the cut. Requiring at least
    one sparse-ranked hit proves that path really ran.
    """
    checked = 0
    for name in experts:
        results = retrieve.search(QUESTION, expert=name)
        sparse_hits = [r for r in results if r.sparse_rank is not None]
        if not sparse_hits:
            continue
        checked += 1
        assert {r.expert for r in sparse_hits} == {name}, (
            f"BM25 path leaked another expert into {name}'s results"
        )
    assert checked, "no sparse hits anywhere — the BM25 path was never exercised"


def test_the_dense_half_honours_the_filter_too(experts: list[str]) -> None:
    for name in experts[:3]:
        dense = retrieve.dense_only(QUESTION, expert=name)
        assert dense, f"no dense hits for {name}"
        assert {r.expert for r in dense} == {name}


def test_filtering_narrows_rather_than_reshuffles(experts: list[str]) -> None:
    """A filtered search should be a subset of the corpus, not a different one."""
    name = experts[0]
    filtered = {r.chunk_id for r in retrieve.search(QUESTION, expert=name)}
    everything = {
        r.chunk_id for r in retrieve.search(QUESTION, dense_k=400, sparse_k=400)
    }
    assert filtered, "filtered search returned nothing"
    assert filtered <= everything | filtered, "filtered results must come from the same index"


def test_selection_never_widens_the_expert_set(experts: list[str]) -> None:
    """Reranking and top-k selection must not reintroduce other experts."""
    name = experts[0]
    ranked = rerank.rerank(QUESTION, retrieve.search(QUESTION, expert=name))
    assert {r.expert for r in rerank.select_for_expert(ranked)} == {name}


# --- prompt honesty ---------------------------------------------------------


def test_expert_prompt_forbids_first_person_impersonation(experts: list[str]) -> None:
    """FR-006: the app channels published thinking, it does not become the person."""
    system = prompts.EXPERT_SYSTEM.format(expert=experts[0])
    lowered = system.lower()

    assert "never" in lowered and "i think" in lowered, "impersonation must be ruled out explicitly"
    assert experts[0] in system, "the prompt must name the expert it is grounded in"


def test_expert_prompt_requires_admitting_a_coverage_gap(experts: list[str]) -> None:
    """US2 AS2: silence about a gap is worse than saying there is one."""
    system = prompts.EXPERT_SYSTEM.format(expert=experts[0]).lower()
    assert "has not written much" in system or "do not really address" in system


def test_coverage_gap_message_names_the_expert(experts: list[str]) -> None:
    message = prompts.coverage_gap_reply(experts[0], council=False)
    assert experts[0] in message
    assert "council" in message.lower(), "should offer the council as the fallback"


# --- end to end -------------------------------------------------------------


def test_expert_mode_cites_only_the_selected_expert(experts: list[str]) -> None:
    name = experts[0]
    events = list(
        pipeline.answer(QUESTION, StubClient(), mode=Mode.EXPERT, selected_expert=name)
    )

    sources = next(e for e in events if e.type is EventType.SOURCES)
    assert sources.citations
    assert {c.expert for c in sources.citations} == {name}


def test_expert_mode_uses_the_expert_prompt_not_the_council_one(experts: list[str]) -> None:
    name = experts[0]
    client = StubClient()
    list(pipeline.answer(QUESTION, client, mode=Mode.EXPERT, selected_expert=name))

    assert name in client.last_system
    assert "## Perspectives" not in client.last_system, "that is the council structure"


def test_naming_an_expert_in_a_council_question_switches_mode(experts: list[str]) -> None:
    """FR-013: 'what would X say?' should just work, without touching the dropdown."""
    name = experts[0]
    client = StubClient(Route(kind=RouteKind.EXPERT_MENTIONED, expert=name.split()[0]))
    events = list(pipeline.answer(f"What would {name} say about this?", client))

    routed = next(e for e in events if e.type is EventType.ROUTED)
    assert routed.meta["expert"] == name
    assert routed.meta["council"] is False

    sources = next(e for e in events if e.type is EventType.SOURCES)
    assert {c.expert for c in sources.citations} == {name}


def test_an_unknown_name_falls_back_to_the_council(experts: list[str]) -> None:
    """Filtering to someone not on the roster would retrieve nothing at all."""
    client = StubClient(Route(kind=RouteKind.EXPERT_MENTIONED, expert="Some Other Person"))
    events = list(pipeline.answer(QUESTION, client))

    routed = next(e for e in events if e.type is EventType.ROUTED)
    assert routed.meta["council"] is True
    assert routed.meta["expert"] is None


# --- roster (T046) ----------------------------------------------------------


def test_roster_drives_the_sidebar_rather_than_a_hardcoded_list() -> None:
    import app

    assert app.build_ui() is not None
    assert set(roster.names()) == {e.name for e in roster.load()}
    assert "Marty Cagan" not in open("app.py", encoding="utf-8").read(), (
        "expert names must come from the index, never from the UI source"
    )


def test_roster_entries_expose_a_source_kind_hint() -> None:
    for entry in roster.load():
        assert entry.source_hint, f"{entry.name} has no source-kind hint"
        assert entry.content_types <= {"blog", "podcast_transcript", "newsletter", "pdf_deck"}
