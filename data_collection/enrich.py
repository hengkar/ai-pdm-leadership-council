"""Stage 3 — add controlled-vocabulary topics and a short summary to each work.

Offline and one-time: this is the only pipeline stage that calls an LLM, and it
runs on the maintainer's own key, read from the environment. Nothing here is
reachable from the running app, so a user's key is never spent on curation
(constitution Principles I and II).

    echo 'DEV_LLM_API_KEY=sk-...' > .env     # gitignored, maintainer key only
    .venv/bin/python -m data_collection.enrich [--force] [--limit N]

Topics are constrained by the response schema itself, so the model cannot
invent a tag that would later fail to match any filter.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from data_collection.vocabulary import TOPICS
from rag.config import CURATED_DIR, PROJECT_ROOT

MODEL = "gpt-4o-mini"

# Per-work excerpt cap. The opening of a work carries its thesis, and tagging
# does not improve enough with the full text to justify the tokens.
MAX_EXCERPT_CHARS = 12_000

# gpt-4o-mini list pricing, USD per token. Used only to report what the run cost.
INPUT_COST_PER_TOKEN = 0.15 / 1_000_000
OUTPUT_COST_PER_TOKEN = 0.60 / 1_000_000

# Building the enum into the schema is what makes an off-vocabulary tag
# unrepresentable rather than merely detectable.
TopicLiteral = Literal[tuple(sorted(TOPICS))]  # type: ignore[valid-type]


class Enrichment(BaseModel):
    """Structured output contract for one work."""

    topics: list[TopicLiteral] = Field(  # type: ignore[valid-type]
        description="2-5 topics that this work substantively covers.",
        min_length=1,
        max_length=5,
    )
    summary: str = Field(
        description="Two sentences describing what the expert argues in this work."
    )


SYSTEM_PROMPT = (
    "You catalogue product-management writing and interviews for a retrieval "
    "system. Given one work by a named product leader, choose the topics it "
    "substantively covers — not every topic it mentions in passing — and write "
    "a two-sentence summary of the argument the expert actually makes. Write "
    "the summary so a product manager scanning search results can tell whether "
    "this work speaks to their situation."
)


_KEY_NAMES = ("DEV_LLM_API_KEY", "OPENAI_API_KEY")


def _load_dotenv(path: Path) -> None:
    """Load `KEY=value` lines from a local .env into the environment.

    `.env` is gitignored and holds the *maintainer's* key for this offline
    stage only. It is never read by the deployed app, which accepts a key from
    the user at runtime and nowhere else (constitution Principle I).

    Reading from a file beats passing the key on a command line, where it would
    land in shell history and be visible to anything listing processes.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        # Real environment always wins, so an explicit export can override .env.
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def _api_key() -> str:
    _load_dotenv(PROJECT_ROOT / ".env")
    for name in _KEY_NAMES:
        key = os.environ.get(name, "").strip()
        if key:
            return key
    print(
        "No maintainer key found.\n"
        "Create a .env file in the project root (it is gitignored) containing:\n"
        "    DEV_LLM_API_KEY=sk-...\n"
        "or export DEV_LLM_API_KEY in your shell before running this stage.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def enrich_work(client: OpenAI, work: dict) -> tuple[Enrichment, int, int]:
    """Tag and summarize one work. Returns the result plus token counts."""
    excerpt = work["body"][:MAX_EXCERPT_CHARS]
    completion = client.chat.completions.parse(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Expert: {work['expert']}\n"
                    f"Title: {work['title']}\n"
                    f"Format: {work['content_type']}\n\n"
                    f"Work (opening excerpt):\n{excerpt}"
                ),
            },
        ],
        response_format=Enrichment,
    )
    usage = completion.usage
    parsed = completion.choices[0].message.parsed
    if parsed is None:  # refusal or truncation
        raise RuntimeError(f"no structured output returned for {work['id']}")
    return parsed, usage.prompt_tokens, usage.completion_tokens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-enrich works that already have topics")
    parser.add_argument("--limit", type=int, help="stop after N works (for a cheap trial run)")
    args = parser.parse_args(argv)

    paths = sorted(CURATED_DIR.rglob("*.json"))
    if not paths:
        print("No curated works found — run fetch.py then parse.py first.")
        return 1

    client = OpenAI(api_key=_api_key())
    enriched = skipped = failed = 0
    total_in = total_out = 0

    for path in paths:
        work = json.loads(path.read_text(encoding="utf-8"))

        if work.get("topics") and work.get("summary") and not args.force:
            skipped += 1
            continue
        if args.limit is not None and enriched >= args.limit:
            skipped += 1
            continue

        try:
            result, tokens_in, tokens_out = enrich_work(client, work)
        except Exception as exc:  # keep going; one bad work shouldn't halt the run
            print(f"  FAIL  {work['id']}: {type(exc).__name__}", file=sys.stderr)
            failed += 1
            continue

        work["topics"] = list(result.topics)
        work["summary"] = result.summary
        path.write_text(json.dumps(work, indent=2, ensure_ascii=False), encoding="utf-8")

        total_in += tokens_in
        total_out += tokens_out
        enriched += 1
        print(f"  ok    {work['id']}: {', '.join(work['topics'])}")

    cost = total_in * INPUT_COST_PER_TOKEN + total_out * OUTPUT_COST_PER_TOKEN
    print(f"\n{enriched} enriched, {skipped} skipped, {failed} failed")
    print(f"tokens: {total_in:,} in / {total_out:,} out — approx ${cost:.4f} on {MODEL}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
