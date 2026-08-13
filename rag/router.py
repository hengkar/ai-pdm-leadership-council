"""Query routing: decide what kind of question this is before spending on it.

Two jobs, both cheap. Off-topic questions are turned away before retrieval or
generation runs, which is what keeps a stray request well under a cent
(SC-008). And a council-mode question that names an expert — "what would
Shreyas say about this?" — is redirected to that expert's material, so the user
gets what they asked for without hunting for the dropdown (FR-013).

The classification uses each provider's structured-output mode, so the result
arrives as a typed value rather than prose to be parsed. That doubles as the
assignment's function-calling requirement.
"""

from __future__ import annotations

import logging
from enum import Enum

from pydantic import BaseModel, Field

from rag import roster
from rag.errors import ProviderError
from rag.llm import LLMClient

logger = logging.getLogger(__name__)


class RouteKind(str, Enum):
    PM_QUESTION = "pm_question"
    OFF_TOPIC = "off_topic"
    EXPERT_MENTIONED = "expert_mentioned"


class Route(BaseModel):
    """What the classifier returns."""

    kind: RouteKind = Field(
        description=(
            "pm_question for any product-management situation; off_topic if it has "
            "nothing to do with product work; expert_mentioned if the text names a "
            "specific product leader whose view is being asked for."
        )
    )
    expert: str | None = Field(
        default=None,
        description="The product leader named, if kind is expert_mentioned.",
    )


ROUTER_PROMPT = """\
Classify this message from a product manager.

Answer off_topic only if it plainly has nothing to do with product work — a \
recipe, a maths problem, general chit-chat. Anything about building, \
prioritising, measuring, launching, or leading product work is a pm_question, \
including career and team questions. When in doubt, choose pm_question: turning \
away a real question is worse than answering a marginal one.

Choose expert_mentioned only when the message names a person and asks for their \
view, and put that name in `expert`.

Message:
{question}\
"""


def route(client: LLMClient, question: str) -> Route:
    """Classify a question, degrading to answering it if classification fails.

    A router outage must not take the product down: if the call fails we treat
    the message as a normal question, which costs a little more than a refusal
    but never turns away someone with a real problem.
    """
    try:
        result = client.classify(ROUTER_PROMPT.format(question=question), Route)
    except ProviderError as exc:
        logger.warning("router failed, treating as a normal question: %s", exc.status.value)
        return Route(kind=RouteKind.PM_QUESTION)

    if result.kind is RouteKind.EXPERT_MENTIONED:
        # The model may name someone who is not on the council. Resolve against
        # the roster and fall back rather than filtering to nothing.
        resolved = roster.resolve(result.expert)
        if resolved is None:
            logger.info("routed to unknown expert %r — answering as council", result.expert)
            return Route(kind=RouteKind.PM_QUESTION)
        return Route(kind=RouteKind.EXPERT_MENTIONED, expert=resolved)

    return result
