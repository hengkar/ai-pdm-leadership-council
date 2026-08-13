"""Link health: do the citations actually resolve?

SC-004 promises every listed source resolves to real published material. That is
a claim about the outside world, so it has to be checked against the outside
world rather than asserted in a unit test. Run it before shipping and after any
corpus rebuild.

    .venv/bin/python -m evaluation.check_links [--sample 20]
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter

import requests

from rag.retrieve import _index

USER_AGENT = "ai-pdm-leadership-council/0.1 (link check; contact via repository issues)"
TIMEOUT = 20


def check(url: str, session: requests.Session) -> tuple[bool, str]:
    """HEAD first, falling back to a ranged GET.

    Plenty of sites reject HEAD but serve GET perfectly well, so a HEAD failure
    alone would produce false alarms.
    """
    try:
        response = session.head(url, timeout=TIMEOUT, allow_redirects=True)
        if response.status_code < 400:
            return True, str(response.status_code)
        response = session.get(
            url, timeout=TIMEOUT, allow_redirects=True, headers={"Range": "bytes=0-2048"}
        )
        return response.status_code < 400, str(response.status_code)
    except requests.RequestException as exc:
        return False, type(exc).__name__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=0, help="check N random URLs (0 = all)")
    args = parser.parse_args(argv)

    index = _index()
    # One URL per source work: checking every chunk would hammer the same pages.
    by_doc: dict[str, tuple[str, str]] = {}
    for meta in index.metadata.values():
        url = meta.get("youtube_url") or meta.get("url")
        if url:
            by_doc.setdefault(meta["doc_id"], (url, meta.get("expert", "?")))

    targets = list(by_doc.items())
    if args.sample and args.sample < len(targets):
        targets = random.sample(targets, args.sample)

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    failures: list[tuple[str, str, str]] = []
    codes: Counter[str] = Counter()
    for doc_id, (url, expert) in sorted(targets):
        ok, detail = check(url, session)
        codes[detail] += 1
        if not ok:
            failures.append((doc_id, url, detail))
            print(f"  DEAD  {expert:16} {detail:12} {url}", file=sys.stderr)

    checked = len(targets)
    print(f"\n{checked - len(failures)}/{checked} source links resolve")
    print("  responses: " + ", ".join(f"{code}×{n}" for code, n in codes.most_common()))
    if failures:
        print(f"\n{len(failures)} dead link(s) — a citation that 404s undermines the whole answer.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
