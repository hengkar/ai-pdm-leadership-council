"""Runtime retrieval and generation for the AI PDM Leadership Council.

Nothing in this package may import `data_collection` or read `DEV_LLM_API_KEY`:
the corpus is built offline and this package only reads committed index
artifacts (constitution Principle II).
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


def warmup() -> float:
    """Load the local models before the first question arrives.

    Measured cold, the embedder and cross-encoder take about 27 seconds to load
    while warm retrieval takes under a second. Left lazy, that whole cost lands
    on whoever asks first and blows the five-second first-token budget (SC-007).
    Paying it at startup instead moves it off the user's critical path.

    Returns seconds spent, so a caller can log what boot cost.
    """
    from rag import prompts, rerank, retrieve

    started = time.time()
    retrieve._index()
    rerank._cross_encoder()
    prompts._exemplar_vectors()  # shares the retrieval embedder; encodes once
    elapsed = time.time() - started
    logger.info("warmup complete in %.1fs", elapsed)
    return elapsed
