"""Generate the retrieval evaluation set.

The questions are hand-written PM situations. The ground truth — which source
works *should* be retrievable for each — is derived from the enrichment stage's
topic tags rather than labelled by hand.

That is deliberate, and it is not circular: ranking uses embeddings and BM25
over passage text, while the topic tags are metadata the ranker never sees. So
the labels come from an independent signal, which is what makes the resulting
hit-rate meaningful rather than self-confirming.

    .venv/bin/python -m evaluation.build_dataset
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from rag.config import PROJECT_ROOT

DATASET_PATH = PROJECT_ROOT / "evaluation" / "dataset.jsonl"
CURATED = PROJECT_ROOT / "data" / "curated"

# (question, topic, mode). Written as a PM would actually phrase the problem,
# not as keyword queries — retrieval has to bridge that gap in the real product.
QUESTIONS: list[tuple[str, str, str]] = [
    ("My engineering team keeps pushing back on my roadmap. What should I do?", "engineering-collaboration", "council"),
    ("Engineering says my estimates are unrealistic. How do I handle that?", "engineering-collaboration", "council"),
    ("How do I get engineers involved earlier instead of handing them specs?", "engineering-collaboration", "council"),
    ("Everything on my backlog looks urgent. How do I choose?", "prioritization", "council"),
    ("How should I decide what goes in the next quarter?", "prioritization", "council"),
    ("My stakeholders all want their feature first. How do I prioritise fairly?", "prioritization", "council"),
    ("How do I build a roadmap people actually trust?", "roadmaps", "council"),
    ("Should my roadmap have dates on it?", "roadmaps", "council"),
    ("How do I talk to customers without leading them to the answer I want?", "customer-discovery", "council"),
    ("We keep building things nobody uses. How do I fix our discovery?", "customer-discovery", "council"),
    ("How often should my team be talking to users?", "customer-discovery", "council"),
    ("How do I run user research when I have no budget?", "user-research", "council"),
    ("What should I do when research contradicts what leadership believes?", "user-research", "council"),
    ("How do I pick a north star metric for my product?", "north-star-metrics", "council"),
    ("Our metrics look good but the business isn't growing. What am I missing?", "metrics", "council"),
    ("How do I know if a metric is actually a good one?", "metrics", "council"),
    ("Our growth has flattened and nobody agrees why. How do I diagnose it?", "growth", "council"),
    ("What growth tactics are usually a waste of time?", "growth", "council"),
    ("How do I think about growth loops versus funnels?", "growth", "council"),
    ("Users sign up and never come back. Where do I start?", "retention", "council"),
    ("How do I improve activation for a product with a long setup?", "retention", "council"),
    ("How do I tell whether we have product-market fit?", "product-market-fit", "council"),
    ("We have some traction but it feels fragile. Is that PMF?", "product-market-fit", "council"),
    ("How should I price a new product?", "pricing", "council"),
    ("How do I write a product strategy that isn't just a list of features?", "product-strategy", "council"),
    ("My company has no clear product strategy. What can I do from below?", "product-strategy", "council"),
    ("How do I communicate a vision people remember?", "vision", "council"),
    ("How do I influence senior stakeholders without authority?", "influence-without-authority", "council"),
    ("My CEO keeps overriding my roadmap. How do I handle it?", "stakeholder-management", "council"),
    ("How do I manage a stakeholder who bypasses me and goes to engineers?", "stakeholder-management", "council"),
    ("I've just moved from PM to leading PMs. How do I make that shift?", "product-leadership", "council"),
    ("How do I coach a PM who isn't performing?", "product-leadership", "council"),
    ("What does a good product team culture actually look like?", "team-dynamics", "council"),
    ("My team is demoralised after a failed launch. How do I rebuild momentum?", "team-dynamics", "council"),
    ("How do I hire a great product manager?", "hiring", "council"),
    ("What should I look for in a PM interview?", "hiring", "council"),
    ("How do I get better at product sense?", "product-sense", "council"),
    ("How do I know if I'm ready for a senior PM role?", "career-growth", "council"),
    ("How do I stop being a project manager and start being a product manager?", "career-growth", "council"),
    ("How should I run a product launch?", "go-to-market", "council"),
    ("How do I ship faster without lowering quality?", "execution", "council"),
    ("How do I write documents that actually get read?", "communication", "council"),
]


def main() -> int:
    by_topic: dict[str, list[str]] = defaultdict(list)
    works = 0
    for path in CURATED.rglob("*.json"):
        work = json.loads(path.read_text(encoding="utf-8"))
        works += 1
        for topic in work.get("topics", []):
            by_topic[topic].append(work["id"])

    if not works:
        print("No curated corpus — run the pipeline first.")
        return 1

    written = skipped = 0
    with DATASET_PATH.open("w", encoding="utf-8") as handle:
        for question, topic, mode in QUESTIONS:
            expected = sorted(by_topic.get(topic, []))
            if not expected:
                # No work in the corpus covers this topic, so the question
                # cannot be scored fairly. Dropping it beats scoring a miss
                # against material that was never there.
                print(f"  skip (no corpus coverage: {topic}): {question[:52]}…")
                skipped += 1
                continue
            handle.write(
                json.dumps(
                    {
                        "question": question,
                        "mode": mode,
                        "expert": None,
                        "expected_doc_ids": expected,
                        "tags": [topic],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            written += 1

    print(f"\n{written} cases written to {DATASET_PATH.relative_to(PROJECT_ROOT)} ({skipped} skipped)")
    print(f"corpus: {works} works across {len(by_topic)} topics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
