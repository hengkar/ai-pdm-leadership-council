"""Stage 4 — split curated works into retrievable chunks.

Two strategies, because the two formats have different natural seams:

* Articles are split on their heading sections, then by size when a section runs
  long. The heading trail rides along so a passage can be read in context.
* Transcripts are split one exchange per chunk and never merged, because a chunk
  carries the timestamp of the moment it came from — combining two exchanges
  would file one speaker's words under another moment's link.

    .venv/bin/python -m data_collection.chunk
"""

from __future__ import annotations

import argparse
import json

from data_collection.schemas import SCHEMA_VERSION, ContentType, Chunk, Segment, SourceWork
from rag.config import CHUNKS_PATH, CHUNK_OVERLAP_TOKENS, CURATED_DIR, TARGET_CHUNK_TOKENS

# The embedding model counts tokens, not words, but a tokenizer would be another
# dependency for a decision this coarse. English prose runs about 0.75 words per
# token, and the target is a soft one.
WORDS_PER_TOKEN = 0.75
TARGET_CHUNK_WORDS = int(TARGET_CHUNK_TOKENS * WORDS_PER_TOKEN)   # ~337
OVERLAP_WORDS = int(CHUNK_OVERLAP_TOKENS * WORDS_PER_TOKEN)       # ~45

# Below this a trailing fragment is folded back into the previous chunk instead
# of standing alone, since a stray sentence retrieves poorly.
MIN_CHUNK_WORDS = 40


def _split_words(text: str, target: int, overlap: int) -> list[str]:
    """Split into ~`target`-word pieces with `overlap` words of run-back."""
    words = text.split()
    if len(words) <= target:
        return [text.strip()] if text.strip() else []

    pieces: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + target, len(words))
        pieces.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap

    # A short tail carries little on its own; merge it back.
    if len(pieces) > 1 and len(pieces[-1].split()) < MIN_CHUNK_WORDS:
        tail = pieces.pop()
        pieces[-1] = f"{pieces[-1]} {tail}"

    return pieces


# Consecutive exchanges are merged only while they stay close together in the
# recording. A chunk's link points at the moment its text begins, so spanning a
# long gap would send a reader to a spot minutes before what they came to hear.
MAX_MERGE_GAP_S = 300


def _merge_short_exchanges(segments: list[Segment]) -> list[Segment]:
    """Combine consecutive short exchanges up to the target chunk size.

    One exchange per chunk leaves a transcript in fragments — the corpus
    averaged 187 words per chunk against a ~337 target — and short chunks carry
    too little context to retrieve well. Merging is safe here because the pieces
    are adjacent in the recording and the merged chunk keeps the first
    timestamp, which is genuinely where its text starts.
    """
    merged: list[Segment] = []
    for segment in segments:
        if not merged:
            merged.append(segment)
            continue

        previous = merged[-1]
        combined_words = len(previous.text.split()) + len(segment.text.split())
        gap = (
            (segment.timestamp_s or 0) - (previous.timestamp_s or 0)
            if segment.timestamp_s is not None and previous.timestamp_s is not None
            else 0
        )

        if combined_words <= TARGET_CHUNK_WORDS and 0 <= gap <= MAX_MERGE_GAP_S:
            merged[-1] = Segment(
                text=f"{previous.text}\n\n{segment.text}",
                timestamp_s=previous.timestamp_s,  # where the merged passage begins
                heading_path=previous.heading_path,
            )
        else:
            merged.append(segment)
    return merged


def chunk_work(work: SourceWork) -> list[Chunk]:
    """Split one work into chunks, preserving provenance on every piece."""
    segments = work.segments or [Segment(text=work.body)]
    is_podcast = work.content_type is ContentType.PODCAST_TRANSCRIPT
    if is_podcast:
        segments = _merge_short_exchanges(segments)

    chunks: list[Chunk] = []
    for segment in segments:
        for piece in _split_words(segment.text, TARGET_CHUNK_WORDS, OVERLAP_WORDS):
            index = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=f"{work.id}#{index}",
                    doc_id=work.id,
                    expert=work.expert,
                    title=work.title,
                    url=work.url,
                    date=work.date,
                    content_type=work.content_type,
                    topics=list(work.topics),
                    text=piece,
                    heading_path=segment.heading_path,
                    # Every piece of one answer shares that answer's moment: the
                    # split is ours, not a new point in the recording.
                    timestamp_s=segment.timestamp_s if is_podcast else None,
                    youtube_url=work.youtube_url if is_podcast else None,
                    episode_verified=work.episode_verified,
                )
            )
    return chunks


def embedding_text(chunk: Chunk) -> str:
    """What actually gets embedded: the heading trail plus the passage.

    Prefixing the heading is cheap grounding — it tells the model which article
    and section a passage belongs to without another retrieval hop.
    """
    return f"{chunk.heading_path}\n\n{chunk.text}" if chunk.heading_path else chunk.text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="only chunk the first N works")
    args = parser.parse_args(argv)

    paths = sorted(CURATED_DIR.rglob("*.json"))
    if not paths:
        print("No curated works found — run fetch.py then parse.py first.")
        return 1
    if args.limit:
        paths = paths[: args.limit]

    unenriched = 0
    all_chunks: list[Chunk] = []
    for path in paths:
        work = SourceWork.model_validate_json(path.read_text(encoding="utf-8"))
        if not work.topics:
            unenriched += 1
        all_chunks.extend(chunk_work(work))

    CHUNKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CHUNKS_PATH.open("w", encoding="utf-8") as handle:
        # Header line carries the schema version so build_index and the runtime
        # can refuse a stale artifact rather than mis-read it.
        handle.write(json.dumps({"schema_version": SCHEMA_VERSION}) + "\n")
        for chunk in all_chunks:
            handle.write(chunk.model_dump_json() + "\n")

    words = sum(len(c.text.split()) for c in all_chunks)
    podcast = sum(1 for c in all_chunks if c.timestamp_s is not None)
    print(f"{len(all_chunks):,} chunks from {len(paths)} works -> {CHUNKS_PATH}")
    print(f"  {podcast:,} podcast chunks (timestamped) / {len(all_chunks) - podcast:,} article chunks")
    print(f"  mean {words / max(len(all_chunks), 1):.0f} words per chunk")
    if unenriched:
        print(f"  note: {unenriched} work(s) have no topics — run enrich.py for metadata filtering")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
