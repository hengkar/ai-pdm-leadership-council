# Data Model: AI PDM Leadership Council

Maps the spec's Key Entities to concrete schemas. All persisted schemas are pydantic v2 models
in `data_collection/schemas.py`; runtime-only structures live in `rag/`. Attribution fields are
**required everywhere** — a record without `expert` + source linkage cannot be constructed
(Constitution III enforced at the type level).

## Offline / persisted entities

### Expert (registry entry in `data_collection/sources.yaml`)

| Field | Type | Rules |
|---|---|---|
| `name` | str | Canonical display name, e.g. "Shreyas Doshi"; unique |
| `slug` | str | kebab-case id, e.g. `shreyas-doshi`; unique, stable |
| `sources` | list[SourceConfig] | ≥1; adapter type + endpoint/slug map per source |

`SourceConfig.type ∈ {wordpress, substack, pdf, github_repo}`; `github_repo` entries carry
`repo`, `ref` (pinned SHA), and an `episodes` slug→expert map (repeat appearances map to one
canonical expert).

### SourceWork (one JSON file in `data/curated/<expert-slug>/`)

| Field | Type | Rules |
|---|---|---|
| `id` | str | `<expert-slug>--<work-slug>`; unique corpus-wide |
| `expert` | str | Canonical expert name; must exist in registry |
| `title` | str | non-empty |
| `url` | HttpUrl | original public location |
| `date` | date \| None | publication date if known |
| `content_type` | enum | `blog \| newsletter \| pdf_deck \| podcast_transcript` |
| `word_count` | int | ≥300 (quality gate) |
| `body` | str | cleaned text; boilerplate/sponsor content stripped |
| `video_id`, `youtube_url` | str \| None | required iff `content_type == podcast_transcript` |
| `topics` | list[str] | 2–5 tags from controlled vocabulary (added by enrich stage) |
| `summary` | str | 2-sentence abstract (added by enrich stage) |

Dedup rule: content-hash across all works; duplicates dropped at parse time.

### Chunk (one line in `data/chunks.jsonl`)

| Field | Type | Rules |
|---|---|---|
| `chunk_id` | str | `<doc_id>#<seq>`; unique |
| `doc_id` | str | FK → SourceWork.id |
| `expert` | str | denormalized from SourceWork (never derived at query time) |
| `title`, `url`, `date`, `content_type`, `topics` | — | denormalized from SourceWork |
| `heading_path` | str \| None | e.g. "Product vs Feature Teams > Role of the PM" (articles) |
| `timestamp_s` | int \| None | start second; required iff podcast chunk (deep-link source) |
| `text` | str | ~450 tokens target, ~60 overlap; embedded as `heading_path + text` |

Invariants: article chunks never cross work boundaries; transcript chunks never cross
question boundaries; transcript chunk text = interviewer question (context) + guest answer,
attributed to the guest.

### Indexes (`data/index/`)

- **Chroma collection** `council`: vector per chunk (`bge-small-en-v1.5`, cosine), full chunk
  metadata for `where` filtering on `expert`, `content_type`, `topics`.
- **BM25 pickle**: tokenized chunk texts + parallel `chunk_id` list; filtered post-hoc for
  expert mode.
- Build stats (chunks per expert / per topic) printed by `build_index.py` and pasted into the
  README data section.

### EvalCase (one line in `evaluation/dataset.jsonl`)

| Field | Type | Rules |
|---|---|---|
| `question` | str | realistic PM situational question |
| `mode` | enum | `council \| expert` |
| `expert` | str \| None | required iff mode == expert |
| `expected_doc_ids` | list[str] | ≥1; ground-truth SourceWork ids that answer it |
| `tags` | list[str] | topic slice for reporting |

## Runtime-only entities (never persisted)

### SessionState (Gradio `gr.State`)

| Field | Type | Rules |
|---|---|---|
| `provider` | enum | `openai \| gemini \| claude` |
| `api_key` | str | session memory only; excluded from all `repr`/logs; dies with session |
| `key_validated` | bool | set by first-use ping |
| `history` | list[Message] | in-session chat turns only |

### RosterEntry (derived, `rag/roster.py`)

| Field | Type | Rules |
|---|---|---|
| `name` | str | canonical expert name |
| `slug` | str | kebab id (avatar filename lookup) |
| `work_count`, `chunk_count` | int | >0 — an expert with no indexed material is never shown |
| `content_types` | set[enum] | which source kinds back this expert (sidebar hint: 📄 / 🎙) |

Built once at startup by scanning committed index metadata — never from `sources.yaml` or
`data/curated/` at runtime (Constitution II). This is the single roster used by the sidebar,
the expert-mode selector, and router expert-name validation.

### ExamplePrompt (static, `ui_content.py`)

| Field | Type | Rules |
|---|---|---|
| `title` | str | short label, e.g. "Roadmap pushback" |
| `situation` | str | the full question text submitted verbatim on click (FR-021) |

~4 entries, hand-written to reflect real PM situations the corpus covers. Static text only —
displaying them costs nothing (Principle I).

### Route (router output — provider structured output)

`kind ∈ {pm_question, off_topic, expert_mentioned}`; `expert: str | None` (validated against
roster; unknown names fall back to `pm_question`).

### RetrievalResult

`chunk` (Chunk), `dense_rank`, `sparse_rank`, `rrf_score`, `rerank_score` — carried through so
the eval ablations and the sources panel use identical data.

### Answer / Citation (assembled for UI)

- Answer: streamed markdown; council mode sections = Situation → Perspective (per expert) →
  Recommended Actions.
- Citation (from chunk metadata only): `expert`, `title`, `url`, and for podcast chunks
  `youtube_url + "&t=" + timestamp_s`. Rendered as 📄 (written) / 🎙 (podcast). A citation not
  backed by a retrieved chunk cannot exist.

## Relationships

```
Expert 1──* SourceWork 1──* Chunk *──1 (chroma vector + bm25 row)
EvalCase *──* SourceWork (expected_doc_ids)
Answer *──* Chunk (via citations)
```

## State transitions

SourceWork: `raw (fetched)` → `curated (parsed+validated)` → `enriched (topics+summary)` →
`chunked` → `indexed`. Each transition is one idempotent pipeline stage; re-running a stage
overwrites only its own outputs.
