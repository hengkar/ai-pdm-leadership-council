"""System prompts, few-shot exemplars, and context assembly.

Two rules run through everything here.

The model must **synthesise rather than quote**. Roughly nine tenths of the
corpus is podcast transcript — real speech, with the hesitations and asides
that come with it. Quoting it verbatim reads badly and, worse, presents an
off-the-cuff remark as a considered position.

The model must **never speak as the expert**. It reports what someone has
argued in public; it does not impersonate them. Putting words in a named real
person's mouth is the failure mode this product most needs to avoid.

Prompt order is static-first — instructions, then exemplars, then the retrieved
passages and the question — so providers with prefix caching can reuse the
front of the prompt across turns.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from rag.retrieve import RetrievalResult

_SHARED_RULES = """\
Ground every claim in the excerpts provided. Where the excerpts do not cover \
something, say so plainly rather than filling the gap from general knowledge.

Synthesise; do not quote at length. Most excerpts are speech transcribed \
verbatim, so reproducing them reads poorly — put the thinking in your own words \
and keep any direct quotation to a short, telling phrase.

Never write as though you are the expert. You are reporting what they have \
argued in public. Do not invent positions, predictions, or anecdotes they have \
not stated.

Refer to each expert by name in the text so the reader can tell whose thinking \
is whose. Do not add a sources list — the interface renders citations itself.\
"""

COUNCIL_SYSTEM = f"""\
You advise product managers by drawing together how several experienced product \
leaders have approached a situation.

Structure every answer with these three markdown sections and no others:

## Your Situation
One short paragraph restating the situation as you understand it, naming the \
real underlying problem rather than repeating the question back.

## Perspectives
One `### {{Expert Name}}` subsection per expert, two to four sentences each. \
Where the experts genuinely differ, say so — contrast is the point of asking a \
council rather than one person. Where they agree, do not manufacture \
disagreement.

## Recommended Actions
A numbered list of three to six concrete next steps the reader could take this \
week. Actions, not principles.

{_SHARED_RULES}\
"""

EXPERT_SYSTEM = """\
You advise product managers in the spirit of {expert}'s published thinking.

Answer as a knowledgeable colleague explaining how {expert} approaches this kind \
of problem — "{expert} argues that…", never "I think…". Use only the excerpts \
provided, all of which are {expert}'s own work.

Structure the answer as a short paragraph framing the situation, then the \
substance of {expert}'s approach, then two to five concrete next steps.

If the excerpts do not really address the question, say directly that {expert} \
has not written much on this, and offer only what the material genuinely \
supports. That is more useful than a confident answer built from thin material.

""" + _SHARED_RULES

OFF_TOPIC_REPLY = """\
This council answers product-management situations — prioritisation, roadmaps, \
discovery, metrics, stakeholders, team dynamics, growth, and career questions in \
product.

Ask about a situation you are facing at work and it will draw on how experienced \
product leaders have approached it.\
"""


def coverage_gap_reply(expert: str | None, council: bool) -> str:
    """Said when retrieval found nothing worth answering from."""
    if expert:
        return (
            f"The corpus does not contain enough of {expert}'s published thinking on "
            "this to answer well. Try the full council, or rephrase towards the "
            "underlying product problem."
        )
    if council:
        return (
            "Only one voice in the corpus touches on this, so a council answer would "
            "misrepresent what the material supports. Try asking a specific expert, "
            "or rephrase towards the underlying product problem."
        )
    return (
        "The council's published material does not cover this well enough to answer "
        "without guessing. Try rephrasing towards the product problem underneath it."
    )


@dataclass(frozen=True)
class Exemplar:
    """One worked example, used to pin the answer's shape rather than content."""

    situation: str
    answer: str


# Deliberately small and format-focused. These teach structure and register;
# the substance always comes from the retrieved passages.
EXEMPLARS: tuple[Exemplar, ...] = (
    Exemplar(
        situation="My engineering team keeps pushing back on my roadmap.",
        answer=(
            "## Your Situation\nThe disagreement is being treated as a scheduling "
            "dispute when it is usually a disagreement about evidence.\n\n"
            "## Perspectives\n### An Expert\nBring engineers into discovery rather "
            "than presenting finished conclusions.\n\n### Another Expert\nSeparate "
            "disagreement about the problem from disagreement about the solution.\n\n"
            "## Recommended Actions\n1. Run a problem-framing session.\n"
            "2. Share the customer evidence directly.\n"
            "3. Agree the success metric before debating implementation."
        ),
    ),
    Exemplar(
        situation="How do I choose what goes on the roadmap next quarter?",
        answer=(
            "## Your Situation\nThe real question is what evidence earns a place on "
            "the roadmap, not which framework to rank with.\n\n"
            "## Perspectives\n### An Expert\nPrioritise by the size of the "
            "uncertainty a bet removes.\n\n### Another Expert\nCommit to outcomes and "
            "leave the team room on the solution.\n\n"
            "## Recommended Actions\n1. Write the outcome each candidate serves.\n"
            "2. Rank by evidence, not by requester.\n"
            "3. Timebox the riskiest assumption first."
        ),
    ),
    Exemplar(
        situation="I've just become a manager and I'm struggling to let go of the work.",
        answer=(
            "## Your Situation\nThe discomfort is about where your contribution now "
            "comes from, not about workload.\n\n"
            "## Perspectives\n### An Expert\nYour output is now the team's output.\n\n"
            "### Another Expert\nDelegate the outcome, not the task list.\n\n"
            "## Recommended Actions\n1. Name one thing to stop doing this week.\n"
            "2. Hand over a whole outcome, not a subtask.\n"
            "3. Agree how you will hear about problems early."
        ),
    ),
    Exemplar(
        situation="Our activation numbers are flat and nobody agrees why.",
        answer=(
            "## Your Situation\nWithout a shared definition of activation, each team "
            "is optimising a different thing.\n\n"
            "## Perspectives\n### An Expert\nDefine the moment a user first gets "
            "value, then measure to it.\n\n### Another Expert\nInstrument the drop-off "
            "before theorising about causes.\n\n"
            "## Recommended Actions\n1. Write down the activation moment.\n"
            "2. Instrument each step to it.\n3. Fix the largest drop first."
        ),
    ),
)


@lru_cache(maxsize=1)
def _exemplar_vectors():
    from sentence_transformers import SentenceTransformer

    from rag.config import EMBEDDING_MODEL

    model = SentenceTransformer(EMBEDDING_MODEL)
    return model, model.encode(
        [e.situation for e in EXEMPLARS], normalize_embeddings=True
    )


def select_exemplars(question: str, count: int = 2) -> list[Exemplar]:
    """Pick the exemplars closest to this question.

    Sending all of them would spend tokens on examples that do not resemble the
    question and drag the answer towards their shape.
    """
    model, vectors = _exemplar_vectors()
    query = model.encode([question], normalize_embeddings=True)[0]
    scored = sorted(
        zip(EXEMPLARS, (float(query @ vector) for vector in vectors)),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [exemplar for exemplar, _ in scored[:count]]


def format_excerpts(results: list[RetrievalResult]) -> str:
    """Render retrieved passages for the prompt, numbered and attributed.

    Episodes whose upstream metadata is unreliable are labelled by show rather
    than by title, so the model cannot cite an episode we cannot stand behind.
    """
    lines: list[str] = []
    for position, result in enumerate(results, start=1):
        meta = result.metadata
        expert = meta.get("expert", "Unknown")
        if meta.get("content_type") == "podcast_transcript":
            source = (
                f"{meta.get('title')} (podcast)"
                if meta.get("episode_verified", True)
                else "Lenny's Podcast"
            )
        else:
            source = meta.get("title", "untitled")
        lines.append(f"[{position}] {expert} — {source}\n{result.text.strip()}")
    return "\n\n".join(lines)


def build_user_turn(
    question: str, results: list[RetrievalResult], exemplars: list[Exemplar]
) -> str:
    """Assemble the variable half of the prompt: examples, excerpts, question."""
    blocks: list[str] = []
    if exemplars:
        shown = "\n\n".join(
            f"Situation: {e.situation}\n\n{e.answer}" for e in exemplars
        )
        blocks.append(f"Examples of the expected shape and register:\n\n{shown}")
    blocks.append(f"Excerpts from the experts' published work:\n\n{format_excerpts(results)}")
    blocks.append(f"The product manager's situation:\n\n{question}")
    return "\n\n---\n\n".join(blocks)
