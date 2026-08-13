"""robots.txt checks, including AI-ingestion opt-outs.

Standard robots parsing answers "may a crawler fetch this path". It does not
answer the question this project actually has to ask, which is whether the
publisher is willing to have their writing ingested by an AI system.

Many sites now answer that separately: they allow general crawlers and search
indexing while naming the AI crawlers specifically and disallowing them. A
fetcher with a bespoke user-agent is not literally covered by a `ClaudeBot`
directive, but the intent behind that directive is unmistakable, and this is an
AI product. So a site that blocks the AI crawlers is treated as off limits.

Checked against Marty Cagan's svpg.com, which blocks all nine of the agents
below while permitting ordinary crawlers — the case that prompted this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

# Crawlers whose purpose is gathering text for AI training or retrieval.
# A site naming any of these is expressing a view about AI use of its content.
AI_CRAWLERS = frozenset(
    {
        "amazonbot",
        "anthropic-ai",
        "applebot-extended",
        "bytespider",
        "ccbot",
        "claudebot",
        "cohere-ai",
        "diffbot",
        "facebookbot",
        "google-extended",
        "gptbot",
        "meta-externalagent",
        "oai-searchbot",
        "perplexitybot",
        "timpibot",
    }
)


@dataclass(frozen=True)
class RobotsVerdict:
    allowed: bool
    reason: str
    blocked_ai_agents: tuple[str, ...] = ()


def _robots_url(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


def check(url: str, user_agent: str, session: requests.Session | None = None) -> RobotsVerdict:
    """Decide whether this project may fetch `url`.

    A site with no robots.txt is treated as permitted, which matches the
    standard: absence is not refusal. A site that blocks AI crawlers is
    refused even when our own user-agent would technically be allowed.
    """
    getter = session or requests
    robots_url = _robots_url(url)

    try:
        response = getter.get(robots_url, timeout=20, headers={"User-Agent": user_agent})
    except requests.RequestException as exc:
        return RobotsVerdict(False, f"could not fetch robots.txt ({type(exc).__name__})")

    if response.status_code >= 400:
        return RobotsVerdict(True, f"no robots.txt (HTTP {response.status_code}) — permitted")

    text = response.text

    blocked = _ai_agents_blocked(text)
    if blocked:
        return RobotsVerdict(
            False,
            "site opts out of AI ingestion (blocks " + ", ".join(blocked) + ")",
            tuple(blocked),
        )

    parser = RobotFileParser()
    parser.parse(text.splitlines())
    if not parser.can_fetch(user_agent, url):
        return RobotsVerdict(False, "path disallowed for our user-agent")

    return RobotsVerdict(True, "permitted by robots.txt")


def _ai_agents_blocked(robots_text: str) -> list[str]:
    """Return the AI crawlers this robots.txt disallows site-wide.

    Written directly rather than via RobotFileParser because we need to know
    *which* agents are named, not whether one particular agent may fetch.
    """
    blocked: list[str] = []
    current_agents: list[str] = []
    pending_group = True

    for raw_line in robots_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()

        if field == "user-agent":
            if not pending_group:  # a new group begins
                current_agents = []
                pending_group = True
            current_agents.append(value.lower())
        elif field == "disallow":
            pending_group = False
            if value == "/":
                blocked.extend(a for a in current_agents if a in AI_CRAWLERS)

    return sorted(set(blocked))
