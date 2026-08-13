"""Hybrid retrieval over the committed index.

Dense search finds passages that mean the same thing as the question; BM25
finds the ones that use the same words. Product management runs on specific
vocabulary — "north star metric", "opportunity solution tree", "DHM" — that an
embedding will happily blur into something adjacent, so both run and their
rankings are fused.

Everything here is local and free. The user's key pays only for routing and
generation (constitution Principle I).
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from rag.config import (
    BM25_PATH,
    CHROMA_COLLECTION,
    CHROMA_DIR,
    CHUNKS_PATH,
    DENSE_TOP_K,
    EMBEDDING_MODEL,
    EMBEDDINGS_PATH,
    RRF_K,
    SPARSE_TOP_K,
)

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """One candidate passage, carrying everything a citation needs.

    Ranks are kept so the evaluation harness can measure each retrieval stage
    separately, and so the reranker's effect is visible rather than implied.
    """

    chunk_id: str
    text: str
    metadata: dict[str, Any]
    dense_rank: int | None = None
    sparse_rank: int | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None

    @property
    def expert(self) -> str:
        return self.metadata["expert"]

    @property
    def doc_id(self) -> str:
        return self.metadata["doc_id"]


def _load_chunk_records() -> list[dict[str, Any]]:
    """Read chunks.jsonl, skipping the schema-version header line."""
    lines = CHUNKS_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[1:] if line.strip()]


def _flatten(chunk: dict[str, Any]) -> dict[str, Any]:
    """Chunk record -> Chroma metadata (scalars only).

    Deliberately mirrors `data_collection.build_index._metadata` rather than
    importing it: the runtime package must not depend on the offline pipeline
    (Principle II). The duplication is small and the contract is pinned by
    tests that read real index metadata.
    """
    meta: dict[str, Any] = {
        "doc_id": chunk["doc_id"],
        "expert": chunk["expert"],
        "title": chunk["title"],
        "url": chunk["url"],
        "content_type": chunk["content_type"],
        "episode_verified": bool(chunk.get("episode_verified", True)),
        "topics": ",".join(chunk.get("topics") or []),
    }
    for key in ("date", "heading_path", "timestamp_s", "youtube_url"):
        if chunk.get(key) is not None:
            meta[key] = chunk[key]
    return meta


class _Index:
    """Loaded once per process and shared across sessions.

    The models and indexes are read-only, so sharing them is safe and avoids
    paying model-load time on every question.
    """

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self.embedder = SentenceTransformer(EMBEDDING_MODEL)
        self.collection = self._build_collection()

        payload = pickle.loads(BM25_PATH.read_bytes())
        self.bm25 = payload["bm25"]
        self.bm25_ids: list[str] = payload["chunk_ids"]

        # One pass over the index gives BM25 the metadata it otherwise lacks:
        # its pickle holds only tokens and ids, so without this the sparse side
        # could not honour an expert filter or build a citation.
        records = self.collection.get(include=["metadatas", "documents"])
        self.metadata: dict[str, dict[str, Any]] = dict(
            zip(records["ids"], records["metadatas"])
        )
        self.documents: dict[str, str] = dict(zip(records["ids"], records["documents"]))
        logger.info("index loaded: %d chunks", len(self.metadata))

    def _build_collection(self):
        """Assemble the vector collection in memory from committed artifacts.

        The shipped artifacts are `embeddings.npy` plus `chunks.jsonl`, and the
        collection is reconstructed from them at boot. A persistent Chroma
        database held the same information in 12.9 MB — mostly SQLite overhead,
        since the text and metadata are already in chunks.jsonl — and the Hub
        requires Git LFS for anything past 10 MB. Rebuilding costs a fraction of
        a second at this corpus size and keeps the deployment a plain repo.

        Falls back to a persistent store if the vectors are absent, so an older
        local build still works.
        """
        import chromadb

        if not EMBEDDINGS_PATH.exists():
            logger.warning("no %s — falling back to the persistent store", EMBEDDINGS_PATH.name)
            return chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(
                CHROMA_COLLECTION
            )

        import numpy as np

        vectors = np.load(EMBEDDINGS_PATH)
        chunks = _load_chunk_records()
        if len(chunks) != len(vectors):
            raise RuntimeError(
                f"{len(vectors)} embeddings but {len(chunks)} chunks — "
                "artifacts are out of step; re-run data_collection.build_index"
            )

        collection = chromadb.EphemeralClient().get_or_create_collection(
            name=CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"}
        )
        for start in range(0, len(chunks), 500):
            window = slice(start, start + 500)
            collection.add(
                ids=[c["chunk_id"] for c in chunks[window]],
                embeddings=vectors[window].tolist(),
                documents=[c["text"] for c in chunks[window]],
                metadatas=[_flatten(c) for c in chunks[window]],
            )
        return collection


@lru_cache(maxsize=1)
def _index() -> _Index:
    return _Index()


def _passes(meta: dict[str, Any], expert: str | None, content_type: str | None) -> bool:
    if expert and meta.get("expert") != expert:
        return False
    if content_type and meta.get("content_type") != content_type:
        return False
    return True


def search(
    query: str,
    expert: str | None = None,
    content_type: str | None = None,
    dense_k: int = DENSE_TOP_K,
    sparse_k: int = SPARSE_TOP_K,
) -> list[RetrievalResult]:
    """Return fused candidates, best first.

    `expert` is what makes "Ask an Expert" a retrieval-level guarantee rather
    than a prompt-level request: filtered here, the model never sees another
    expert's words and so cannot attribute them (FR-003, SC-005).
    """
    index = _index()
    query_vector = index.embedder.encode([query], normalize_embeddings=True).tolist()

    # --- dense ---
    where = {"expert": expert} if expert else None
    if content_type:
        clause = {"content_type": content_type}
        where = {"$and": [where, clause]} if where else clause

    dense = index.collection.query(
        query_embeddings=query_vector, n_results=dense_k, where=where
    )
    dense_ids = dense["ids"][0]

    # --- sparse ---
    scores = index.bm25.get_scores(query.lower().split())
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    sparse_ids: list[str] = []
    for position in ranked:
        chunk_id = index.bm25_ids[position]
        if scores[position] <= 0:
            break
        if _passes(index.metadata.get(chunk_id, {}), expert, content_type):
            sparse_ids.append(chunk_id)
        if len(sparse_ids) >= sparse_k:
            break

    return _fuse(dense_ids, sparse_ids, index)


def _fuse(dense_ids: list[str], sparse_ids: list[str], index: _Index) -> list[RetrievalResult]:
    """Reciprocal rank fusion.

    RRF combines rankings rather than scores, which matters because cosine
    similarity and BM25 are not on a common scale and normalising them would
    mean choosing an arbitrary weighting.
    """
    dense_rank = {cid: position for position, cid in enumerate(dense_ids)}
    sparse_rank = {cid: position for position, cid in enumerate(sparse_ids)}

    results: dict[str, RetrievalResult] = {}
    for chunk_id in set(dense_ids) | set(sparse_ids):
        score = 0.0
        if chunk_id in dense_rank:
            score += 1.0 / (RRF_K + dense_rank[chunk_id] + 1)
        if chunk_id in sparse_rank:
            score += 1.0 / (RRF_K + sparse_rank[chunk_id] + 1)

        results[chunk_id] = RetrievalResult(
            chunk_id=chunk_id,
            text=index.documents.get(chunk_id, ""),
            metadata=index.metadata.get(chunk_id, {}),
            dense_rank=dense_rank.get(chunk_id),
            sparse_rank=sparse_rank.get(chunk_id),
            rrf_score=score,
        )

    return sorted(results.values(), key=lambda r: r.rrf_score, reverse=True)


def dense_only(query: str, expert: str | None = None, k: int = DENSE_TOP_K):
    """Dense-only retrieval, for the evaluation harness's ablation."""
    index = _index()
    vector = index.embedder.encode([query], normalize_embeddings=True).tolist()
    where = {"expert": expert} if expert else None
    hits = index.collection.query(query_embeddings=vector, n_results=k, where=where)
    return [
        RetrievalResult(
            chunk_id=cid,
            text=index.documents.get(cid, ""),
            metadata=index.metadata.get(cid, {}),
            dense_rank=position,
            rrf_score=1.0 / (position + 1),
        )
        for position, cid in enumerate(hits["ids"][0])
    ]
