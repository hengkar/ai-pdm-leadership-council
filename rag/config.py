"""Paths, model identifiers and retrieval constants for the runtime pipeline.

One module so the cost story, the retrieval knobs and the index locations are
all reviewable in a single place.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

# --- Paths -----------------------------------------------------------------
# Resolved from this file so the app behaves the same locally and on the Space,
# whatever the working directory is.

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CURATED_DIR = DATA_DIR / "curated"          # committed, offline stage only
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"     # committed
INDEX_DIR = DATA_DIR / "index"              # committed — the Space boots from this
CHROMA_DIR = INDEX_DIR / "chroma"
BM25_PATH = INDEX_DIR / "bm25.pkl"

CHROMA_COLLECTION = "council"


# --- Local models ----------------------------------------------------------
# Both run on the Space's CPU and cost the user nothing, which is what keeps
# retrieval free at query time (constitution Principle II).

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
RERANKER_MODEL = "BAAI/bge-reranker-base"


# --- Providers -------------------------------------------------------------


class Mode(str, Enum):
    """Which product mode a question is asked in.

    Defined here rather than imported from `data_collection.schemas`: the
    runtime package must not depend on the offline pipeline (Principle II).
    The two definitions are intentionally identical in value.
    """

    COUNCIL = "council"
    EXPERT = "expert"


class Provider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"
    CLAUDE = "claude"


# Cost-efficient tier, pinned per provider. This is not a default we could
# freely raise: the assignment caps a full trial at US$0.50 (SC-002), and at
# roughly 4k input + 700 output tokens per answer, a frontier-tier model would
# put ~15 questions over that ceiling on its own. The ceiling picks the tier,
# so users get a provider choice rather than a model picker.
PROVIDER_MODELS: dict[Provider, str] = {
    Provider.OPENAI: "gpt-4o-mini",
    Provider.GEMINI: "gemini-2.0-flash",
    Provider.CLAUDE: "claude-haiku-4-5",
}

PROVIDER_LABELS: dict[Provider, str] = {
    Provider.OPENAI: "OpenAI",
    Provider.GEMINI: "Google Gemini",
    Provider.CLAUDE: "Anthropic Claude",
}

# Where each provider's keys are issued, shown next to the key field.
PROVIDER_KEY_URLS: dict[Provider, str] = {
    Provider.OPENAI: "https://platform.openai.com/api-keys",
    Provider.GEMINI: "https://aistudio.google.com/apikey",
    Provider.CLAUDE: "https://console.anthropic.com/settings/keys",
}

# Claude Haiku 4.5 predates the `effort` parameter and rejects it, and it takes
# the older `thinking: {type: "enabled", budget_tokens: N}` form rather than
# adaptive thinking. The adapter sends neither: this pipeline wants a fast,
# cheap, single-pass answer over retrieved context, not model-side reasoning.
CLAUDE_SUPPORTS_EFFORT = False

# Anthropic only caches prefixes of at least this many tokens on Haiku 4.5
# (higher than the newer models). The cache-friendly prompt layout is a stretch
# goal, so treat a miss as expected rather than a bug unless the static prefix
# clears this bar.
CLAUDE_MIN_CACHEABLE_TOKENS = 4096


# --- Generation bounds -----------------------------------------------------
# Ceilings, not targets. They exist so a runaway generation cannot quietly blow
# through the user's budget.

ROUTER_MAX_TOKENS = 300      # a typed enum plus an optional expert name
ANSWER_MAX_TOKENS = 900      # situation + 2-3 perspectives + numbered actions
KEY_VALIDATION_MAX_TOKENS = 1


# --- Retrieval -------------------------------------------------------------

DENSE_TOP_K = 30             # candidates from Chroma
SPARSE_TOP_K = 30            # candidates from BM25
RRF_K = 60                   # reciprocal-rank-fusion constant, standard default
RERANK_CANDIDATES = 20       # fused pool handed to the cross-encoder

FINAL_TOP_K_EXPERT = 5
FINAL_TOP_K_COUNCIL = 6
MIN_EXPERTS_IN_COUNCIL = 2   # below this the answer isn't a council answer
MAX_CHUNKS_PER_EXPERT = 3    # stops one long transcript dominating the context

# Reranker scores below this mean the corpus does not really cover the question.
# The honest-gap reply is better than an answer built from weak matches (FR-005).
RERANK_SCORE_FLOOR = 0.0

# Chunking (mirrored by data_collection/chunk.py; kept here because retrieval
# quality depends on matching what was indexed).
TARGET_CHUNK_TOKENS = 450
CHUNK_OVERLAP_TOKENS = 60
