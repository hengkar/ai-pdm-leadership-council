---

description: "Task list for AI PDM Leadership Council implementation"
---

# Tasks: AI PDM Leadership Council

**Input**: Design documents from `/specs/001-pdm-leadership-council/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md, constitution v1.0.0

**Tests**: Included where `plan.md` specifies them (contract tests for provider adapters, unit tests for parsing/chunking/routing, integration test for retrieval). The provider protocol and data schemas contracts both state rules as "contract-tested", so those tests are required, not optional.

**Organization**: Tasks are grouped by user story. All Python commands run via `.venv/bin/python` (Constitution IV).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Exact file paths included in every task

## Path Conventions

Single Python project at repository root: `app.py`, `ui_content.py`, `rag/`, `data_collection/`, `data/`, `evaluation/`, `tests/` (per plan.md Structure Decision).

## ⚠️ Sequencing note (read before starting)

Spec priorities rank **US1 (council answers) as P1**, but two P2 stories are hard *enablers*:
**US5** produces the corpus every answer depends on, and **US3** supplies the API key without
which no answer can be generated. Phases below therefore run US5 → US3 → US1. The priority
order still governs *value*: US1 is the payoff and the MVP demo, and everything before it
exists to make it possible. This matches plan.md's "Order of Attack".

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton and dependencies

- [X] T001 Create `requirements.txt` at repo root with pinned deps from plan.md Technical Context (gradio, chromadb, sentence-transformers, rank_bm25, openai, google-genai, anthropic, pydantic, trafilatura, beautifulsoup4, pymupdf, python-frontmatter, PyYAML, pytest)
- [X] T002 [P] Create `.gitignore` at repo root excluding `.venv/`, `data/raw/`, `__pycache__/`, `.env`, `*.pyc`
- [X] T003 [P] Create package skeletons: `rag/__init__.py`, `data_collection/__init__.py`, `evaluation/.gitkeep`, `tests/unit/`, `tests/contract/`, `tests/integration/`
- [X] T004 Install dependencies with `.venv/bin/pip install -r requirements.txt` and verify imports in `tests/unit/test_imports.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared schemas, registry, and safety infrastructure that every story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T005 Implement pydantic v2 models per data-model.md in `data_collection/schemas.py`: `SourceWork`, `Chunk`, `EvalCase`, `ContentType` enum, and `SCHEMA_VERSION` constant; enforce required attribution fields (`expert`, `doc_id`, `url`) and the rule that `timestamp_s` is required iff `content_type == podcast_transcript`
- [X] T006 [P] Create the expert/source registry in `data_collection/sources.yaml` with the 8 roster experts (FR-017), per-source adapter configs, and the pinned-SHA `github_repo` entry with its episode-slug→expert map (research.md R7)
- [X] T007 [P] Define the ~25-term controlled topic vocabulary in `data_collection/vocabulary.py` (research.md R9)
- [X] T008 [P] Implement the shared error taxonomy and key-scrubbing log filter in `rag/errors.py`: `KeyStatus`, `ProviderError`, and a scrubber guaranteeing no API key reaches logs or exception text (contracts/provider-protocol.md rule 1, Constitution I)
- [X] T009 [P] Implement path/model constants in `rag/config.py`: index paths, embedding and reranker model ids, per-provider model ids, retrieval top-k values, and the rerank score threshold

**Checkpoint**: Schemas, registry, and safety plumbing ready — story work can begin

---

## Phase 3: User Story 5 - Rebuild the Knowledge Base (Priority: P2, enabler) 🔧

**Goal**: A reproducible offline pipeline that turns public expert material into committed, attributed indexes — the corpus every answer draws on.

**Independent Test**: On a fresh clone, run the documented rebuild for one expert and verify attributed corpus records appear with no manual editing; run it fully and verify every roster expert is represented (quickstart §1b scenarios G–J).

### Tests for User Story 5

- [X] T010 [P] [US5] Unit test transcript speaker-turn attribution in `tests/unit/test_parse_transcript.py`: chunks attribute to the guest never the interviewer, and repeat-appearance slugs collapse to one canonical expert
- [X] T011 [P] [US5] Unit test chunking invariants in `tests/unit/test_chunk.py`: article chunks never cross work boundaries, transcript chunks never cross question boundaries, podcast chunks always carry `timestamp_s`
- [X] T012 [P] [US5] Unit test fetch idempotency in `tests/unit/test_manifest.py`: unchanged content hashes are skipped and produce no duplicate works (US5-AS3)

### Implementation for User Story 5

- [X] T013 [US5] Implement the adapter framework and `github_repo` adapter in `data_collection/fetch.py`: shallow clone pinned to SHA, council episodes only, manifest write to `data/raw/manifest.json`, `--expert` and `--force` flags
- [X] T014 [US5] Implement transcript parsing in `data_collection/parse.py`: frontmatter extraction, `Name (HH:MM:SS):` turn splitting, guest attribution, sponsor/intro stripping, and the known-quirk handling from PLAN_TRANSCRIPTS.md (duplicate dirs, unreliable frontmatter durations)
- [X] T015 [P] [US5] Add the WordPress/RSS adapter to `data_collection/fetch.py` for SVPG, Product Talk, and caseyaccidental.com (rate-limited, robots-respecting)
- [~] T016 [P] [US5] ~~Substack adapter~~ — **dropped at user's direction.** Biddle, Zhuo and Verna are represented through the podcast archive instead.
- [X] T017 [P] [US5] Add HTML and PDF parsing to `data_collection/parse.py` using trafilatura and pymupdf, with boilerplate stripping, content-hash dedupe, and the ≥300-word quality gate
- [X] T018 [US5] Implement the offline enrichment pass in `data_collection/enrich.py`: structured-JSON topic tags from the controlled vocabulary plus 2-sentence summaries, reading `DEV_LLM_API_KEY` from env only (Constitution II, US5-AS4)
- [X] T019 [US5] Implement both chunking strategies in `data_collection/chunk.py`: heading-aware ~450-token article chunks with `heading_path`, and Q&A-unit transcript chunks with start timestamps; write `data/chunks.jsonl`
- [X] T020 [US5] Implement `data_collection/build_index.py`: local `bge-small-en-v1.5` embeddings into the persistent Chroma collection `council` with full metadata, BM25 pickle, `SCHEMA_VERSION` stamping, and a per-expert/per-topic stats report
- [ ] T021 [US5] Run the full pipeline end to end and commit `data/curated/`, `data/chunks.jsonl`, and `data/index/`; paste the stats report into a corpus section of `README.md`

**Checkpoint**: A committed, attributed, reproducible corpus exists — retrieval work can begin

---

## Phase 4: User Story 3 - Bring Your Own API Key (Priority: P2, enabler) 🔑

**Goal**: Users supply their own provider key, it works for the session, never persists, and failures are explained clearly.

**Independent Test**: Paste an invalid key and see an immediate clear error; paste a valid one and see a call succeed; restart and confirm the key is gone (quickstart scenario A).

### Tests for User Story 3

- [X] T022 [P] [US3] Contract tests for all three adapters against contracts/provider-protocol.md in `tests/contract/test_provider_protocol.py`: `validate_key` never raises, `classify` returns validated schema instances, `stream` yields deltas, and the uniform error taxonomy holds
- [X] T023 [P] [US3] Key-hygiene test in `tests/contract/test_key_hygiene.py`: the key appears in no `__repr__`, no exception message, and no log record across all three adapters

### Implementation for User Story 3

- [X] T024 [US3] Define the `LLMClient` protocol, `Message`, and `ProviderName` types in `rag/llm.py` per contracts/provider-protocol.md
- [X] T025 [P] [US3] Implement the OpenAI adapter (`gpt-4o-mini`) in `rag/llm.py` with structured-output `classify` and streaming `stream`
- [X] T026 [P] [US3] Implement the Gemini adapter (`gemini-2.0-flash`) in `rag/llm.py`
- [X] T027 [P] [US3] Implement the Anthropic adapter (`claude-haiku-4-5`) in `rag/llm.py`
- [X] T028 [US3] Implement `make_client(provider, api_key)` and the ~1-token `validate_key` ping in `rag/llm.py`, mapping all provider failures to the shared `KeyStatus`/`ProviderError` taxonomy (FR-009)
- [X] T029 [US3] Implement `SessionState` in `app.py` as `gr.State` holding provider, key, and validation flag — never persisted, never echoed back into the field (FR-008, contracts/ui-contract.md)
- [X] T030 [US3] Build the Gradio Blocks shell in `app.py`: sidebar provider selector, masked key field, key-status indicator, and submit disabled until a key is present

**Checkpoint**: A key can be supplied and validated; generation is now possible

---

## Phase 5: User Story 1 - Ask the Product Council (Priority: P1) 🎯 MVP

**Goal**: A PM describes a situation and receives a streamed, structured, multi-expert answer with sources.

**Independent Test**: With a valid key, ask "My engineering team keeps pushing back on my roadmap" and verify ≥2 expert-attributed perspectives, numbered recommended actions, progressive streaming, and a sources list (quickstart scenario B).

### Tests for User Story 1

- [X] T031 [P] [US1] Integration test for hybrid retrieval against the committed index in `tests/integration/test_retrieve.py`: RRF fusion returns relevant chunks for known PM questions and the council diversity cap yields ≥2 experts
- [X] T032 [P] [US1] Integration test for the pipeline event contract in `tests/integration/test_pipeline_events.py`: exactly one terminal outcome per call, `Sources` derived only from retrieved chunks, and no key in any payload (contracts/pipeline-events.md)

### Implementation for User Story 1

- [X] T033 [US1] Implement `rag/roster.py`: build `RosterEntry` list by scanning committed index metadata at startup, excluding experts with zero chunks; never read `sources.yaml` or `data/curated/` at runtime (Constitution II, data-model.md)
- [X] T034 [US1] Implement hybrid retrieval in `rag/retrieve.py`: query embedding with the index-time model, dense top-30 from Chroma, sparse top-30 from BM25, RRF fusion (k=60), returning `RetrievalResult` objects carrying both ranks
- [X] T035 [US1] Implement `rag/rerank.py`: local `bge-reranker-base` cross-encoder over the fused top-20, per-expert diversity cap for council mode, and the score threshold that triggers a coverage gap instead of a weak answer
- [X] T036 [US1] Implement `rag/prompts.py`: council system prompt producing Situation → Perspectives → Recommended Actions, the ~10-exemplar few-shot library with embedding-similarity selection of 1–2, the no-impersonation and synthesize-don't-quote rules, and cache-friendly static-first ordering (FR-004, FR-006, research.md R11)
- [X] T037 [US1] Implement `rag/router.py`: typed classification via each provider's structured-output mode returning `pm_question | off_topic | expert_mentioned`, with unknown expert names falling back to `pm_question` (FR-012, research.md R6)
- [X] T038 [US1] Implement `rag/pipeline.py`: the `answer()` generator orchestrating route → retrieve → rerank → prompt → stream and emitting the full event taxonomy with its terminal-outcome and supersede guarantees (contracts/pipeline-events.md)
- [X] T039 [P] [US1] Write the ~4 `ExamplePrompt` entries and product framing copy in `ui_content.py`, covering situations the corpus actually addresses (FR-021)
- [X] T040 [US1] Wire the conversation surface in `app.py`: empty-state hero with clickable example cards, streaming answer rendering from `AnswerDelta`, and distinct visual treatments for `OffTopic`, `CoverageGap`, `KeyProblem`, and `Failure` (FR-010, FR-021, contracts/ui-contract.md rules 1–2)
- [X] T041 [US1] Render the sources list under each answer in `app.py` from the `Sources` event: expert, work title, and link for every contributing chunk (FR-011 baseline; deep-link polish in US4)

**Checkpoint**: 🎯 **MVP reached** — the council answers real questions with citations. Demoable.

---

## Phase 6: User Story 2 - Ask a Specific Expert (Priority: P2)

**Goal**: A single selected expert answers from their own material only, and admits gaps honestly.

**Independent Test**: Select Shreyas Doshi, ask about prioritization and verify every citation is his; then ask something outside his corpus and verify an honest gap message (quickstart scenario C).

### Tests for User Story 2

- [X] T042 [P] [US2] Test expert-filter purity in `tests/integration/test_expert_mode.py`: with an expert filter applied, 100% of returned chunks belong to that expert across both Chroma and BM25 paths (SC-005)

### Implementation for User Story 2

- [X] T043 [US2] Add metadata filtering to `rag/retrieve.py`: Chroma `where={"expert": ...}` plus equivalent post-filtering of BM25 candidates, and optional `content_type` filtering (FR-003, research.md R3)
- [X] T044 [US2] Add the expert-mode system prompt to `rag/prompts.py`: answers framed as "in the spirit of {expert}'s published thinking", never first person, with explicit coverage-gap disclosure when excerpts are silent (FR-005, FR-006)
- [X] T045 [US2] Handle the `expert_mentioned` route in `rag/pipeline.py` so a council-mode question naming an expert auto-applies that expert's filter (FR-013, quickstart scenario D)
- [X] T046 [US2] Add the sidebar roster UI in `app.py`: experts from `rag.roster` with source-kind hints, mode toggle driving selection (all shown in council mode, single-select in expert mode) — never a hardcoded list (contracts/ui-contract.md rule 4)

**Checkpoint**: Both product modes work independently

---

## Phase 7: User Story 4 - Verify the Sources (Priority: P3)

**Goal**: Every citation resolves to real published material, with podcast citations jumping to the moment.

**Independent Test**: Ask several questions and follow every citation; articles open originals and podcast links land at the cited moment (quickstart scenario E).

### Tests for User Story 4

- [X] T047 [P] [US4] Test citation construction in `tests/unit/test_citations.py`: citations build from chunk metadata only, podcast citations always include a `&t=` offset matching `timestamp_s`, and no citation can exist without a backing retrieved chunk

### Implementation for User Story 4

- [X] T048 [US4] Implement the `Citation` model and deep-link construction in `rag/pipeline.py`: `youtube_url + "&t=" + timestamp_s` for podcast chunks, plain original URL for written works (FR-011)
- [X] T049 [US4] Render the differentiated sources panel in `app.py`: 📄 expert — "title" → link for written works, 🎙 expert on Lenny's Podcast (mm:ss) → timestamped link for episodes
- [X] T050 [P] [US4] Add a link-health check in `evaluation/check_links.py` that samples corpus URLs and reports unreachable ones (supports SC-004)

**Checkpoint**: All five user stories independently functional

---

## Phase 8: Evaluation & Assignment Delivery

**Purpose**: The graded obligations — measured quality, public deployment, documented cost (FR-014, FR-016, FR-018, FR-019)

- [X] T051 [P] Hand-write ~40 PM questions with expected source doc ids and topic tags in `evaluation/dataset.jsonl` per the `EvalCase` schema
- [X] T052 Implement `evaluation/run_retrieval_eval.py`: hit-rate@5 and MRR with dense-only vs hybrid vs hybrid+rerank ablations, emitting a markdown results table (SC-006)
- [X] T053 Implement `evaluation/run_answer_eval.py`: LLM-judge faithfulness scoring of ~20 generated answers against their retrieved excerpts, run on `DEV_LLM_API_KEY`
- [X] T054 Write `README.md`: project explanation, required API keys by name, cost estimate showing a full trial under $0.50, the list of implemented optional functionalities (≥5, FR-019), evaluation results tables, and corpus/sourcing attribution notes
- [!] T055 Deploy to a public Hugging Face Space: push `app.py`, `ui_content.py`, `rag/`, `data/curated/`, `data/chunks.jsonl`, `data/index/`, `requirements.txt`, and `README.md`, excluding `data/raw/` and `.venv/` (FR-016)
      ↳ **BLOCKED — no Hugging Face token available.** Needs your HF account; deployment is also an outward-facing publish I should not do unilaterally.
- [!] T056 Verify on the live Space: cold boot from committed artifacts with no indexing, first token under 5 s, and quickstart scenarios A, B, and F with a real user key (SC-001, SC-007, SC-008)
      ↳ **BLOCKED — depends on T055.**

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T057 Run the full quickstart validation (scenarios A–K plus G–J) from `specs/001-pdm-leadership-council/quickstart.md` and record results
- [ ] T058 [P] Add remaining unit tests in `tests/unit/` for router fallbacks, prompt few-shot selection, and roster construction
- [X] T059 [P] Measure and tune retrieval + rerank latency on Space-equivalent CPU; document timings in `README.md`
- [ ] T060 [P] Sync documentation with as-built reality: `CLAUDE.md` commands section, `PLAN*.md` deviations, and this feature's spec/plan if any decision changed (Constitution V, Development Workflow)

---

## Phase 10: Session Key Lifecycle (US3 follow-up) 🔑

**Why this phase exists**: two defects reached a running app in this exact area,
neither caught by 155 passing tests, because both are event-sequence bugs that
only appear when real browser events fire in order. Found by using the app.

**Goal**: an accepted key stays usable for the session, and never outlives the
provider it was issued for.

**Independent Test**: paste a key, click an example card, and get an answer
(FR-022); then switch provider and confirm a new key is required (FR-023).

- [X] T061 [US3] Fix `check_key` in `app.py` so an empty key field does not revoke an already-accepted key. Validation clears the visible field for hygiene, so the next `blur` arrives empty while the key is still good in session state — the field is an input, not the record of truth (FR-022)
- [X] T062 [US3] Add `switch_provider` in `app.py` so changing provider discards the key and requires a new one, and wire it to the provider dropdown. Prevents a key being sent to a provider it was not issued for (FR-023, Constitution I)
- [X] T063 [P] [US3] Regression tests in `tests/unit/test_key_lifecycle.py` covering the empty-blur sequence, key replacement, provider switch, same-provider no-op, and no-provider-call-without-a-key

**Checkpoint**: the session key behaves correctly across real UI event sequences

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all stories
- **US5 (Phase 3)**: Depends on Foundational — produces the corpus that US1/US2/US4 consume
- **US3 (Phase 4)**: Depends on Foundational only — can run fully parallel with US5 (different files, no shared state)
- **US1 (Phase 5)**: Depends on US5 (needs an index) and US3 (needs a working client)
- **US2 (Phase 6)**: Depends on US1's retrieval/prompt modules
- **US4 (Phase 7)**: Depends on US1's pipeline and citation flow
- **Phase 8**: Depends on US1 at minimum; full results need US2 and US4
- **Phase 9**: Depends on all desired stories

### Story Independence

- **US5** is testable with no app at all (pipeline outputs are the deliverable)
- **US3** is testable with no corpus (contract tests use fake transports)
- **US1** is the first story requiring both enablers; it is the MVP demo
- **US2** and **US4** are additive slices over US1 and are independently demoable

### Parallel Opportunities

- T002, T003 in Setup
- T006, T007, T008, T009 in Foundational (four different files)
- **Whole-phase parallelism**: US5 (Phase 3) and US3 (Phase 4) touch disjoint files — one developer per phase is the highest-leverage split
- Within US5: T010–T012 (tests), then T015/T016/T017 (adapters and parsers in separate concerns)
- Within US3: T022/T023 (tests), then T025/T026/T027 (three provider adapters)
- Within US1: T031/T032 (tests); T039 is independent of all retrieval work
- T051 can be written any time after the corpus exists

---

## Parallel Example: User Story 3

```bash
# Launch the three provider adapters together (same protocol, separate implementations):
Task: "Implement the OpenAI adapter (gpt-4o-mini) in rag/llm.py"
Task: "Implement the Gemini adapter (gemini-2.0-flash) in rag/llm.py"
Task: "Implement the Anthropic adapter (claude-haiku-4-5) in rag/llm.py"

# Launch both contract test suites together:
Task: "Contract tests for all three adapters in tests/contract/test_provider_protocol.py"
Task: "Key-hygiene test in tests/contract/test_key_hygiene.py"
```

---

## Implementation Strategy

### MVP scope

**Phases 1–5** (Setup → Foundational → US5 → US3 → US1). That is the smallest set that
produces a demoable product: a real corpus, a user-supplied key, and streamed council answers
with citations. US2 and US4 are deliberately excluded from MVP — valuable, but the council
experience alone proves the concept.

### Incremental delivery

1. Setup + Foundational → skeleton ready
2. US5 → corpus committed and reproducible (reviewable on its own)
3. US3 → key handling proven by contract tests
4. US1 → **MVP: demo the council**, stop and validate
5. US2 → expert mode
6. US4 → citation depth
7. Phase 8 → eval, README, Space deployment (assignment certification)
8. Phase 9 → polish

### Parallel team strategy

After Foundational, split US5 (data pipeline) and US3 (provider layer) — they share no files
and together unblock US1. Converge on US1, then fan out again to US2 and US4.

---

## Notes

- Every Python invocation uses `.venv/bin/python` or `.venv/bin/pip` (Constitution IV)
- `DEV_LLM_API_KEY` is used only by `data_collection/enrich.py` and `evaluation/`; nothing under `rag/` or `app.py` may read it (Constitution I/II)
- Commit after each task or logical group; index artifacts are committed deliberately (T021)
- Stop at any checkpoint to validate a story independently
