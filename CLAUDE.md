# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

Planning complete, no code yet. The repository contains requirements and an agreed plan set:

- `requirement_pdm_council.txt` — the product concept
- `requirement_assignment.txt` — the course assignment constraints the final app must satisfy
- `PLAN.md` — the overview build plan; where it disagrees with a detailed plan, the detailed plan wins
- `PLAN_DATA_PIPELINE.md` — offline ingestion design (fetch → parse → enrich → chunk → index)
- `PLAN_TRANSCRIPTS.md` — Lenny's Podcast transcript archive (github.com/ChatPRD/lennys-podcast-transcripts) as a knowledge source
- `PLAN_QUERY_FLOW.md` — runtime design (routing → hybrid retrieval → rerank → prompt → streamed answer)

Implementation should follow the plan set; update the plans when decisions change so they stay authoritative.

## Python Environment

All Python MUST run inside the project virtual environment at `.venv/` — never the system
interpreter, and never `pip install` outside it.

```bash
python3 -m venv .venv                # create once
source .venv/bin/activate            # or invoke directly:
.venv/bin/python script.py
.venv/bin/pip install -r requirements.txt
```

When adding scripts, docs, or Space configuration, write commands assuming the venv
(`.venv/bin/python` in non-interactive contexts). Keep `.venv/` out of version control.

## Spec-Kit Workflow

The repo is initialized with GitHub spec-kit (v0.16.2, `.specify/`), integrated with Claude Code
as `speckit-*` skills in `.claude/skills/`. Feature work is expected to go through the SDD cycle:

1. `/speckit-specify` — write the feature spec (use the PLAN_*.md docs as source material)
2. `/speckit-clarify` — resolve open questions in the spec
3. `/speckit-plan` — implementation plan
4. `/speckit-tasks` — task breakdown
5. `/speckit-implement` — execute

Feature numbering is sequential; helper scripts live in `.specify/scripts/bash/`.

The project constitution (`.specify/memory/constitution.md`, v1.0.0) is ratified and binding:
user-key-only spend with the $0.50 ceiling, offline-only corpus construction, attribution
integrity, virtual-environment-only Python, and spec-driven assignment-bound delivery. Plans,
tasks, and reviews must verify compliance; amend it via `/speckit-constitution`.

## What This Project Is

**AI PDM Leadership Council**: a RAG application (final project for an LLM course) that helps junior/mid-level Product Managers by retrieving and synthesizing thinking from experienced product leaders (Lenny Rachitsky, Shreyas Doshi, Julie Zhuo, Marty Cagan, Teresa Torres, etc.).

Two product modes:
1. **Ask an Expert** — user selects a specific expert (e.g., "Ask Shreyas") and gets that expert's perspective.
2. **Ask the Product Council** — multiple expert perspectives are retrieved and compared side by side.

Responses follow a structured format: restate the situation, present multiple perspectives, then give recommended actions.

## Hard Constraints (required for course certification)

- RAG project written in **Python**, using at least one foundation-model LLM (local or API). Gradio UI is the suggested starting point but not required.
- Must be deployed on a **public Hugging Face Space**.
- **No API keys in the repo.** The UI must let the user paste their own API key for OpenAI, Google Gemini, or Claude.
- No costly pipelines run on the user's key — RAG answers on the order of ~10k tokens are fine; heavy on-the-fly processing is not. The full app must be tryable for **≤ $0.50** in API costs.
- Data collection/curation scripts must be included in the repo.
- README must include: project explanation, the list of API keys the user needs, a cost estimate, and the list of implemented optional functionalities.
- Must implement **at least 5** of the assignment's optional functionalities (full list in `requirement_assignment.txt`), e.g. streaming responses, reranking, hybrid search, metadata filtering, query routing, dynamic few-shot prompting, RAG evaluation (with dataset + scripts in repo), function calling, prompt caching, speech I/O.

Note: "domain other than an AI tutor" is one of the optional functionalities this project inherently satisfies (product management domain), and metadata filtering maps naturally onto the per-expert "Ask an Expert" mode.

## Architecture Direction (from requirements)

The knowledge base is built from content by named product leaders, so per-document metadata (expert name, source) is central: "Ask an Expert" is a metadata-filtered retrieval; "Ask the Council" retrieves across experts and groups results by expert for comparison. Keep expert attribution intact through the entire pipeline (collection → chunking → retrieval → generation).
