"""The pipeline's event contract.

`app.py` is a renderer with no logic of its own, so these guarantees are what
the UI is allowed to assume. They run against the real index with a fake LLM
client: retrieval is genuine, generation is stubbed, nothing is spent.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from pydantic import BaseModel

from rag import pipeline, roster
from rag.config import CHROMA_DIR, Mode, Provider
from rag.errors import KeyStatus, ProviderError
from rag.pipeline import TERMINAL, EventType
from rag.router import Route, RouteKind

pytestmark = pytest.mark.skipif(
    not CHROMA_DIR.exists(), reason="no committed index — run data_collection.build_index"
)

QUESTION = "My engineering team keeps pushing back on my roadmap. What should I do?"


class FakeClient:
    """Stands in for a provider: no key, no network, scripted behaviour."""

    provider = Provider.OPENAI

    def __init__(
        self,
        route_kind: RouteKind = RouteKind.PM_QUESTION,
        expert: str | None = None,
        deltas: tuple[str, ...] = ("Answer ", "text."),
        fail_stream: bool = False,
        fail_classify: bool = False,
    ) -> None:
        self._route = Route(kind=route_kind, expert=expert)
        self._deltas = deltas
        self._fail_stream = fail_stream
        self._fail_classify = fail_classify
        self.stream_calls = 0

    def validate_key(self) -> KeyStatus:
        return KeyStatus.OK

    def classify(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        if self._fail_classify:
            raise ProviderError(KeyStatus.PROVIDER_ERROR, "classifier unavailable")
        return self._route

    def stream(self, system: str, messages, max_tokens: int) -> Iterator[str]:
        self.stream_calls += 1
        self.last_system = system
        self.last_user = messages[0].content
        if self._fail_stream:
            raise ProviderError(KeyStatus.QUOTA_EXCEEDED, "out of quota")
        return iter(self._deltas)


def _run(client: FakeClient, question: str = QUESTION, **kwargs) -> list:
    return list(pipeline.answer(question, client, **kwargs))


def test_exactly_one_terminal_event_and_it_comes_last() -> None:
    events = _run(FakeClient())
    terminal = [e for e in events if e.type in TERMINAL]

    assert len(terminal) == 1, f"expected one terminal event, got {[e.type for e in terminal]}"
    assert events[-1].type in TERMINAL


def test_a_normal_question_streams_then_cites_then_finishes() -> None:
    events = _run(FakeClient())
    order = [e.type for e in events]

    assert EventType.ROUTED in order
    assert EventType.ANSWER_DELTA in order
    assert order.index(EventType.SOURCES) > order.index(EventType.ANSWER_DELTA)
    assert order[-1] is EventType.DONE


def test_off_topic_short_circuits_before_any_generation() -> None:
    """The cheap path that keeps a stray question under a cent (SC-008)."""
    client = FakeClient(route_kind=RouteKind.OFF_TOPIC)
    events = _run(client, "What is a good lasagna recipe?")

    assert [e.type for e in events] == [EventType.OFF_TOPIC]
    assert client.stream_calls == 0, "off-topic must not reach the generator"


def test_an_expert_named_in_the_question_filters_retrieval() -> None:
    names = roster.names()
    if "Marty Cagan" not in names:
        pytest.skip("Marty Cagan not in this corpus")

    client = FakeClient(route_kind=RouteKind.EXPERT_MENTIONED, expert="Marty Cagan")
    events = _run(client, "What would Marty Cagan say about feature teams?")

    routed = next(e for e in events if e.type is EventType.ROUTED)
    assert routed.meta["expert"] == "Marty Cagan"
    assert routed.meta["council"] is False

    sources = next(e for e in events if e.type is EventType.SOURCES)
    assert {c.expert for c in sources.citations} == {"Marty Cagan"}


def test_explicit_selection_wins_over_the_router() -> None:
    name = roster.names()[0]
    client = FakeClient(route_kind=RouteKind.PM_QUESTION)
    events = _run(client, QUESTION, mode=Mode.EXPERT, selected_expert=name)

    sources = next(e for e in events if e.type is EventType.SOURCES)
    assert {c.expert for c in sources.citations} == {name}


def test_council_answers_cite_more_than_one_expert() -> None:
    events = _run(FakeClient())
    sources = next(e for e in events if e.type is EventType.SOURCES)

    assert len({c.expert for c in sources.citations}) >= 2


def test_citations_come_only_from_retrieved_material() -> None:
    """A citation the model invented would be indistinguishable from a real one."""
    events = _run(FakeClient(deltas=("I read this in a book that was never retrieved.",)))
    sources = next(e for e in events if e.type is EventType.SOURCES)

    assert sources.citations
    for citation in sources.citations:
        assert citation.expert in roster.names()
        assert citation.url


def test_unverified_episodes_are_cited_without_a_deep_link() -> None:
    events = _run(FakeClient())
    sources = next(e for e in events if e.type is EventType.SOURCES)

    for citation in sources.citations:
        if citation.is_podcast and not citation.episode_verified:
            assert "t=" not in citation.link
            assert citation.title not in citation.display


def test_a_failure_mid_stream_is_terminal_and_not_retried() -> None:
    client = FakeClient(fail_stream=True)
    events = _run(client)

    failure = next(e for e in events if e.type is EventType.FAILURE)
    assert failure.key_status is KeyStatus.QUOTA_EXCEEDED
    assert failure.text, "a failure must carry a user-facing message"
    assert client.stream_calls == 1
    assert events[-1].type is EventType.FAILURE


def test_a_router_outage_degrades_to_answering_rather_than_refusing() -> None:
    """Losing the classifier must not take the product down."""
    events = _run(FakeClient(fail_classify=True))
    assert events[-1].type is EventType.DONE


def test_no_event_payload_carries_key_material() -> None:
    for event in _run(FakeClient()):
        blob = f"{event.text} {event.meta} {event.citations}"
        assert "sk-" not in blob


def test_an_empty_question_finishes_without_spending() -> None:
    client = FakeClient()
    events = _run(client, "   ")

    assert [e.type for e in events] == [EventType.DONE]
    assert client.stream_calls == 0


def test_the_prompt_carries_excerpts_and_forbids_impersonation() -> None:
    client = FakeClient()
    _run(client)

    assert "##" in client.last_system, "the answer structure must be specified"
    assert "impersonat" in client.last_system.lower() or "never write as though" in client.last_system.lower()
    assert "[1]" in client.last_user, "excerpts must be numbered for attribution"
