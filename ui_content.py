"""User-facing copy and the first-visit example situations.

Kept out of `app.py` so wording can change without touching wiring, and so the
examples stay easy to review against what the corpus actually covers.
"""

from __future__ import annotations

from dataclasses import dataclass

TAGLINE = "Learn how great product leaders think — about the situation you're actually in."

INTRO = """\
Describe a situation you're facing. The council retrieves how experienced product \
leaders have written and spoken about problems like it, then lays out where they \
agree, where they differ, and what you could do next — with every claim cited \
back to the original.\
"""

KEY_NOTE = """\
Your API key is held for this browser session only. It is never stored, never \
logged, and goes nowhere except the provider you choose.\
"""


@dataclass(frozen=True)
class ExamplePrompt:
    """A starting situation offered on first visit (FR-021)."""

    title: str
    situation: str


# Deliberately few, and chosen to match subjects the corpus genuinely covers —
# an example that retrieves badly is a worse first impression than none at all.
EXAMPLES: tuple[ExamplePrompt, ...] = (
    ExamplePrompt(
        "Roadmap pushback",
        "My engineering team keeps pushing back on my roadmap. What should I do?",
    ),
    ExamplePrompt(
        "Deciding what's next",
        "Everything on my backlog looks urgent. How do I decide what actually goes "
        "in the next quarter?",
    ),
    ExamplePrompt(
        "Growth has stalled",
        "Our growth has flattened and the team can't agree on why. How should I "
        "approach diagnosing it?",
    ),
    ExamplePrompt(
        "New to leading",
        "I've just moved from PM to leading a team of PMs and I'm struggling to let "
        "go of the hands-on work. How do I make that shift?",
    ),
)


def empty_state_html(roster_summary: str) -> str:
    """The hero shown before the first question."""
    return f"""
<div style="text-align:center; padding:2.2rem 1rem 1rem;">
  <div style="font-size:2rem; margin-bottom:.35rem;">🏛</div>
  <h2 style="margin:.2rem 0 .5rem; font-weight:600;">Ask the Product Council</h2>
  <p style="max-width:34rem; margin:0 auto 1rem; opacity:.8; line-height:1.55;">{INTRO}</p>
  <p style="opacity:.6; font-size:.9rem;">Drawing on {roster_summary}</p>
</div>
"""
