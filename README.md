# 🏛 AI PDM Leadership Council

Situational advice for product managers, grounded in the published thinking of
experienced product leaders — and cited back to it.

A junior or mid-level PM describes a real situation ("my engineering team keeps
pushing back on my roadmap"). The app retrieves how experienced product leaders
have actually written and spoken about problems like it, then lays out where
they agree, where they differ, and what to do next. Every claim is traceable to
a source you can open.

Two modes:

- **Ask the Council** — several experts' perspectives, contrasted.
- **Ask an Expert** — one expert, answered only from their own material.

---

## Quick start

You need your own API key from one of three providers. The app ships with none
and never stores yours.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py          # http://localhost:7860
```

Paste a key in the sidebar, pick a mode, and ask.

### API keys you need

Exactly one of these, chosen from the sidebar dropdown:

| Provider | Key name | Model used | Get one |
|---|---|---|---|
| OpenAI | OpenAI API key | `gpt-4o-mini` | https://platform.openai.com/api-keys |
| Google Gemini | Google Gemini API key | `gemini-2.0-flash` | https://aistudio.google.com/apikey |
| Anthropic | Anthropic API key | `claude-haiku-4-5` | https://console.anthropic.com/settings/keys |

Your key lives in browser-session memory only. It is never written to disk,
never logged (an active scrubber redacts anything key-shaped from log records),
and never sent anywhere but the provider you picked.

### What it costs you to try

**A full trial of every feature costs well under US$0.50 — realistically about
2–4 cents.**

Retrieval is free: embeddings and reranking run locally on CPU, and the search
index ships prebuilt. Your key pays for two calls per question.

| Step | Tokens | Cost per question |
|---|---|---|
| Routing (classification) | ~250 in / ~20 out | ~$0.00005 |
| Answer generation | ~2,900 in / ~700 out | ~$0.0008 |
| **Total per question** | | **~$0.001** |

Measured on `gpt-4o-mini`; Gemini Flash and Claude Haiku are comparable. Asking
15 questions — enough to exercise both modes, the citations, and the edge cases
— costs roughly **$0.015**. Off-topic questions are turned away by the router
before any generation happens, so they cost about $0.00005.

No action in the app triggers bulk processing on your key. Corpus building and
enrichment are offline, run once by the maintainer.

---

## How it works

```
question
  → route (typed classification: on-topic? names an expert?)
  → retrieve (dense + BM25, fused with reciprocal rank fusion)
  → rerank (local cross-encoder) + per-expert diversity cap
  → prompt (mode-specific, with dynamically selected examples)
  → stream answer + citations
```

The offline pipeline that produces the index is separate and never runs at
question time:

```
fetch → parse → enrich → chunk → build_index
```

### Corpus

31 works, 775 passages, 8 product leaders: Brian Chesky, Casey Winters, Elena
Verna, Gibson Biddle, Julie Zhuo, Marty Cagan, Shreyas Doshi, Teresa Torres.

Two independent public sources: the experts' own blogs (Product Talk,
caseyaccidental.com, via their public RSS feeds) and a public archive of
Lenny's Podcast transcripts.

**Sourcing policy.** Only publicly available material, modest volume per expert,
always cited back to the original. Before fetching any site the pipeline checks
`robots.txt` — including AI-specific opt-outs. One planned source, Marty Cagan's
svpg.com, blocks every major AI crawler (ClaudeBot, GPTBot, Google-Extended and
others) while allowing ordinary ones. That is a deliberate opt-out from exactly
this kind of use, so the site is excluded and Cagan is represented through his
podcast appearance instead. `data_collection/robots.py` enforces this for any
source added later.

**A known data-quality caveat.** Five works in the transcript archive have
unreliable episode metadata — different episodes sharing a video ID, or one
transcript filed under two titles. Expert attribution is still sound, because it
comes from the speaker labels inside the transcript, but episode identity is not.
Those works keep their content and are cited as "*{Expert} on Lenny's Podcast*"
with no episode title and no timestamped link, rather than making a specific
claim the metadata cannot support.

---

## Evaluation

Dataset, scripts, and results are in `evaluation/`. Ground truth comes from
topic tags assigned during enrichment, which the ranker never sees — so the
labels are independent of the signal being measured. Scored per source work over
33 hand-written PM questions.

### Retrieval

| strategy | hit-rate@5 | hit-rate@3 | MRR |
|---|---|---|---|
| dense only | 91% | 67% | 0.593 |
| hybrid (dense + BM25, RRF) | 79% | 79% | 0.712 |
| **hybrid + cross-encoder rerank** (shipped) | **91%** | **82%** | 0.629 |

**SC-006 target — hit-rate@5 ≥ 80% — is met at 91%.**

Read honestly: adding BM25 *lowers* hit@5 against plain dense retrieval while
raising hit@3 and MRR — fusion promotes keyword matches that sometimes displace
a relevant work out of the top five, but ranks its hits higher when it finds
them. Reranking recovers hit@5 and delivers the best hit@3. Since only five or
six passages ever reach the prompt, hit@3 is the number that matters, and that
is where the full pipeline wins. The margin over plain dense search is real but
modest.

### Answer faithfulness

10 council answers judged against the excerpts they were built from:

| dimension | mean (1–5) | min |
|---|---|---|
| grounded in excerpts | 4.90 | 4 |
| correct attribution | 5.00 | 5 |
| admits coverage gaps | 4.90 | 4 |

**First-person impersonation of a named expert: 0/10.** That is the failure this
product most needs to avoid — putting words in a real person's mouth — and the
prompts forbid it explicitly.

Judge and answerer share a model family, so treat these as a regression signal
rather than an independent audit.

### Performance

First token in **3–5 seconds** (SC-007 budget: 5s), after a one-time ~17s model
warmup at boot. Retrieval and reranking together take under a second once warm.

---

## Optional functionalities implemented

Eleven of the course's optional functionalities, against a requirement of five:

1. **Streaming responses** — answers stream token by token.
2. **Domain-specific application** — product-management leadership, not an AI tutor.
3. **Two+ independent data sources** — expert blogs via RSS, plus a GitHub podcast-transcript archive.
4. **Structured JSON in curation** — enrichment uses schema-constrained output whose topic tags drive metadata filtering.
5. **Reranking** — local `bge-reranker-base` cross-encoder over fused candidates.
6. **Hybrid search** — dense embeddings + BM25, combined with reciprocal rank fusion.
7. **Metadata filtering** — expert and content-type filters at the retrieval layer.
8. **Query routing** — typed classification into on-topic / off-topic / expert-mentioned.
9. **Function calling** — routing uses each provider's structured-output mode, so the route is a typed value, not parsed prose.
10. **Dynamic few-shot prompting** — exemplars selected per question by embedding similarity.
11. **RAG evaluation** — dataset, ablation scripts, and results above, all in `evaluation/`.

---

## Rebuilding the corpus

Requires a maintainer key in `.env` (gitignored) for the enrichment step only:

```bash
echo 'DEV_LLM_API_KEY=sk-...' > .env
.venv/bin/python -m data_collection.fetch --all
.venv/bin/python -m data_collection.parse
.venv/bin/python -m data_collection.enrich          # ~$0.012 one-time
.venv/bin/python -m data_collection.chunk
.venv/bin/python -m data_collection.build_index
```

Re-running is idempotent: unchanged sources are skipped, duplicate bodies are
dropped, and enrichment is carried forward rather than overwritten.

`data/curated/` holds the full text of third-party articles and transcripts and
is **not committed** — publishing it would redistribute other people's work in
bulk, which is a different thing from using it for retrieval. The collection
scripts are committed, so the corpus is fully reproducible from this repository.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

155 tests. Provider adapters are contract-tested against a stub, and retrieval
tests run against the real index — none of them need an API key or spend money.

## Layout

| Path | What it is |
|---|---|
| `app.py`, `ui_content.py` | Gradio interface (renderer only, no logic) |
| `rag/` | Runtime: routing, retrieval, reranking, prompts, pipeline |
| `data_collection/` | Offline pipeline: fetch, parse, enrich, chunk, index |
| `evaluation/` | Eval dataset, scripts, and results |
| `specs/001-pdm-leadership-council/` | Spec, plan, contracts, task breakdown |
