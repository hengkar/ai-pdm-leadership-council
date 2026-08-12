<!--
Sync Impact Report
- Version change: (unfilled template) → 1.0.0 (initial adoption)
- Modified principles: none (initial adoption — all five principles newly defined)
- Added sections: Core Principles (I–V), Additional Constraints, Development Workflow, Governance
- Removed sections: none (template placeholders replaced)
- Follow-up TODOs: none — no placeholders deferred
-->

# AI PDM Leadership Council Constitution

## Core Principles

### I. User-Key-Only Spend With a Hard Cost Ceiling

No API key is ever committed to, or shipped with, this repository. The deployed app operates
exclusively on a key the user pastes at runtime (OpenAI, Google Gemini, or Claude), held in
session state only — never persisted, logged, or written to disk. The complete user experience
MUST be tryable for US$0.50 or less, and no user-triggered action may start an expensive
processing job on the user's key. Off-topic queries MUST be short-circuited before meaningful
spend.

*Rationale*: Assignment-mandated and the foundation of user trust; a single leaked key or
runaway pipeline fails the project outright.

### II. Offline Corpus, Free Runtime

All knowledge-base construction — collection, parsing, enrichment, chunking, embedding,
indexing — happens offline, before deployment, using the developer's own key read from an
environment variable. Runtime retrieval (embedding the query, searching, reranking) MUST run
on local, free components; the user's key pays only for routing and answer generation. Index
artifacts are committed so the deployed app boots ready. Collection and curation scripts MUST
live in the repository.

*Rationale*: Keeps Principle I's cost ceiling physically enforceable rather than aspirational,
and makes the corpus reproducible and reviewable.

### III. Attribution Integrity (NON-NEGOTIABLE)

Every retrievable excerpt is attributed to exactly one named expert and one original source
work, and that attribution MUST survive the entire pipeline into the user-visible answer as a
resolvable citation (article link, or timestamped recording link for podcast material).
Answers are framed as grounded in an expert's published thinking — never first-person
impersonation. When the corpus does not cover a question, the app says so instead of
fabricating a perspective or borrowing another expert's material.

*Rationale*: The product's entire value proposition is "real expert thinking, verifiably
sourced"; broken attribution is a broken product and disrespects the real people named.

### IV. Virtual-Environment-Only Python

Every Python and pip invocation — development, scripts, tests, data pipelines, tooling — MUST
run inside the project virtual environment at `.venv/`. The system interpreter is never used
and packages are never installed outside the venv. Non-interactive contexts (scripts, docs,
CI, automation) MUST invoke `.venv/bin/python` and `.venv/bin/pip` explicitly rather than
relying on shell activation. `.venv/` stays out of version control; dependencies are declared
in a committed requirements file so the environment is reproducible.

*Rationale*: Guarantees reproducible builds and identical dependency resolution across
sessions, machines, and the deployment target, and protects the host system from pollution.

### V. Spec-Driven, Assignment-Bound Delivery

Feature work follows the Spec Kit cycle (specify → clarify → plan → tasks → implement). The
feature spec is authoritative for WHAT the product does; the PLAN_*.md documents are
authoritative for HOW — conflicts are resolved in that order and the losing document is
updated, never left stale. Course-assignment obligations are binding requirements, not
aspirations: public Hugging Face Space deployment, a README stating required keys, trial cost,
and implemented optional functionalities (at least 5), and a published evaluation whose
dataset and tooling live in the repository.

*Rationale*: The project is graded against explicit external constraints; treating them as
first-class requirements prevents a functionally impressive but non-certifiable result.

## Additional Constraints

- Python is the implementation language; the app must use retrieval-augmented generation with
  foundation-model LLMs (fine-tuned allowed, self-trained models not).
- English-only for the MVP: corpus, questions, and answers.
- Corpus sourcing stays modest and respectful: dozens of works per expert with full
  attribution, never full-site mirrors; only publicly available material is collected.
- The expert roster consists of real, named product leaders; per-expert material MUST be kept
  separable (metadata) to support both product modes.
- No user accounts and no cross-session persistence; a session is anonymous and self-contained.

## Development Workflow

- Each feature lives in `specs/<NNN>-<name>/` with its spec, plan, tasks, and checklists;
  `.specify/feature.json` points at the active feature.
- Quality gates before a feature is called done: spec checklist passes, evaluation results
  meet the spec's success criteria, and the deployed app is verified end-to-end on the public
  Space with a real user key flow.
- Repository documentation (`CLAUDE.md`, PLAN_*.md, README) is updated in the same change that
  invalidates it; stale guidance is treated as a defect.
- All commands written into scripts, docs, or configuration assume Principle IV
  (`.venv/bin/python`, `.venv/bin/pip`).

## Governance

This constitution supersedes all other project practices. Amendments are made by editing
`.specify/memory/constitution.md` via the `/speckit-constitution` command with an updated
Sync Impact Report, a semantic version bump (MAJOR for principle removals or redefinitions,
MINOR for new or materially expanded principles/sections, PATCH for clarifications), and
propagation of any affected guidance to `CLAUDE.md` and the PLAN documents in the same change.
Every plan, task list, and implementation review MUST verify compliance with Principles I–V;
deviations require an explicit, documented justification in the affected artifact or an
amendment here.

**Version**: 1.0.0 | **Ratified**: 2026-08-12 | **Last Amended**: 2026-08-12
