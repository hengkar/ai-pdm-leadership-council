"""Stage 2 — turn raw files into validated, attributed SourceWork records.

The transcript path is the delicate one. An episode has an interviewer and a
guest, and only the guest's words are the expert thinking the council exists to
surface, so speaker attribution is enforced here rather than left to chunking.

    .venv/bin/python data_collection/parse.py [--expert shreyas-doshi]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date as DateType
from email.utils import parsedate_to_datetime
from pathlib import Path

import frontmatter
import trafilatura
import yaml

from data_collection.schemas import ContentType, Segment, SourceWork
from rag.config import CURATED_DIR, DATA_DIR, PROJECT_ROOT

# Editorial gate for blog posts, stricter than the schema's 300-word validity
# floor. Measured against the fetched feeds, everything below this line is a
# podcast announcement, a sponsored customer story, or a "come work with me"
# promo rather than the expert's own thinking; everything at or above it is
# substantive. Transcripts keep the lower floor — they are long by nature.
MIN_BLOG_WORDS = 500

RAW_DIR = DATA_DIR / "raw"
SOURCES_PATH = PROJECT_ROOT / "data_collection" / "sources.yaml"

# `Speaker Name (HH:MM:SS):` or `Speaker Name (MM:SS):` at the start of a line.
# Both forms occur in the archive, sometimes within the same expert's episodes —
# an HH:MM:SS-only pattern silently yields zero turns and drops the episode.
_TURN_RE = re.compile(
    r"^(?P<speaker>[^\n(]{1,80}?)\s*\((?P<ts>(?:\d{1,2}:)?\d{1,2}:\d{2})\):\s*$", re.M
)

# Phrases that mark host housekeeping rather than substance. Deliberately
# conservative — over-stripping would silently delete real answers.
_BOILERPLATE_MARKERS = (
    "a word from our sponsors",
    "word from our sponsors",
    "brought to you by",
    "this episode is sponsored",
    "subscribe to the newsletter",
    "welcome to the show",
    "welcome to lenny's podcast",
)

_INAUDIBLE_RE = re.compile(r"\[inaudible[^\]]*\]", re.I)


@dataclass(frozen=True)
class Turn:
    speaker: str
    timestamp_s: int
    text: str
    is_guest: bool = False


@dataclass(frozen=True)
class QAUnit:
    """One retrievable exchange: the host's question plus the guest's answer."""

    expert: str
    answer_text: str
    timestamp_s: int
    question: str | None = None

    @property
    def retrieval_text(self) -> str:
        """Question first so the chunk matches how a PM phrases the problem."""
        return f"{self.question}\n\n{self.answer_text}" if self.question else self.answer_text


def _timestamp_to_seconds(stamp: str) -> int:
    """Seconds from either `HH:MM:SS` or `MM:SS`."""
    parts = [int(part) for part in stamp.split(":")]
    if len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        hours, (minutes, seconds) = 0, parts
    return hours * 3600 + minutes * 60 + seconds


def canonical_expert_for_slug(slug: str) -> str:
    """Map an episode directory slug to the one canonical expert name.

    Repeat appearances (`elena-verna-40`) and upstream duplicate directories
    (`casey-winters_`) must collapse, or the roster would show the same person
    several times and per-expert filtering would silently miss half their work.
    Unknown slugs raise rather than being guessed at.
    """
    registry = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8"))
    episodes = registry["transcript_archives"][0]["episodes"]
    if slug not in episodes:
        raise KeyError(f"{slug!r} is not a council episode in sources.yaml")
    return episodes[slug]


def strip_boilerplate(text: str) -> str:
    """Drop sponsor reads and show intros; keep everything else."""
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        lowered = sentence.lower()
        if any(marker in lowered for marker in _BOILERPLATE_MARKERS):
            continue
        kept.append(sentence)
    cleaned = " ".join(kept)
    cleaned = _INAUDIBLE_RE.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_speaker_turns(transcript: str, guest: str | None = None) -> list[Turn]:
    """Split a transcript body into speaker turns.

    `guest` marks which speaker's turns carry the expert's thinking; matching is
    loose (surname containment) because archives are inconsistent about whether
    a speaker is "Shreyas" or "Shreyas Doshi".
    """
    matches = list(_TURN_RE.finditer(transcript))
    turns: list[Turn] = []

    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(transcript)
        body = strip_boilerplate(transcript[body_start:body_end])
        if not body:
            continue

        speaker = match.group("speaker").strip()
        turns.append(
            Turn(
                speaker=speaker,
                timestamp_s=_timestamp_to_seconds(match.group("ts")),
                text=body,
                is_guest=_is_same_speaker(speaker, guest) if guest else False,
            )
        )
    return turns


def _is_same_speaker(speaker: str, guest: str) -> bool:
    speaker_l, guest_l = speaker.lower(), guest.lower()
    if speaker_l == guest_l:
        return True
    # "Shreyas" matches "Shreyas Doshi"; surname alone also matches.
    guest_parts = guest_l.split()
    return speaker_l in guest_parts or any(part in speaker_l.split() for part in guest_parts)


def qa_units(turns: list[Turn]) -> list[QAUnit]:
    """Group turns into question/answer units anchored on the guest's answers.

    Consecutive guest turns merge into one answer; a question with no answer
    after it is dropped, since there is nothing to retrieve.
    """
    units: list[QAUnit] = []
    pending_question: str | None = None
    answer_parts: list[str] = []
    answer_start: int | None = None
    expert: str | None = None

    def flush() -> None:
        nonlocal answer_parts, answer_start, pending_question
        if answer_parts and answer_start is not None and expert:
            units.append(
                QAUnit(
                    expert=expert,
                    answer_text=" ".join(answer_parts).strip(),
                    timestamp_s=answer_start,
                    question=pending_question,
                )
            )
        answer_parts = []
        answer_start = None
        pending_question = None

    for turn in turns:
        if turn.is_guest:
            expert = turn.speaker
            if answer_start is None:
                answer_start = turn.timestamp_s
            answer_parts.append(turn.text)
        else:
            # A host turn closes any answer in progress and becomes the next
            # question — questions are context, never attributed content.
            flush()
            pending_question = turn.text

    flush()
    return units


def parse_transcript_file(path: Path) -> SourceWork | None:
    """Parse one archive transcript into a validated SourceWork.

    Returns None when the episode is too thin to be useful (the schema's
    word-count gate), so callers can report a skip rather than crash.
    """
    slug = path.stem
    expert = canonical_expert_for_slug(slug)
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    meta = post.metadata

    turns = parse_speaker_turns(post.content, guest=expert)
    units = qa_units(turns)
    if not units:
        return None

    body = "\n\n".join(unit.retrieval_text for unit in units)
    word_count = len(body.split())
    if word_count < 300:
        return None

    published = meta.get("publish_date")
    if isinstance(published, str):
        published = DateType.fromisoformat(published)

    video_id = str(meta.get("video_id", "")).strip()
    youtube_url = str(meta.get("youtube_url", "")).strip()
    if not (video_id and youtube_url):
        return None  # without these a podcast citation cannot deep-link

    return SourceWork(
        id=f"{_slugify(expert)}--{slug}",
        expert=expert,
        title=str(meta.get("title") or slug).strip(),
        url=youtube_url,
        date=published if isinstance(published, DateType) else None,
        content_type=ContentType.PODCAST_TRANSCRIPT,
        word_count=word_count,
        body=body,
        video_id=video_id,
        youtube_url=youtube_url,
        # One segment per exchange, each keeping the second it starts at so a
        # citation can point back to that moment.
        segments=[
            Segment(text=unit.retrieval_text, timestamp_s=unit.timestamp_s) for unit in units
        ],
    )


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _parse_rfc822_date(value: str) -> DateType | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return None


def parse_article_file(path: Path) -> SourceWork | None:
    """Parse one saved RSS item into a validated SourceWork.

    The feed gives us the post as HTML; trafilatura pulls the article text out
    and drops navigation, share widgets and subscribe prompts. Returns None if
    extraction fails or the result is too thin to be worth indexing.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))

    # Markdown output keeps the heading structure, which becomes the chunk's
    # heading_path — cheap context that tells a reader where a passage sits.
    text = trafilatura.extract(
        payload["html"],
        include_comments=False,
        include_tables=False,
        favor_precision=True,
        output_format="markdown",
    )
    if not text:
        return None

    body = re.sub(r"\n{3,}", "\n\n", text).strip()
    word_count = len(body.split())
    if word_count < MIN_BLOG_WORDS:
        return None

    expert = payload["expert"]
    return SourceWork(
        id=f"{_slugify(expert)}--{path.stem}",
        expert=expert,
        title=payload["title"],
        url=payload["link"],
        date=_parse_rfc822_date(payload.get("published", "")),
        content_type=ContentType.BLOG,
        word_count=word_count,
        body=body,
        segments=_segment_markdown(body, payload["title"]),
    )


def _segment_markdown(markdown: str, title: str) -> list[Segment]:
    """Split article markdown into segments, one per heading section.

    The heading trail travels with each segment so a chunk can be embedded with
    the context of where it sits, rather than as a floating paragraph.
    """
    segments: list[Segment] = []
    heading = title
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            path = title if heading == title else f"{title} > {heading}"
            segments.append(Segment(text=text, heading_path=path))
        buffer.clear()

    for line in markdown.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if match:
            flush()
            heading = match.group(2).strip()
        else:
            buffer.append(line)
    flush()

    return segments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expert", help="only parse this expert's material")
    args = parser.parse_args(argv)

    transcripts = sorted((RAW_DIR / "transcripts").glob("*.md"))
    articles = sorted((RAW_DIR / "articles").rglob("*.json"))
    if not transcripts and not articles:
        print("No raw material found — run fetch.py first.")
        return 1

    # Pass 1 — parse and deduplicate. Nothing is written yet: whether a work's
    # episode metadata can be trusted depends on the *other* works, so the
    # collision check needs the whole set first.
    skipped = 0
    parsed: list[tuple[Path, SourceWork]] = []
    seen_bodies: dict[str, str] = {}  # content hash -> first work id that used it

    for path in articles:
        work = parse_article_file(path)
        if work is None:
            print(f"  skip  {path.stem}: extraction failed or below the quality gate")
            skipped += 1
            continue
        if args.expert and _slugify(work.expert) != args.expert:
            continue

        digest = hashlib.sha256(work.body.encode("utf-8")).hexdigest()
        if digest in seen_bodies:
            print(f"  dup   {work.id}: same body as {seen_bodies[digest]} — not curated")
            skipped += 1
            continue
        seen_bodies[digest] = work.id
        parsed.append((path, work))

    for path in transcripts:
        try:
            expert = canonical_expert_for_slug(path.stem)
        except KeyError:
            print(f"  skip  {path.stem}: not a council episode")
            skipped += 1
            continue
        if args.expert and _slugify(expert) != args.expert:
            continue

        work = parse_transcript_file(path)
        if work is None:
            print(f"  skip  {path.stem}: below the quality gate or missing episode links")
            skipped += 1
            continue

        # Identical bodies filed under two slugs must not both be indexed:
        # duplicate passages get retrieved twice and squeeze other experts out
        # of the council's context window.
        digest = hashlib.sha256(work.body.encode("utf-8")).hexdigest()
        if digest in seen_bodies:
            print(f"  dup   {work.id}: same body as {seen_bodies[digest]} — not curated")
            skipped += 1
            continue
        seen_bodies[digest] = work.id
        parsed.append((path, work))

    # Pass 2 — flag works whose episode identity is ambiguous. Two works sharing
    # a video_id means at least one carries the wrong episode metadata, so a
    # timestamped deep link from either could land in a different recording.
    # The expert attribution still holds (it comes from the speaker labels), so
    # the content is kept and only the episode-level claim is withdrawn.
    # Only podcast works carry a video_id. Articles must be excluded here or
    # they would all collide on a None key and be flagged as unverified.
    by_video: dict[str, list[str]] = {}
    for _, work in parsed:
        if work.video_id:
            by_video.setdefault(work.video_id, []).append(work.id)
    ambiguous = {
        work_id
        for ids in by_video.values()
        if len(ids) > 1
        for work_id in ids
    }

    written = 0
    for path, work in parsed:
        if work.id in ambiguous:
            work = work.model_copy(update={"episode_verified": False})

        destination = CURATED_DIR / _slugify(work.expert) / f"{path.stem}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)

        # Carry forward enrichment from a previous run. Without this, re-running
        # parse silently discards every topic and summary the enrichment stage
        # paid for, and the next chunk build ships with no metadata to filter on.
        # Only reuse them when the body is unchanged — if the text moved, the
        # old tags describe something that no longer exists.
        if destination.exists():
            previous = json.loads(destination.read_text(encoding="utf-8"))
            if previous.get("topics") and previous.get("body") == work.body:
                work = work.model_copy(
                    update={"topics": previous["topics"], "summary": previous.get("summary")}
                )

        destination.write_text(work.model_dump_json(indent=2), encoding="utf-8")
        written += 1

        flag = "" if work.episode_verified else "  [episode unverified — no deep link]"
        print(f"  ok    {work.id}: {work.word_count:,} words -> {work.expert}{flag}")

    print(f"\n{written} work(s) curated, {skipped} skipped")
    if ambiguous:
        print(
            f"\n{len(ambiguous)} work(s) marked episode_verified=false: content and expert "
            "attribution kept, episode title and timestamped links suppressed in citations."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
