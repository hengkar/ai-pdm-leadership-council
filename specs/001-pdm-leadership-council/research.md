# Phase 0 Research: AI PDM Leadership Council

No `NEEDS CLARIFICATION` markers existed in the Technical Context — the PLAN_*.md design
documents (produced and iterated earlier in this project) already resolved every technology
choice. This document consolidates those decisions in research format so the plan is
self-contained. Source verification noted where it happened.

## R1. UI framework & hosting

- **Decision**: Gradio 5.x Blocks app on a public Hugging Face Space (Gradio SDK, free CPU).
- **Rationale**: Assignment's suggested path; native token-streaming chat; free hosting;
  Space = deployment requirement (FR-016). Blocks (not ChatInterface alone) because the UI
  needs provider dropdown, key field, mode selector, and expert roster beside the chat.
- **Alternatives considered**: Streamlit (weaker streaming-chat ergonomics on Spaces);
  custom frontend in a Docker Space (more control, unjustified effort for MVP).

## R2. Embedding model

- **Decision**: `BAAI/bge-small-en-v1.5` via sentence-transformers, run locally both at index
  time and query time.
- **Rationale**: Strong MTEB retrieval quality per parameter; small enough for free-tier
  Space CPU; local = zero user cost (Constitution I/II) and identical query/index encoders.
- **Alternatives considered**: OpenAI `text-embedding-3-small` (would spend user/dev key at
  query time and couple retrieval to one provider); `all-MiniLM-L6-v2` (cheaper but weaker
  retrieval quality); `bge-base` (better but slower on CPU — revisit only if eval demands).

## R3. Vector store & sparse index

- **Decision**: ChromaDB persistent store + `rank_bm25` (BM25Okapi) pickle, both committed to
  the repo; Reciprocal Rank Fusion (k=60) to fuse dense and sparse candidate lists.
- **Rationale**: Chroma embeds cleanly in a Space (no server), supports metadata `where`
  filters (expert mode); BM25 adds exact-term recall for PM jargon; RRF needs no score
  calibration. Committed artifacts satisfy zero-cost cold boot (Constitution II).
- **Alternatives considered**: FAISS (fast but no metadata filtering built in); LanceDB
  (fine, less familiar); Qdrant/Weaviate (server processes — overkill); fusion by weighted
  score sum (needs calibration; RRF is standard and robust).

## R4. Reranker

- **Decision**: `BAAI/bge-reranker-base` cross-encoder, local, reranking fused top-20 → top-5
  (expert mode) or top-6 with a ≥2-expert diversity floor and per-expert cap (council mode);
  score threshold below which the app reports a coverage gap instead of answering.
- **Rationale**: Ticks the assignment's reranker functionality at zero user cost; measurable
  in the eval ablation (FR-018); the threshold operationalizes honest-gap behavior (FR-005,
  edge cases).
- **Alternatives considered**: Cohere Rerank API (quality, but violates free-runtime
  principle); no reranker (weaker precision@k; loses an assignment functionality).

## R5. LLM providers & models

- **Decision**: One `LLMClient` protocol with three adapters — OpenAI (`gpt-4o-mini`), Google
  (`gemini-2.0-flash`), Anthropic (`claude-haiku`) — cheap tier hardcoded per provider; user
  pastes key, validated with a minimal ping on first use.
- **Rationale**: FR-007 mandates exactly these three providers; pinning cheap models keeps
  the $0.50 story trivially true (≈$0.001–0.003/query) and removes a confusing model picker.
- **Alternatives considered**: User-selectable models (cost variance breaks SC-002 guarantees);
  LiteLLM/LangChain abstraction layers (heavy dependency for three thin adapters).

## R6. Query routing & function calling

- **Decision**: A single small classification call per question using each provider's
  structured-output / tool-calling mode, returning a typed enum
  {`pm_question`, `off_topic`, `expert_mentioned(expert)`}.
- **Rationale**: Implements FR-012/FR-013; typed output (no prose parsing) doubles as the
  assignment's function-calling functionality; ~250 tokens keeps off-topic cost <$0.01 (SC-008).
- **Alternatives considered**: Local zero-shot classifier (free but weaker on nuance, and
  expert-name extraction still needs the LLM); keyword heuristics (brittle).

## R7. Corpus sources

- **Decision**: Two independent public collections: (a) experts' own blogs/newsletters —
  SVPG (Cagan), Product Talk (Torres), caseyaccidental.com (Winters), Gibson Biddle's
  Substack + public PDF decks, free Substack posts for Zhuo/Verna; (b) the ChatPRD
  Lenny's-Podcast transcript archive on GitHub, council-expert episodes only (~15), pinned to
  a commit SHA.
- **Rationale**: Satisfies FR-017 (full roster — transcripts restore Shreyas/Chesky/Verna/Zhuo)
  and FR-020 (two source types). **Verified 2026-08-12** via GitHub API: 303 episodes, YAML
  frontmatter, speaker-labeled timestamped turns, all 8 roster experts present.
- **Alternatives considered**: Scraping X/Twitter for Shreyas (fragile, ToS-hostile — rejected);
  paywalled Lenny's Newsletter (rejected; free posts only); ingesting all 303 episodes
  (rejected: dilutes the council concept, multiplies enrichment cost).

## R8. Chunking strategy

- **Decision**: Articles/PDFs: heading-aware recursive splitting to ~450 tokens with ~60
  overlap, `heading_path` prepended for embedding context. Transcripts: Q&A units
  (interviewer question + guest answer) with start timestamps; chunks attributed to the guest,
  never merged across question boundaries.
- **Rationale**: Respects each medium's natural structure; timestamps enable deep-link
  citations (`&t=` seconds → FR-011/User Story 4); guest attribution enforces Constitution III
  on multi-speaker material.
- **Alternatives considered**: Fixed-size sliding window (ignores structure, splits answers
  mid-thought); per-article single chunks (too coarse for retrieval).

## R9. Enrichment & metadata vocabulary

- **Decision**: One-time offline LLM pass (dev key from env) adding 2–5 topic tags from a
  controlled ~25-term PM vocabulary plus a 2-sentence summary, via structured JSON output;
  the repo's transcript frontmatter `keywords` are ignored (observed to be generic/repeated).
- **Rationale**: Controlled vocabulary makes metadata filtering and eval slicing reliable;
  structured-output curation is itself an assignment functionality feeding another
  (metadata filtering).
- **Alternatives considered**: Free-form tags (vocabulary drift kills filtering); embedding-
  cluster topics (unlabeled, unexplainable).

## R10. Evaluation methodology

- **Decision**: Hand-built dataset of ~40 PM questions with expected source docs
  (`evaluation/dataset.jsonl`); retrieval metrics hit-rate@5 and MRR with ablations
  (dense-only vs hybrid vs hybrid+rerank); LLM-judge faithfulness scoring of ~20 generated
  answers on the dev key; results table published in README (FR-018, SC-006).
- **Rationale**: Ablations show each pipeline stage earns its place; grounded-in-corpus
  judging targets the product's core risk (fabricated advice).
- **Alternatives considered**: RAGAS framework (heavier dependency; custom metrics are
  transparent and assignment-reviewable); synthetic question generation (risks testing what
  the corpus says rather than what PMs ask).

## R11. Prompt layout & caching

- **Decision**: Static-first prompt order (system instructions → few-shot exemplars → then
  variable chunks/question), with the dynamic few-shot selector choosing 1–2 of ~10
  hand-written exemplars by query embedding similarity.
- **Rationale**: Static-prefix layout is cache-friendly across turns on providers with prompt
  caching (stretch functionality, README-documented); dynamic few-shot is a committed
  assignment functionality and keeps format discipline cheap.
- **Alternatives considered**: All exemplars every turn (token waste); no few-shot (council
  format drifts).

## R12. Session & key handling

- **Decision**: Provider + key live in Gradio session state only (`gr.State`), validated by a
  ~1-token ping on first use; adapters constructed per-request from session state; explicit
  log scrubbing — no key ever enters logging, error text, or persisted artifacts.
- **Rationale**: FR-008/FR-009 and Constitution I; per-request construction avoids cross-user
  leakage in a shared Space process.
- **Alternatives considered**: Env-var key on the Space (violates user-key-only principle);
  browser localStorage persistence (convenience not worth the never-persisted guarantee).

## R13. UI layout direction

- **Decision**: Adopt the layout pattern of the Towards AI tutor Space (reviewed from a user
  screenshot 2026-08-12) adapted to this product: left sidebar carrying the expert roster
  (avatars + names; mode toggle drives it — all-selected in council mode, single-select in
  expert mode) plus the API-key setup; empty-state hero with ~4 example PM-situation cards
  that submit on click (FR-021); provider shown as a chip near the input bar; a first-class
  sources panel (📄/🎙) under each answer. Implemented in themed Gradio Blocks + custom CSS,
  accepting "clean, not pixel-perfect."
- **Rationale**: The reference proves this layout works for a knowledge-grounded tutor on
  Spaces; the roster-in-sidebar makes "whose thinking is this?" visible pre-question
  (FR-021); example cards directly serve SC-001. Where we diverge deliberately: BYO key must
  be prominent (their Space uses a host key; ours constitutionally cannot), and citations get
  first-class placement (FR-011 is our differentiator).
- **Alternatives considered**: Stock `gr.ChatInterface` (fastest, but no roster/sources
  affordances); custom frontend in a Docker Space (matches the reference pixel-for-pixel but
  costs frontend effort the assignment doesn't grade); free multi-select of experts as a third
  mode (deferred — spec defines two modes; revisit post-MVP).
