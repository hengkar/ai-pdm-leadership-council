"""Persisted schemas shared by every pipeline stage.

These models are the only coupling between fetch, parse, enrich, chunk and
build_index — each stage reads the previous stage's files and writes its own.
See specs/001-pdm-leadership-council/contracts/data-schemas.md.

Attribution is enforced at the type level: `expert`, `doc_id` and `url` are
required and non-empty everywhere, so a record that cannot be traced back to a
named expert and an original source simply cannot be constructed
(constitution Principle III).
"""

from __future__ import annotations

# Aliased: these models have a field called `date`, which would otherwise
# shadow the type when pydantic resolves the deferred annotations.
from datetime import date as DateType
from enum import Enum
from typing import Annotated

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    NonNegativeInt,
    PositiveInt,
    field_validator,
    model_validator,
)

# Bumped whenever a field is renamed, removed, or changes meaning. build_index
# and rag.retrieve compare against this and refuse to load a stale artifact.
SCHEMA_VERSION = 1

# A work shorter than this is boilerplate (a stub page, a link roundup) rather
# than something an expert actually argued.
MIN_WORD_COUNT = 300

NonEmptyStr = Annotated[str, Field(min_length=1)]


class ContentType(str, Enum):
    """Where a source work came from. Drives chunking and citation rendering."""

    BLOG = "blog"
    NEWSLETTER = "newsletter"
    PDF_DECK = "pdf_deck"
    PODCAST_TRANSCRIPT = "podcast_transcript"


class Segment(BaseModel):
    """A natural sub-unit of a work, carried from parsing into chunking.

    Without this the structure discovered while parsing is lost: joining a
    transcript's exchanges into one string throws away the timestamps that make
    a citation deep-linkable, and flattening an article throws away the heading
    trail that tells a reader where a passage sits.
    """

    text: NonEmptyStr
    timestamp_s: NonNegativeInt | None = None   # transcripts
    heading_path: str | None = None             # articles


class SourceWork(BaseModel):
    """One original piece by one expert: an article, newsletter, deck or episode.

    Written by `parse.py` to data/curated/<expert-slug>/<work-slug>.json, then
    re-written in place by `enrich.py` once `topics` and `summary` are filled.
    """

    id: NonEmptyStr
    expert: NonEmptyStr
    title: NonEmptyStr
    url: HttpUrl
    date: DateType | None = None
    content_type: ContentType
    word_count: PositiveInt
    body: NonEmptyStr

    # Podcast-only: lets citations deep-link to the moment in the episode.
    video_id: str | None = None
    youtube_url: HttpUrl | None = None

    # False when the upstream archive's episode metadata cannot be trusted for
    # this work — e.g. two works carrying the same video_id, or one transcript
    # filed under two different episode titles. The expert attribution is still
    # sound (it comes from the speaker labels inside the transcript), but the
    # episode identity is not, so citations must not name the episode or
    # deep-link to a timestamp that may belong to a different recording.
    episode_verified: bool = True

    # Added by the enrichment stage; absent on freshly parsed records.
    topics: list[str] = Field(default_factory=list, max_length=5)
    summary: str | None = None

    # Structure preserved from parsing so the chunker does not have to
    # rediscover it. Empty for formats with no usable internal structure, in
    # which case the chunker falls back to splitting `body`.
    segments: list[Segment] = Field(default_factory=list)

    @field_validator("word_count")
    @classmethod
    def _meets_quality_gate(cls, v: int) -> int:
        if v < MIN_WORD_COUNT:
            raise ValueError(f"work has {v} words, below the {MIN_WORD_COUNT}-word gate")
        return v

    @model_validator(mode="after")
    def _podcasts_carry_episode_links(self) -> SourceWork:
        is_podcast = self.content_type is ContentType.PODCAST_TRANSCRIPT
        if is_podcast and not (self.video_id and self.youtube_url):
            raise ValueError("podcast_transcript requires video_id and youtube_url")
        if not is_podcast and (self.video_id or self.youtube_url):
            raise ValueError("video_id/youtube_url are only valid on podcast_transcript")
        return self


class Chunk(BaseModel):
    """A retrievable passage. One line of data/chunks.jsonl.

    Metadata is denormalized from the parent SourceWork so that `rag/` can build
    a full citation from the search index alone, without reading data/curated/.
    """

    chunk_id: NonEmptyStr
    doc_id: NonEmptyStr
    expert: NonEmptyStr
    title: NonEmptyStr
    url: HttpUrl
    date: DateType | None = None
    content_type: ContentType
    topics: list[str] = Field(default_factory=list)
    text: NonEmptyStr

    # Articles: the heading trail ("Product vs Feature Teams > The PM's Role"),
    # prepended to `text` at embed time for context.
    heading_path: str | None = None

    # Podcasts: seconds into the episode, for a `&t=` deep link.
    timestamp_s: NonNegativeInt | None = None
    youtube_url: HttpUrl | None = None

    # Carried through from the parent work. When False the citation layer must
    # fall back to attributing the expert and the show, without an episode
    # title or a timestamped link (see SourceWork.episode_verified).
    episode_verified: bool = True

    @model_validator(mode="after")
    def _podcast_chunks_are_locatable(self) -> Chunk:
        is_podcast = self.content_type is ContentType.PODCAST_TRANSCRIPT
        if is_podcast and (self.timestamp_s is None or self.youtube_url is None):
            raise ValueError("podcast chunk requires timestamp_s and youtube_url")
        if not is_podcast and self.timestamp_s is not None:
            raise ValueError("timestamp_s is only valid on podcast chunks")
        return self


class Mode(str, Enum):
    """Which product mode a question was asked in."""

    COUNCIL = "council"
    EXPERT = "expert"


class EvalCase(BaseModel):
    """One line of evaluation/dataset.jsonl."""

    question: NonEmptyStr
    mode: Mode
    expert: str | None = None
    expected_doc_ids: list[NonEmptyStr] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _expert_mode_names_an_expert(self) -> EvalCase:
        if self.mode is Mode.EXPERT and not self.expert:
            raise ValueError("expert-mode cases must name the expert")
        return self
