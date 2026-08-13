"""The runtime pipeline: question in, events out.

`answer()` is a generator of events rather than a function returning a string,
so the UI can render progress as it happens and stays a renderer with no logic
of its own. It also means the whole flow is testable headlessly — a test
consumes exactly what the browser consumes.

Order of work: route → retrieve → rerank → assemble prompt → stream. Exactly one
terminal event is emitted per call, so a caller always knows when it is done.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator

from rag import prompts, rerank, retrieve
from rag.config import ANSWER_MAX_TOKENS, Mode
from rag.errors import KeyStatus, ProviderError
from rag.llm import LLMClient, Message
from rag.retrieve import RetrievalResult
from rag.router import Route, RouteKind, route

logger = logging.getLogger(__name__)


# --- events ----------------------------------------------------------------


@dataclass(frozen=True)
class Citation:
    """A pointer from an answer back to real published material.

    Built only from retrieved-chunk metadata — never from anything the model
    wrote — so a citation cannot exist for a passage that was not used.
    """

    expert: str
    title: str
    url: str
    is_podcast: bool = False
    timestamp_s: int | None = None
    episode_verified: bool = True

    @property
    def display(self) -> str:
        icon = "🎙" if self.is_podcast else "📄"
        if self.is_podcast and not self.episode_verified:
            # Episode identity is unreliable upstream: attribute the expert and
            # the show, and claim nothing more.
            return f"{icon} {self.expert} on Lenny's Podcast"
        if self.is_podcast and self.timestamp_s is not None:
            stamp = f"{self.timestamp_s // 60}:{self.timestamp_s % 60:02d}"
            return f"{icon} {self.expert} — {self.title} ({stamp})"
        return f"{icon} {self.expert} — {self.title}"

    @property
    def link(self) -> str:
        """Deep-link into the recording, but only where the episode is trusted."""
        if self.is_podcast and self.episode_verified and self.timestamp_s is not None:
            joiner = "&" if "?" in self.url else "?"
            return f"{self.url}{joiner}t={self.timestamp_s}"
        return self.url


class EventType(str, Enum):
    KEY_PROBLEM = "key_problem"
    OFF_TOPIC = "off_topic"
    ROUTED = "routed"
    COVERAGE_GAP = "coverage_gap"
    ANSWER_DELTA = "answer_delta"
    SOURCES = "sources"
    FAILURE = "failure"
    DONE = "done"


#: Events after which nothing further is emitted.
TERMINAL = {
    EventType.KEY_PROBLEM,
    EventType.OFF_TOPIC,
    EventType.COVERAGE_GAP,
    EventType.FAILURE,
    EventType.DONE,
}


@dataclass(frozen=True)
class Event:
    type: EventType
    text: str = ""
    citations: tuple[Citation, ...] = ()
    route: Route | None = None
    key_status: KeyStatus | None = None
    meta: dict = field(default_factory=dict)


# --- pipeline ---------------------------------------------------------------


def _citation_for(result: RetrievalResult) -> Citation:
    meta = result.metadata
    is_podcast = meta.get("content_type") == "podcast_transcript"
    return Citation(
        expert=meta.get("expert", "Unknown"),
        title=meta.get("title", "untitled"),
        url=meta.get("youtube_url") or meta.get("url", ""),
        is_podcast=is_podcast,
        timestamp_s=meta.get("timestamp_s") if is_podcast else None,
        episode_verified=bool(meta.get("episode_verified", True)),
    )


def _dedupe_citations(results: list[RetrievalResult]) -> tuple[Citation, ...]:
    """One citation per distinct thing the reader can click, ranked order.

    Deduping on doc_id alone is not enough. Two works can render to the same
    citation — that is exactly what happens with the episodes whose upstream
    metadata collides, since both lose their titles and fall back to naming the
    show. Keying on what the reader actually sees avoids showing them the same
    line twice.
    """
    seen: set[tuple[str, str]] = set()
    citations: list[Citation] = []
    for result in results:
        citation = _citation_for(result)
        key = (citation.display, citation.link)
        if key in seen:
            continue
        seen.add(key)
        citations.append(citation)
    return tuple(citations)


def answer(
    question: str,
    client: LLMClient,
    mode: Mode = Mode.COUNCIL,
    selected_expert: str | None = None,
) -> Iterator[Event]:
    """Answer one question, emitting events as the work progresses."""
    question = (question or "").strip()
    if not question:
        yield Event(EventType.DONE)
        return

    # --- route (the only spend before we know the question is answerable) ---
    decision = route(client, question)
    if decision.kind is RouteKind.OFF_TOPIC:
        yield Event(EventType.OFF_TOPIC, text=prompts.OFF_TOPIC_REPLY)
        return

    # A named expert in the question overrides council mode; an explicit
    # dropdown selection still wins over both.
    expert = selected_expert
    if expert is None and decision.kind is RouteKind.EXPERT_MENTIONED:
        expert = decision.expert
    council = expert is None

    yield Event(EventType.ROUTED, route=decision, meta={"expert": expert, "council": council})

    # --- retrieve and select (local, free) ---
    try:
        candidates = retrieve.search(question, expert=expert)
        ranked = rerank.rerank(question, candidates)
        selected = (
            rerank.select_for_council(ranked) if council else rerank.select_for_expert(ranked)
        )
    except Exception as exc:  # index missing or corrupt
        logger.exception("retrieval failed")
        yield Event(EventType.FAILURE, text=f"Retrieval failed: {type(exc).__name__}")
        return

    if not rerank.has_coverage(selected, council=council):
        yield Event(EventType.COVERAGE_GAP, text=prompts.coverage_gap_reply(expert, council))
        return

    # --- generate ---
    system = (
        prompts.COUNCIL_SYSTEM if council else prompts.EXPERT_SYSTEM.format(expert=expert)
    )
    user_turn = prompts.build_user_turn(
        question, selected, prompts.select_exemplars(question)
    )

    produced_any = False
    try:
        for delta in client.stream(
            system, [Message(role="user", content=user_turn)], max_tokens=ANSWER_MAX_TOKENS
        ):
            produced_any = True
            yield Event(EventType.ANSWER_DELTA, text=delta)
    except ProviderError as exc:
        # Whatever was already streamed stands; it is not retried, because the
        # user has already been billed for those tokens.
        yield Event(
            EventType.FAILURE,
            text=exc.user_message,
            key_status=exc.status,
            meta={"partial": produced_any},
        )
        return

    yield Event(EventType.SOURCES, citations=_dedupe_citations(selected))
    yield Event(EventType.DONE, meta={"chunks_used": len(selected)})
