"""Controlled topic vocabulary for corpus enrichment.

The enrichment stage tags each source work with 2-5 of these terms. A closed
vocabulary is what makes topic filtering and per-topic eval slicing meaningful:
free-form tags drift ("roadmapping" vs "roadmaps" vs "planning") until no filter
matches reliably.

Adding a term means re-running `enrich.py` — existing works are only tagged with
terms that existed when they were enriched.
"""

from __future__ import annotations

TOPICS: frozenset[str] = frozenset(
    {
        # Discovery and evidence
        "customer-discovery",
        "user-research",
        "experimentation",
        "opportunity-solution-trees",
        # Deciding what to build
        "prioritization",
        "roadmaps",
        "product-strategy",
        "vision",
        "positioning",
        # Measurement
        "metrics",
        "north-star-metrics",
        "analytics",
        # Working with people
        "stakeholder-management",
        "engineering-collaboration",
        "team-dynamics",
        "hiring",
        "product-leadership",
        "influence-without-authority",
        # Growth and business
        "growth",
        "retention",
        "pricing",
        "product-market-fit",
        "go-to-market",
        # Craft and career
        "product-sense",
        "execution",
        "career-growth",
        "communication",
    }
)


def validate(topics: list[str]) -> list[str]:
    """Return `topics` unchanged, or raise if any term is outside the vocabulary.

    Called by the enrichment stage on the model's structured output so a
    hallucinated tag fails loudly at build time rather than silently producing a
    filter that matches nothing at query time.
    """
    unknown = sorted(set(topics) - TOPICS)
    if unknown:
        raise ValueError(
            f"topics outside the controlled vocabulary: {unknown}. "
            f"Add them to TOPICS and re-run enrichment, or fix the tagging prompt."
        )
    return topics
