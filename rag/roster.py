"""The council roster, derived from the committed index.

The roster is read from index metadata rather than from `sources.yaml`, for two
reasons: the running app must never touch the offline pipeline's files
(constitution Principle II), and an expert configured but not actually indexed
would otherwise appear in the UI and then answer nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache

from rag.config import CHROMA_COLLECTION, CHROMA_DIR

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RosterEntry:
    """One expert, as far as the app is concerned."""

    name: str
    chunk_count: int
    work_count: int
    content_types: frozenset[str] = field(default_factory=frozenset)

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "-")

    @property
    def source_hint(self) -> str:
        """Short marker for the sidebar: what kind of material backs this expert."""
        icons = []
        if "blog" in self.content_types:
            icons.append("📄")
        if "podcast_transcript" in self.content_types:
            icons.append("🎙")
        return "".join(icons)


@lru_cache(maxsize=1)
def load() -> tuple[RosterEntry, ...]:
    """Build the roster once per process, from committed index metadata.

    Cached because it is read on every page load and the index does not change
    while the app is running.
    """
    import chromadb

    if not CHROMA_DIR.exists():
        logger.warning("no index at %s — roster is empty", CHROMA_DIR)
        return ()

    collection = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(
        CHROMA_COLLECTION
    )
    records = collection.get(include=["metadatas"])

    chunks: dict[str, int] = {}
    works: dict[str, set[str]] = {}
    kinds: dict[str, set[str]] = {}
    for meta in records["metadatas"]:
        expert = meta["expert"]
        chunks[expert] = chunks.get(expert, 0) + 1
        works.setdefault(expert, set()).add(meta["doc_id"])
        kinds.setdefault(expert, set()).add(meta["content_type"])

    roster = [
        RosterEntry(
            name=expert,
            chunk_count=count,
            work_count=len(works[expert]),
            content_types=frozenset(kinds[expert]),
        )
        for expert, count in chunks.items()
    ]
    # An expert with nothing indexed is not on the council, whatever the
    # registry says. Alphabetical so the sidebar order is stable.
    return tuple(sorted((e for e in roster if e.chunk_count), key=lambda e: e.name))


def names() -> list[str]:
    return [entry.name for entry in load()]


def resolve(candidate: str | None) -> str | None:
    """Match a name mentioned in a question to a roster expert.

    Loose on purpose: a user writing "what would Shreyas say?" should reach
    Shreyas Doshi. Returns None when nothing matches, so the caller can fall
    back to council mode rather than filtering to an expert who does not exist.
    """
    if not candidate:
        return None
    needle = candidate.strip().lower()
    if not needle:
        return None

    for entry in load():
        full = entry.name.lower()
        if needle == full:
            return entry.name
        parts = full.split()
        if needle in parts or all(part in needle for part in parts):
            return entry.name
    return None
