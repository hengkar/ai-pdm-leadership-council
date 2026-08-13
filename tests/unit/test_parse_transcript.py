"""Transcript parsing: attribution is the thing that must not break.

A podcast transcript has two speakers. Only one of them is the expert whose
thinking the council is supposed to surface, so every assertion here is
ultimately about constitution Principle III.
"""

from __future__ import annotations

import pytest

from data_collection.parse import (
    Turn,
    canonical_expert_for_slug,
    parse_speaker_turns,
    qa_units,
    strip_boilerplate,
)

# A miniature transcript in the upstream format: `Speaker (HH:MM:SS):` headers
# followed by prose. Written by hand — not copied from the archive.
SAMPLE = """\
Shreyas Doshi (00:00:00):
The opening thought that gets used as the episode teaser.

Lenny (00:00:36):
Welcome to the show. Today my guest is Shreyas Doshi. Before we start, a word
from our sponsors.

Lenny (00:02:10):
How should a PM think about prioritisation when everything looks urgent?

Shreyas Doshi (00:02:31):
You separate the work into three buckets and you are honest about which bucket
you are actually in. Most teams skip that step.

Shreyas Doshi (00:03:02):
The second half of the same answer, delivered after a pause.

Lenny (00:04:00):
What about when leadership disagrees?
"""


def _turns() -> list[Turn]:
    return parse_speaker_turns(SAMPLE)


def test_speaker_turns_are_extracted_with_timestamps() -> None:
    turns = _turns()
    assert [t.speaker for t in turns][:3] == ["Shreyas Doshi", "Lenny", "Lenny"]
    assert turns[0].timestamp_s == 0
    assert turns[1].timestamp_s == 36
    assert turns[2].timestamp_s == 2 * 60 + 10


def test_guest_turns_are_distinguished_from_interviewer_turns() -> None:
    turns = parse_speaker_turns(SAMPLE, guest="Shreyas Doshi")
    guest_turns = [t for t in turns if t.is_guest]
    host_turns = [t for t in turns if not t.is_guest]

    assert len(guest_turns) == 3
    assert len(host_turns) == 3
    assert all(t.speaker == "Shreyas Doshi" for t in guest_turns)


def test_qa_units_attribute_to_the_guest_never_the_interviewer() -> None:
    """The central invariant: the host asks, the guest is quoted."""
    units = qa_units(parse_speaker_turns(SAMPLE, guest="Shreyas Doshi"))

    assert units, "expected at least one question/answer unit"
    for unit in units:
        assert unit.expert == "Shreyas Doshi"
        # The host's question is kept as retrieval context...
        assert unit.question is None or "?" in unit.question
        # ...but the answer body is the guest's words.
        assert unit.answer_text


def test_answer_turns_merge_until_the_next_question() -> None:
    units = qa_units(parse_speaker_turns(SAMPLE, guest="Shreyas Doshi"))
    prioritisation = next(u for u in units if u.question and "prioritis" in u.question)

    # Two consecutive guest turns after one question become one answer.
    assert "three buckets" in prioritisation.answer_text
    assert "second half" in prioritisation.answer_text
    # And the unit is anchored at the start of the answer, for the deep link.
    assert prioritisation.timestamp_s == 2 * 60 + 31


def test_a_trailing_question_with_no_answer_is_dropped() -> None:
    units = qa_units(parse_speaker_turns(SAMPLE, guest="Shreyas Doshi"))
    assert not any(
        u.question and "leadership disagrees" in u.question for u in units
    ), "a question with no answer after it is not a retrievable unit"


def test_two_part_mm_ss_timestamps_are_parsed() -> None:
    """The archive is not consistent: some episodes use MM:SS, not HH:MM:SS.

    Found on `shreyas-doshi-live`, where an HH:MM:SS-only parser silently
    produced zero turns and dropped the whole episode from the corpus.
    """
    short_form = (
        "Shreyas Doshi (00:02):\n"
        "An answer recorded in an episode that uses two-part timestamps.\n\n"
        "Lenny (12:30):\n"
        "And a follow-up question?\n\n"
        "Shreyas Doshi (12:45):\n"
        "The reply to it.\n"
    )
    turns = parse_speaker_turns(short_form, guest="Shreyas Doshi")

    assert len(turns) == 3
    assert turns[0].timestamp_s == 2
    assert turns[1].timestamp_s == 12 * 60 + 30
    assert sum(t.is_guest for t in turns) == 2


def test_mixed_timestamp_formats_in_one_file_both_parse() -> None:
    mixed = (
        "Shreyas Doshi (01:05):\nShort form answer.\n\n"
        "Shreyas Doshi (01:02:03):\nLong form answer.\n"
    )
    turns = parse_speaker_turns(mixed, guest="Shreyas Doshi")
    assert [t.timestamp_s for t in turns] == [65, 3723]


def test_sponsor_and_intro_boilerplate_is_stripped() -> None:
    cleaned = strip_boilerplate("Welcome to the show. A word from our sponsors. Real content here.")
    assert "sponsors" not in cleaned.lower()
    assert "Real content here." in cleaned


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("shreyas-doshi", "Shreyas Doshi"),
        ("shreyas-doshi-live", "Shreyas Doshi"),   # repeat appearance
        ("elena-verna-40", "Elena Verna"),          # fourth appearance
        ("casey-winters_", "Casey Winters"),        # upstream duplicate directory
    ],
)
def test_repeat_appearance_slugs_collapse_to_one_canonical_expert(
    slug: str, expected: str
) -> None:
    assert canonical_expert_for_slug(slug) == expected


def test_unknown_slug_is_rejected_rather_than_guessed() -> None:
    with pytest.raises(KeyError):
        canonical_expert_for_slug("some-guest-not-on-the-council")


def test_curated_corpus_marks_ambiguous_episodes_unverified() -> None:
    """Works sharing a video_id keep their content but lose the episode claim.

    The upstream archive files some transcripts against the wrong episode
    metadata. Expert attribution survives (it comes from the speaker labels),
    but naming the episode or deep-linking a timestamp would be a confident
    false claim, so those are withdrawn.
    """
    import json

    from rag.config import CURATED_DIR

    works = [json.loads(p.read_text()) for p in CURATED_DIR.rglob("*.json")]
    if not works:
        pytest.skip("no curated corpus yet — run fetch.py then parse.py")

    # Only podcast works have a video_id; articles would otherwise all collide
    # on a None key and look like one giant ambiguous group.
    by_video: dict[str, list[dict]] = {}
    for work in works:
        if work.get("video_id"):
            by_video.setdefault(work["video_id"], []).append(work)

    for video_id, sharing in by_video.items():
        expected = len(sharing) == 1
        for work in sharing:
            assert work["episode_verified"] is expected, (
                f"{work['id']} shares video_id {video_id} with "
                f"{len(sharing) - 1} other work(s) but is marked verified"
            )

    # Whatever the metadata says, every work still names a real expert.
    assert all(work["expert"] for work in works)
