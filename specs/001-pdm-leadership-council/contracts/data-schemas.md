# Contract: Persisted Data Schemas (`data_collection/schemas.py`)

The file formats that connect the five offline pipeline stages and feed the runtime. Any
stage may be re-run alone; these schemas are the only coupling between stages. Validated with
pydantic v2 — a record failing validation aborts the stage with a report, it is never written.

Authoritative field tables live in [data-model.md](../data-model.md); this contract fixes the
serialization and compatibility rules.

## Files

| Artifact | Format | Producer → Consumer |
|---|---|---|
| `data/raw/<expert>/…` + `manifest.json` | source-native + JSON | fetch → parse (gitignored) |
| `data/curated/<expert>/<work>.json` | one SourceWork per file, UTF-8, 2-space indent | parse → enrich → chunk (committed) |
| `data/chunks.jsonl` | one Chunk per line | chunk → build_index (committed) |
| `data/index/chroma/` | Chroma persistent collection `council` | build_index → `rag/retrieve` (committed) |
| `data/index/bm25.pkl` | pickle: `{"tokenized": [...], "chunk_ids": [...]}` | build_index → `rag/retrieve` (committed) |
| `evaluation/dataset.jsonl` | one EvalCase per line | hand-written → eval scripts (committed) |

## Compatibility rules

1. **Additive evolution only**: new optional fields are fine; renaming/removing a field or
   changing its meaning requires re-running every downstream stage and bumping
   `SCHEMA_VERSION` (a module constant written into `chunks.jsonl` header line and checked by
   `build_index.py` and `rag/retrieve.py` at load).
2. **Attribution is non-optional**: `expert`, `doc_id`, `url` can never become nullable
   (Constitution III). `timestamp_s` is required exactly when `content_type ==
   podcast_transcript`.
3. **Chroma metadata mirror**: every Chunk field except `text` is stored as Chroma metadata;
   `rag/` MUST reconstruct citations from index metadata alone (no reads of `data/curated/` at
   runtime).
4. **Manifest idempotency**: fetch skips URLs whose content hash is unchanged in
   `manifest.json`; `--force` refetches.
5. **sources.yaml is the only roster**: code never hardcodes expert names; UI roster, router
   validation, and eval slicing all read the registry (via a build-time export into the index
   metadata).
