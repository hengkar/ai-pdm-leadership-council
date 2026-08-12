# Implementation Plan: AI PDM Leadership Council

**Branch**: `001-pdm-leadership-council` | **Date**: 2026-08-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-pdm-leadership-council/spec.md`

## Summary

A RAG web app where PMs ask situational questions and get streamed, cited answers grounded in
the published thinking of ~8 named product leaders, in two modes (Ask the Council / Ask an
Expert). Approach: an offline five-stage corpus pipeline (fetch → parse → enrich → chunk →
index, per `PLAN_DATA_PIPELINE.md` and `PLAN_TRANSCRIPTS.md`) produces committed Chroma + BM25
indexes with expert/source/timestamp metadata on every chunk; a Gradio app on a Hugging Face
Space runs the runtime pipeline (typed query routing → hybrid retrieval → local rerank →
mode-specific prompt → streamed generation on the user's key, per `PLAN_QUERY_FLOW.md`).

## Technical Context

**Language/Version**: Python 3.13 (all invocations via `.venv/bin/python` / `.venv/bin/pip`, per Constitution IV)

**Primary Dependencies**: Gradio 5.x (UI + streaming), `chromadb` (dense index),
`sentence-transformers` (`BAAI/bge-small-en-v1.5` embeddings + `BAAI/bge-reranker-base`
cross-encoder), `rank_bm25` (sparse index), provider SDKs `openai` / `google-genai` /
`anthropic`, `pydantic` v2 (schemas), `trafilatura` + `beautifulsoup4` (HTML parsing),
`pymupdf` (PDF), `python-frontmatter` (transcript YAML), `PyYAML` (source registry)

**Storage**: Files only — curated JSON per source work (`data/curated/`), `data/chunks.jsonl`,
persistent Chroma store + pickled BM25 index (`data/index/`, committed); no database, no user
data persistence (Constitution: no accounts/sessions persist)

**Testing**: pytest (`.venv/bin/python -m pytest`); unit tests for parsing/chunking/routing,
contract tests for the provider adapters, integration test for the retrieval pipeline against
the real committed index

**Target Platform**: Public Hugging Face Space (Gradio SDK, free CPU tier); local dev on macOS

**Project Type**: Single Python web application with an offline data-pipeline toolchain

**Performance Goals**: First streamed token <5 s after submit (SC-007); local retrieval +
rerank <2 s on Space CPU; first complete cited answer within 3 min of first visit (SC-001)

**Constraints**: ≤US$0.50 total trial cost on user key (SC-002); off-topic replies <US$0.01
(SC-008); user key session-only, never logged (FR-008); all corpus work offline on dev key
(Constitution II); Space cold-boot must work from committed artifacts alone

**Scale/Scope**: ~8 experts, ~150–270 source works, ~3,000–5,500 chunks; single Space
instance, handful of concurrent users; corpus rebuilds are rare offline events

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | How the design complies |
|---|---|---|---|
| I | User-key-only spend, ≤$0.50 | ✅ PASS | Only routing (~250 tok) + generation (~4k tok) touch the user key on cheap-tier models; off-topic short-circuits in routing; no user-triggered batch jobs exist |
| II | Offline corpus, free runtime | ✅ PASS | Five-stage pipeline runs offline with dev key from env; embeddings/rerank are local models; indexes committed so the Space boots ready |
| III | Attribution integrity | ✅ PASS | `expert` + `source` metadata is mandatory on every chunk (pydantic-enforced); citations rendered from chunk metadata only; prompts forbid impersonation and mandate gap disclosure |
| IV | Venv-only Python | ✅ PASS | All commands in quickstart/tasks/docs written as `.venv/bin/python`; `requirements.txt` committed; `.venv/` ignored |
| V | Spec-driven, assignment-bound | ✅ PASS | This plan implements spec FR-001–FR-020 incl. README/eval/Space delivery; PLAN_*.md remain the HOW references and are updated on drift |

**Initial gate**: PASS (no violations, Complexity Tracking not needed).
**Post-Phase-1 re-check**: PASS — design artifacts introduce no new violations; the provider
contract explicitly bans key persistence/logging, and the data model makes attribution fields
required.
**Re-audit 2026-08-12 (spec US5 added)**: PASS unchanged — the rebuild story maps onto the
existing `data_collection/` package, the manifest idempotency rule in `contracts/data-schemas.md`,
and quickstart §1b scenarios G–J; no design change required.
**Re-audit 2026-08-12 (spec FR-021 + UI direction added)**: PASS unchanged — the empty state
spends nothing (Principle I: example cards are static text; no provider call until the user
submits), reads the roster from committed index metadata (Principle II: no runtime corpus
access), and displays experts by their canonical names (Principle III). Added `ui_content.py`,
`rag/roster.py`, and `contracts/ui-contract.md` to the design; no principle tension arose.

## Project Structure

### Documentation (this feature)

```text
specs/001-pdm-leadership-council/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── provider-protocol.md
│   ├── data-schemas.md
│   ├── pipeline-events.md
│   └── ui-contract.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
app.py                      # Gradio Blocks UI + wiring only (no business logic)
ui_content.py               # example PM situations + UI copy for the empty state (FR-021)
rag/
├── __init__.py
├── roster.py               # expert roster accessor: reads index metadata, feeds sidebar + router validation
├── router.py               # typed query routing via structured output (FR-012, FR-013)
├── retrieve.py              # hybrid search: Chroma + BM25 + RRF fusion, metadata filters
├── rerank.py                # local cross-encoder, diversity cap, score threshold
├── prompts.py               # mode system prompts, few-shot library + dynamic selector
├── llm.py                   # LLMClient protocol + OpenAI/Gemini/Claude adapters
└── pipeline.py              # orchestrates route→retrieve→rerank→prompt→generate, yields events

data_collection/
├── sources.yaml             # expert/source registry incl. transcript slug→expert map
├── schemas.py               # pydantic models shared by all stages
├── fetch.py                 # stage 1: WordPress/Substack/PDF/GitHub-repo adapters
├── parse.py                 # stage 2: HTML/PDF/transcript → curated JSON
├── enrich.py                # stage 3: LLM topic tags + summaries (dev key, offline)
├── chunk.py                 # stage 4: heading-aware / Q&A-unit chunking
└── build_index.py           # stage 5: Chroma + BM25 build with stats report

data/
├── raw/                     # fetch cache (gitignored)
├── curated/                 # committed JSON per source work
├── chunks.jsonl             # committed
└── index/                   # committed: chroma/ + bm25.pkl

evaluation/
├── dataset.jsonl            # ~40 PM questions with expected sources (FR-018)
├── run_retrieval_eval.py    # hit-rate / MRR, hybrid & rerank ablations
└── run_answer_eval.py       # LLM-judge faithfulness pass (dev key)

tests/
├── unit/                    # parsing, chunking, routing, prompt selection
├── contract/                # provider adapter contract tests
└── integration/             # retrieval pipeline against committed index

requirements.txt
README.md                    # project explanation, keys list, cost estimate, functionalities, eval results
```

**Structure Decision**: Single Python project. `rag/` (runtime) and `data_collection/`
(offline) are strictly separated packages sharing only `data/` artifacts and
`data_collection/schemas.py` — this bounds Constitution II at the package level: nothing in
`rag/` may import fetch/enrich code or the dev key. `app.py` stays a thin UI shell so the
pipeline is testable headlessly; user-facing copy and example situations live in
`ui_content.py` so they can change without touching wiring, and `rag/roster.py` is the single
source of expert names for both the sidebar and router validation (never a hardcoded list).

## Complexity Tracking

No constitution violations — table not required.
