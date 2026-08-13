"""Cross-encoder reranking and council-mode selection.

Retrieval optimises for recall — cast a wide net, accept some noise. Reranking
optimises for precision: a cross-encoder reads the question and each candidate
together, which catches passages that merely share vocabulary with the question
but do not answer it.

Two selection rules live here as well:

* a per-expert cap in council mode, so one long transcript cannot fill the
  context and turn a council into a monologue; and
* a score floor, so a question the corpus does not cover produces an honest
  "we haven't written about this" rather than an answer assembled from the
  least-bad matches (FR-005).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from rag.config import (
    FINAL_TOP_K_COUNCIL,
    FINAL_TOP_K_EXPERT,
    MAX_CHUNKS_PER_EXPERT,
    MIN_EXPERTS_IN_COUNCIL,
    RERANK_CANDIDATES,
    RERANK_SCORE_FLOOR,
    RERANKER_MODEL,
)
from rag.retrieve import RetrievalResult

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _cross_encoder():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(RERANKER_MODEL)


def rerank(query: str, candidates: list[RetrievalResult]) -> list[RetrievalResult]:
    """Score candidates against the query and return them best-first."""
    if not candidates:
        return []

    pool = candidates[:RERANK_CANDIDATES]
    scores = _cross_encoder().predict([(query, result.text) for result in pool])
    for result, score in zip(pool, scores):
        result.rerank_score = float(score)

    return sorted(pool, key=lambda r: r.rerank_score or 0.0, reverse=True)


def select_for_expert(ranked: list[RetrievalResult], k: int = FINAL_TOP_K_EXPERT):
    """Top passages for single-expert mode, above the relevance floor."""
    return [r for r in ranked if (r.rerank_score or 0.0) >= RERANK_SCORE_FLOOR][:k]


def select_for_council(
    ranked: list[RetrievalResult],
    k: int = FINAL_TOP_K_COUNCIL,
    per_expert: int = MAX_CHUNKS_PER_EXPERT,
) -> list[RetrievalResult]:
    """Pick passages spanning several experts.

    Straight top-k tends to return one expert repeatedly, because whoever wrote
    most about a topic occupies most of the leaderboard. Capping each expert
    buys the contrast the product exists to provide, at some cost in raw
    relevance — a deliberate trade.
    """
    above_floor = [r for r in ranked if (r.rerank_score or 0.0) >= RERANK_SCORE_FLOOR]

    chosen: list[RetrievalResult] = []
    used: dict[str, int] = {}
    for result in above_floor:
        if used.get(result.expert, 0) >= per_expert:
            continue
        chosen.append(result)
        used[result.expert] = used.get(result.expert, 0) + 1
        if len(chosen) >= k:
            break

    # If the cap left us short (a narrow topic only one expert covers), refill
    # from what is left rather than returning a thin answer.
    if len(chosen) < k:
        taken = {r.chunk_id for r in chosen}
        chosen.extend(r for r in above_floor if r.chunk_id not in taken)
        chosen = chosen[:k]

    return chosen


def has_coverage(selected: list[RetrievalResult], council: bool) -> bool:
    """Whether the selection is worth answering from.

    Council mode additionally needs more than one voice — a single-expert
    answer presented as a council would misrepresent what it is.
    """
    if not selected:
        return False
    if council and len({r.expert for r in selected}) < MIN_EXPERTS_IN_COUNCIL:
        logger.info("council coverage gap: only %d expert(s) matched", len({r.expert for r in selected}))
        return False
    return True
