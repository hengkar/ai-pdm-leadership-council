"""Stage 5 — build the search indexes the app boots from.

Produces two artifacts, both committed so the deployed Space starts ready and
never indexes anything at a user's expense (constitution Principle II):

* a Chroma collection of dense vectors with full chunk metadata, and
* a BM25 index for exact-term recall on PM jargon a dense model may blur.

Embedding runs locally on CPU, so building and querying cost nothing.

    .venv/bin/python -m data_collection.build_index
"""

from __future__ import annotations

import argparse
import json
import pickle
import shutil
from collections import Counter

from data_collection.chunk import embedding_text
from data_collection.schemas import SCHEMA_VERSION, Chunk
from rag.config import (
    BM25_PATH,
    CHROMA_COLLECTION,
    CHROMA_DIR,
    CHUNKS_PATH,
    EMBEDDING_MODEL,
    EMBEDDINGS_PATH,
    INDEX_DIR,
)

EMBED_BATCH = 64


def load_chunks() -> list[Chunk]:
    """Read chunks.jsonl, refusing an artifact built by a different schema."""
    lines = CHUNKS_PATH.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise SystemExit("chunks.jsonl is empty — run data_collection.chunk first")

    header = json.loads(lines[0])
    if header.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(
            f"chunks.jsonl was built with schema {header.get('schema_version')} but this "
            f"code expects {SCHEMA_VERSION}. Re-run parse and chunk."
        )
    return [Chunk.model_validate_json(line) for line in lines[1:] if line.strip()]


def _metadata(chunk: Chunk) -> dict[str, str | int | bool]:
    """Flatten a chunk for Chroma, which stores scalars only.

    Everything a citation needs lives here, because the runtime builds citations
    from index metadata alone and never reads the curated corpus.
    """
    meta: dict[str, str | int | bool] = {
        "doc_id": chunk.doc_id,
        "expert": chunk.expert,
        "title": chunk.title,
        "url": str(chunk.url),
        "content_type": chunk.content_type.value,
        "episode_verified": chunk.episode_verified,
        # Chroma rejects lists; a delimited string keeps topics displayable and
        # still lets a caller post-filter on membership.
        "topics": ",".join(chunk.topics),
    }
    if chunk.date:
        meta["date"] = chunk.date.isoformat()
    if chunk.heading_path:
        meta["heading_path"] = chunk.heading_path
    if chunk.timestamp_s is not None:
        meta["timestamp_s"] = chunk.timestamp_s
    if chunk.youtube_url:
        meta["youtube_url"] = str(chunk.youtube_url)
    return meta


def build(reset: bool = True) -> None:
    import chromadb
    from rank_bm25 import BM25Okapi
    from sentence_transformers import SentenceTransformer

    chunks = load_chunks()
    print(f"Loaded {len(chunks):,} chunks (schema v{SCHEMA_VERSION})")

    if reset and CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Embedding with {EMBEDDING_MODEL} (CPU, local)...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    texts = [embedding_text(chunk) for chunk in chunks]
    vectors = model.encode(
        texts,
        batch_size=EMBED_BATCH,
        show_progress_bar=True,
        normalize_embeddings=True,  # cosine similarity via dot product
    ).tolist()

    # Committed artifact: vectors only. The runtime rebuilds the collection
    # from these plus chunks.jsonl, so no multi-megabyte DB is shipped.
    import numpy as np

    np.save(EMBEDDINGS_PATH, np.asarray(vectors, dtype=np.float32))
    print(f"embeddings -> {EMBEDDINGS_PATH.name} "
          f"({EMBEDDINGS_PATH.stat().st_size / 1e6:.1f} MB)")

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine", "schema_version": SCHEMA_VERSION},
    )
    for start in range(0, len(chunks), 500):  # Chroma prefers bounded batches
        window = slice(start, start + 500)
        collection.add(
            ids=[c.chunk_id for c in chunks[window]],
            embeddings=vectors[window],
            documents=[c.text for c in chunks[window]],
            metadatas=[_metadata(c) for c in chunks[window]],
        )

    print("Building BM25 index...")
    tokenized = [text.lower().split() for text in texts]
    BM25_PATH.write_bytes(
        pickle.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "chunk_ids": [c.chunk_id for c in chunks],
                "tokenized": tokenized,
                "bm25": BM25Okapi(tokenized),
            }
        )
    )

    _report(chunks, collection.count())


def _report(chunks: list[Chunk], indexed: int) -> None:
    """Print the corpus summary that goes into the README."""
    by_expert = Counter(c.expert for c in chunks)
    by_type = Counter(c.content_type.value for c in chunks)
    by_topic = Counter(topic for c in chunks for topic in c.topics)
    unverified = sum(1 for c in chunks if not c.episode_verified)

    print(f"\nIndexed {indexed:,} chunks into '{CHROMA_COLLECTION}'")
    print("\nChunks per expert:")
    for expert, count in by_expert.most_common():
        share = 100 * count / len(chunks)
        print(f"  {expert:16} {count:>4}  ({share:4.1f}%)")

    print("\nChunks per source type:")
    for kind, count in by_type.most_common():
        print(f"  {kind:20} {count:>4}")

    print(f"\nTop topics: {', '.join(f'{t} ({n})' for t, n in by_topic.most_common(8))}")
    if unverified:
        print(f"\n{unverified} chunk(s) from episodes with unverified metadata "
              "(cited without episode title or deep link)")

    thin = [e for e, n in by_expert.items() if n < 20]
    if thin:
        print(
            f"\nNote: {', '.join(thin)} have under 20 chunks each. Council mode's "
            "per-expert cap protects them, but unfiltered retrieval will favour "
            "the better-represented experts."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="append instead of rebuilding")
    args = parser.parse_args(argv)
    build(reset=not args.keep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
