# Quickstart & Validation Guide: AI PDM Leadership Council

Runnable scenarios proving the feature end-to-end. All Python via the project venv
(Constitution IV) — commands assume repo root.

## Prerequisites

```bash
python3 -m venv .venv                      # once (already created in this repo)
.venv/bin/pip install -r requirements.txt
export DEV_LLM_API_KEY=...                 # offline pipeline only — never committed, never the app's key
```

## 1. Build the corpus (offline, dev machine only)

```bash
.venv/bin/python data_collection/fetch.py --all          # or --expert shreyas-doshi
.venv/bin/python data_collection/parse.py
.venv/bin/python data_collection/enrich.py               # uses DEV_LLM_API_KEY
.venv/bin/python data_collection/chunk.py
.venv/bin/python data_collection/build_index.py          # prints per-expert/per-topic stats
```

**Expected**: `data/curated/` populated (~150–270 JSON files), `data/chunks.jsonl`
(~3,000–5,500 lines), `data/index/` containing `chroma/` + `bm25.pkl`. Stats show every
roster expert with >0 chunks. See [contracts/data-schemas.md](./contracts/data-schemas.md).

### 1b. Validate rebuild reproducibility (US5)

| # | Scenario | Steps | Expected |
|---|---|---|---|
| G | Fresh-clone single-expert rebuild | On a clean checkout (no `data/raw/`): venv setup, then run stages 1–2 with `--expert shreyas-doshi` | Curated JSON records appear, each with expert name, title, URL, date, content type — no manual edits needed (US5-AS1) |
| H | Full-roster coverage | After a full pipeline run, read `build_index.py` stats | Every roster expert >0 chunks; both source collections (blog + podcast archive) present (US5-AS2) |
| I | Idempotent re-run | Re-run `fetch.py --all` then `parse.py` with no source changes | Manifest reports all skips; `data/curated/` byte-identical; no duplicate works (US5-AS3) |
| J | Key separation | Inspect env: only `DEV_LLM_API_KEY` used by `enrich.py`; grep pipeline code for provider key params | No user-key path exists in `data_collection/`; app never imports it (US5-AS4, Constitution I/II) |

## 2. Run tests

```bash
.venv/bin/python -m pytest tests/ -v                     # all
.venv/bin/python -m pytest tests/unit/test_chunk.py -v   # single file
```

**Expected**: unit (parse/chunk/route/prompt), contract (all three provider adapters against
the [provider protocol](./contracts/provider-protocol.md)), and integration (retrieval against
the committed index) suites pass.

## 3. Run the app locally

```bash
.venv/bin/python app.py                                   # http://localhost:7860
```

Manual validation, one scenario per user story (spec acceptance scenarios):

| # | Story | Steps | Expected |
|---|---|---|---|
| A | US3 key handling | Ask before entering a key; then paste an invalid key; then a valid one | Prompted for key, no spend; clear invalid-key error; valid key works |
| B | US1 council | Ask "My engineering team keeps pushing back on my roadmap" | Streamed answer: Situation → ≥2 expert-attributed Perspectives → numbered Actions; sources panel |
| C | US2 expert | Select Shreyas Doshi, ask about prioritization; then ask him something off his corpus | All citations = Shreyas only; honest gap message on second question |
| D | US2 routing | In council mode ask "What would Marty Cagan say about feature teams?" | Answer drawn from Cagan material (auto-filter) |
| E | US4 sources | Click every citation from B–D | Articles open originals; podcast links land at the cited moment |
| F | Off-topic | Ask for a lasagna recipe | Brief scope reply, visibly no full generation |
| K | FR-021 empty state | Load the app fresh; inspect before typing | Expert roster visible; ~4 example PM-situation cards shown; clicking one submits it as the question |

## 4. Run the evaluation (offline, dev key)

```bash
.venv/bin/python evaluation/run_retrieval_eval.py        # hit-rate@5, MRR + ablations table
.venv/bin/python evaluation/run_answer_eval.py --n 20    # LLM-judge faithfulness
```

**Expected**: hit-rate@5 ≥ 0.80 (SC-006); ablation table shows hybrid ≥ dense-only and
+rerank ≥ hybrid; results pasted into README.

## 5. Deploy & verify the Space

```bash
# Space repo contains: app.py, rag/, data/{curated,chunks.jsonl,index}, requirements.txt, README.md
# (data/raw and .venv excluded)
```

On the public Space, re-run scenarios A, B, and F with a real user key, and confirm:
cold boot works from committed artifacts alone (no indexing on boot), first token <5 s
(SC-007), and the README shows required keys, cost estimate (≤$0.50 full trial, SC-002),
the ≥5 implemented optional functionalities (FR-019), and the eval results table (FR-018).
