"""Answer faithfulness: is the advice actually grounded in the excerpts?

Retrieval metrics say the right material was found. They say nothing about
whether the answer stuck to it. This product's core risk is a confident,
well-structured answer that attributes something to a named real person which
they never said — so that is what gets measured.

A judge model reads the answer beside the excerpts it was built from and scores
three things independently: grounding, attribution, and whether coverage gaps
were admitted rather than papered over.

Runs on the maintainer's key, offline, never a user's.

    .venv/bin/python -m evaluation.run_answer_eval [--n 12]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from statistics import mean

from openai import OpenAI
from pydantic import BaseModel, Field

from rag import prompts, rerank, retrieve
from rag.config import PROJECT_ROOT, Provider
from rag.llm import Message, make_client

DATASET_PATH = PROJECT_ROOT / "evaluation" / "dataset.jsonl"
RESULTS_PATH = PROJECT_ROOT / "evaluation" / "results_answers.md"
JUDGE_MODEL = "gpt-4o-mini"


class Judgement(BaseModel):
    grounded: int = Field(ge=1, le=5, description="Is every claim supported by the excerpts? 5 = fully.")
    attribution: int = Field(ge=1, le=5, description="Is each view attributed to the expert who actually holds it? 5 = exact.")
    admits_gaps: int = Field(ge=1, le=5, description="Where the excerpts are thin, does it say so instead of inventing? 5 = candid.")
    impersonation: bool = Field(description="True if the answer writes in an expert's first-person voice.")
    note: str = Field(description="One sentence on the most significant problem, or 'none'.")


JUDGE_PROMPT = """\
You are auditing an AI product-management adviser for faithfulness.

Below are the source excerpts the answer was built from, and the answer itself. \
Judge ONLY whether the answer is faithful to those excerpts — not whether the \
advice is good, well written, or complete.

Penalise: claims that go beyond the excerpts; views attributed to the wrong \
expert; invented anecdotes, statistics or quotations; and any passage written as \
though the expert were speaking in the first person.

EXCERPTS:
{excerpts}

ANSWER:
{answer}
"""


def _load_key() -> str:
    for line in (PROJECT_ROOT / ".env").read_text(encoding="utf-8").splitlines() if (PROJECT_ROOT / ".env").exists() else []:
        if line.strip() and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            os.environ.setdefault(name.strip(), value.strip().strip("\"'"))
    for name in ("DEV_LLM_API_KEY", "OPENAI_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    print("No maintainer key found — set DEV_LLM_API_KEY in .env", file=sys.stderr)
    raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=12, help="questions to judge")
    args = parser.parse_args(argv)

    key = _load_key()
    cases = [json.loads(line) for line in DATASET_PATH.read_text(encoding="utf-8").splitlines() if line.strip()][: args.n]

    answerer = make_client(Provider.OPENAI, key)
    judge = OpenAI(api_key=key, max_retries=0)

    scores: list[Judgement] = []
    impersonations: list[str] = []

    for index, case in enumerate(cases, start=1):
        question = case["question"]
        selected = rerank.select_for_council(
            rerank.rerank(question, retrieve.search(question))
        )
        if not selected:
            continue

        excerpts = prompts.format_excerpts(selected)
        user_turn = prompts.build_user_turn(question, selected, prompts.select_exemplars(question))
        answer = "".join(
            answerer.stream(prompts.COUNCIL_SYSTEM, [Message("user", user_turn)], max_tokens=900)
        )

        verdict = judge.chat.completions.parse(
            model=JUDGE_MODEL,
            messages=[{"role": "user", "content": JUDGE_PROMPT.format(excerpts=excerpts, answer=answer)}],
            response_format=Judgement,
            max_tokens=400,
        ).choices[0].message.parsed

        if verdict is None:
            continue
        scores.append(verdict)
        if verdict.impersonation:
            impersonations.append(question)
        print(f"  {index:>2}. grounded {verdict.grounded} · attribution {verdict.attribution} · "
              f"gaps {verdict.admits_gaps}{'  IMPERSONATION' if verdict.impersonation else ''}")

    if not scores:
        print("No answers judged.")
        return 1

    table = (
        "| dimension | mean (1-5) | min |\n|---|---|---|\n"
        f"| grounded in excerpts | {mean(s.grounded for s in scores):.2f} | {min(s.grounded for s in scores)} |\n"
        f"| correct attribution | {mean(s.attribution for s in scores):.2f} | {min(s.attribution for s in scores)} |\n"
        f"| admits coverage gaps | {mean(s.admits_gaps for s in scores):.2f} | {min(s.admits_gaps for s in scores)} |"
    )
    print(f"\n{table}\n\nimpersonation: {len(impersonations)}/{len(scores)} answers")

    RESULTS_PATH.write_text(
        "# Answer faithfulness\n\n"
        f"{len(scores)} council answers generated with `gpt-4o-mini` and judged by "
        f"`{JUDGE_MODEL}` against the excerpts each was built from. The judge scores "
        "faithfulness only — not whether the advice is good.\n\n"
        f"{table}\n\n"
        f"First-person impersonation of a named expert: **{len(impersonations)}/{len(scores)}** "
        "answers.\n\n"
        "Note that judge and answerer share a model family, so these numbers are a "
        "regression signal rather than an independent audit.\n",
        encoding="utf-8",
    )
    print(f"written to {RESULTS_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
