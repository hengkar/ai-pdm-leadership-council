# Podcast Transcripts Plan — Lenny's Podcast via ChatPRD Archive

How to use https://github.com/ChatPRD/lennys-podcast-transcripts as a knowledge source.
Companion to `PLAN_DATA_PIPELINE.md`; this source slots into the same five-stage pipeline.

## What the repo contains (verified 2026-08-12)

- **303 episode transcripts**, one folder per guest: `episodes/<guest-slug>/transcript.md`
- Each file has **YAML frontmatter** (guest, title, youtube_url, video_id, publish_date,
  description, duration, keywords) followed by a **speaker-labeled, timestamped transcript**:
  `Shreyas Doshi (00:14:32): ...`
- ~83 KB per transcript, ~24 MB total. There's also an AI-generated `index/` of topic files
  (we don't need it — we build our own enrichment).

## Why this is a big deal for the project

**Every expert in the original product spec has episodes** — including the ones the stage-0
audit dropped as unfetchable:

| Expert | Episodes in repo | Previously |
|---|---|---|
| Shreyas Doshi | 2 | dropped (Twitter-bound) |
| Brian Chesky | 1 | dropped |
| Elena Verna | 4 | candidate only |
| Julie Zhuo | 2 | candidate only |
| Marty Cagan | 2 | blog only |
| Casey Winters | 2 | blog only |
| Gibson Biddle | 1 | Substack/PDF only |
| Teresa Torres | 1 | blog only |

That's ~15 long-form interviews (~1.3 MB of text) restoring the full council roster, and
long-form interview answers are exactly the "how this leader thinks" content the product needs.

## Ingestion plan

### Fetch — new `github_repo` adapter (stage 1)

- Shallow-clone the repo **pinned to a commit SHA** in `sources.yaml` (reproducible corpus,
  no scraping, one HTTP operation).
- **Selection policy: council experts only, not all 303 episodes.** The app is an expert
  council, not a podcast search engine — 300 one-off guests would dilute retrieval and blow up
  enrichment cost. `sources.yaml` maps guest slugs → canonical expert names:

```yaml
- type: github_repo
  repo: ChatPRD/lennys-podcast-transcripts
  ref: <pinned-sha>
  episodes:
    shreyas-doshi: Shreyas Doshi
    shreyas-doshi-live: Shreyas Doshi
    brian-chesky: Brian Chesky
    elena-verna: Elena Verna
    elena-verna-20: Elena Verna     # repeat appearances share one canonical name
    # ... etc
```

Adding a future guest to the council = one YAML line.

### Parse — new transcript parser (stage 2)

- `python-frontmatter` for the YAML header; regex `^(.+?) \((\d{2}:\d{2}:\d{2})\):` for
  speaker turns.
- **Attribution is the critical rule**: chunks are attributed to the **guest** (`expert:
  Shreyas Doshi`), never to the interviewer. Lenny's question is kept as a context prefix on
  the answer chunk (questions make answers retrievable), but the thinking belongs to the guest.
- Strip: sponsor reads, intro/outro boilerplate, `[inaudible]` markers.
- Known data quirks to handle:
  - Duplicate-ish dirs (`casey-winters` vs `casey-winters_`) → dedupe by content hash
  - Suffixed dirs (`elena-verna-20`, `-30`, `-40`) are repeat appearances → same canonical expert
  - Frontmatter `duration` is unreliable (one file claims 3:50 but holds an 87 KB transcript)
    → trust word count, not frontmatter, for quality gates
- Output: same curated-JSON schema as articles, with `content_type: "podcast_transcript"` and
  extra fields `video_id`, `youtube_url`.

### Enrich (stage 3) — unchanged

Same LLM pass as articles: controlled-vocabulary topic tags + summary. The repo's frontmatter
`keywords` are generic (same list appears on many episodes) — ignore them, tag from the
transcript text. ~15 long transcripts ≈ a few dollars one-time on the dev key; enrich from the
episode's first ~8k tokens + description rather than the full 80 KB.

### Chunk (stage 4) — transcript-aware strategy

Articles chunk by headings; transcripts have none. Instead:

- Chunk = **Q&A unit**: interviewer question + the guest's answer turns, split at ~450 tokens
  with overlap when an answer runs long. Never merge across question boundaries.
- Each chunk carries the **start timestamp**, so citations can deep-link:
  `youtube_url + "&t=" + seconds` — "watch Shreyas say this" is a genuinely better citation
  than a page link.
- Metadata: everything articles get (expert, title, url, date, topics) plus `content_type:
  podcast_transcript` and `timestamp`.

### Index (stage 5) — unchanged

Same Chroma + BM25 build. Expected addition: ~1,500–2,500 chunks from the 15 episodes
(comparable to the entire blog corpus — transcripts are long).

## Runtime impact (`PLAN_QUERY_FLOW.md`)

- **Council roster restored** to the full product-spec list — Shreyas, Chesky, Elena, and
  Julie become selectable in "Ask an Expert" mode.
- `content_type` becomes a second **metadata filtering** dimension (blog vs podcast), and the
  council-mode diversity cap now also prevents one 80 KB transcript from dominating retrieval.
- Sources panel: podcast chunks render as `🎙 Shreyas Doshi on Lenny's Podcast (14:32) → link`
  with the timestamped YouTube deep-link.
- Prompt note: transcript chunks are conversational ("you know, I think...") while blog chunks
  are polished prose — the system prompt should tell the model to synthesize, not quote
  verbatim, so spoken-word filler doesn't leak into answers.

## Assignment impact

- Strengthens **evidence of 2+ data sources beyond the course** (blogs + Substack + GitHub
  transcript archive — clearly independent source types).
- PDF parsing (Biddle decks) drops from "needed for buffer" to pure stretch.
- Attribution/licensing: transcripts of a public podcast, archived in a public repo explicitly
  organized "for use with AI assistants"; we ingest a subset, always cite the episode and link
  to the original video. Fine for a personal course project.

## Build order within the pipeline

1. Add the `github_repo` adapter + slug→expert map to `sources.yaml`
2. Transcript parser with speaker-turn attribution (test on `shreyas-doshi` first — two
   episodes, high-value guest)
3. Q&A chunker with timestamps
4. Re-run enrich + index; spot-check that "Ask Shreyas" retrieval returns podcast chunks with
   working YouTube deep-links
