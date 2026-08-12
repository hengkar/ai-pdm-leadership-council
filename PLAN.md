# Build Plan — AI PDM Leadership Council

A RAG application that helps junior/mid-level Product Managers by retrieving and synthesizing
thinking from experienced product leaders. Final project for an LLM course; must satisfy the
constraints in `requirement_assignment.txt`.

This is the overview document. Detailed designs live in three companion plans:

- **`PLAN_DATA_PIPELINE.md`** — offline ingestion: fetch → parse → enrich → chunk → index
- **`PLAN_TRANSCRIPTS.md`** — Lenny's Podcast transcript archive as a knowledge source
- **`PLAN_QUERY_FLOW.md`** — runtime: routing → hybrid retrieval → rerank → prompt → streamed answer

Where this overview and a companion plan disagree, the companion plan wins (it's more recent
and more considered).

## Recommended Stack

| Layer | Choice | Why |
|---|---|---|
| UI | Gradio on Hugging Face Spaces | The assignment's suggested path; free hosting, easy streaming chat |
| LLM | User-pasted key, supporting all three: OpenAI, Gemini, Claude | Requirement; provider becomes a dropdown, and the cheap tiers (gpt-4o-mini / gemini-flash / haiku) keep costs tiny |
| Embeddings | Local sentence-transformers model (e.g. `bge-small-en-v1.5`) | Indexing must never touch the user's key; runs free on the Space's CPU |
| Vector store | ChromaDB, prebuilt index committed to the repo | The Space boots with the index ready — zero indexing cost at runtime |
| Reranker | Local cross-encoder (`bge-reranker-base`) | Ticks the reranker requirement without API cost |

## The Core Design Decision

Expert attribution is metadata on every chunk (`expert`, `source_url`, `content_type`, `topics`).
That single decision makes both product modes fall out of the retriever:

- **Ask an Expert** = retrieval with a metadata filter on `expert`
- **Ask the Council** = unfiltered retrieval, results grouped by expert, then one synthesis
  prompt that presents 2–3 contrasting perspectives plus recommended actions (the structured
  format in `requirement_pdm_council.txt`)

## Phases

### 1. Data collection & curation (the real work)

Detailed in `PLAN_DATA_PIPELINE.md`. A source audit (stage 0) locks the expert list before any
code is written; the safe bets are:

- Marty Cagan — SVPG articles (WordPress)
- Teresa Torres — Product Talk blog (WordPress)
- Casey Winters — caseyaccidental.com (WordPress)
- Gibson Biddle — Substack + his public **PDF** strategy decks

Plus the **Lenny's Podcast transcript archive** (github.com/ChatPRD/lennys-podcast-transcripts,
see `PLAN_TRANSCRIPTS.md`): ~15 speaker-labeled, timestamped episode transcripts covering
**every expert in the product spec** — restoring Shreyas Doshi, Brian Chesky, Elena Verna, and
Julie Zhuo, whom the scraping audit had dropped. Target: 30–50 articles per blog expert plus
~15 transcripts, ~150–270 docs across ~8 experts.

Adapter-based fetch scripts driven by a `sources.yaml` registry output validated **structured
JSON** per article, followed by a one-time LLM enrichment pass (developer key, offline) that
adds controlled-vocabulary topic tags and summaries — those tags power metadata filtering in
the app. Scripts stay in the repo per the requirements.

### 2. Indexing pipeline

- Chunking: heading-aware ~450 tokens for articles; Q&A units with YouTube timestamps for
  podcast transcripts; expert/topic/content-type metadata on every chunk
- Local embeddings → Chroma index, plus a BM25 index for hybrid search
- `build_index.py`; index artifacts committed to the repo so the Space boots ready

### 3. RAG pipeline

Detailed in `PLAN_QUERY_FLOW.md` (including the Mermaid flow, module layout, and provider
abstraction).

Query
→ **query routing** (typed classification via structured output / **function calling**;
  off-topic questions short-circuit before any retrieval or key spend)
→ **hybrid search** (BM25 + dense, RRF fusion)
→ **metadata filter** (expert mode; council mode gets a per-expert diversity cap)
→ **rerank** (local cross-encoder) top-20 → top-5 into the prompt
→ prompt assembly with **dynamic few-shot** exemplars, cache-friendly layout
→ **streamed** answer with per-expert citations

### 4. Gradio app

- API-key textbox + provider dropdown (key held in session state only, never logged)
- Mode selector: Expert dropdown / Council
- Streaming chat with the structured response format (Your Situation → Perspectives → Recommended Actions)

### 5. RAG evaluation

- Hand-built eval set (~40 PM questions with expected source docs) in `evaluation/`
- Scripts computing retrieval hit-rate / MRR with vs. without reranking and hybrid search
- LLM-judge pass on answer faithfulness
- Results table goes in the README

### 6. README + deploy

- Project explanation, list of required API keys, cost estimate
- Cost estimate: embeddings/rerank are local, so ~15 test queries at ~3k tokens each on the
  cheap models ≈ **$0.02–0.05**, far under the $0.50 cap
- Optional-functionalities list
- Deploy to a public HF Space and test end-to-end

## Optional Functionalities Covered (need 5, plan hits 11–13)

Committed by the two detailed plans:

1. Streaming responses
2. Domain-specific app (PM leadership, not an AI tutor)
3. Two+ data sources beyond the course
4. Structured JSON in data curation (LLM enrichment → topic tags used for filtering)
5. Reranker (local cross-encoder)
6. Hybrid search (BM25 + dense, RRF)
7. Metadata filtering (expert mode + auto-filter from routing)
8. Query routing
9. Function calling (typed routing via structured output)
10. Dynamic few-shot prompting
11. RAG evaluation with dataset + scripts + results in README

Stretch (drop without regret if flaky):

12. PDF parsing in curation (Gibson Biddle's strategy decks) — pending stage-0 audit
13. Prompt-caching-friendly prompt layout, explained in README

Large buffer — several can fail and the project still clears the 5-functionality bar.

## Order of Attack

Data first (phases 1–2), because everything downstream depends on what the corpus actually
looks like — starting with the transcript archive (no scraping, proves the pipeline fastest),
then the blog adapters. Then a walking skeleton of the app with plain dense retrieval, then
layer in hybrid/rerank/routing, then eval, then polish and deploy.

## Note on Sourcing

Scraping expert blogs is for a personal course project with full attribution — keep the corpus
modest (dozens of articles per expert, not full-site mirrors) and cite sources in every answer.
Good RAG practice and respectful of the authors.
