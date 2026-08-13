"""Stage 1 — fetch source material into data/raw/ (gitignored cache).

Runs on the maintainer's machine only. Writes nothing but raw files and a
manifest; parsing and cleaning are the next stage's job, so a parser fix never
requires re-downloading anything.

    .venv/bin/python data_collection/fetch.py --expert shreyas-doshi
    .venv/bin/python data_collection/fetch.py --all [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

from data_collection import robots

from rag.config import DATA_DIR, PROJECT_ROOT

RAW_DIR = DATA_DIR / "raw"
MANIFEST_PATH = RAW_DIR / "manifest.json"
SOURCES_PATH = PROJECT_ROOT / "data_collection" / "sources.yaml"

# Identifies the project to the servers we fetch from, so an operator who wants
# to block or contact us can. Politeness, not disguise.
USER_AGENT = (
    "ai-pdm-leadership-council/0.1 (educational RAG course project; "
    "contact via repository issues)"
)
REQUEST_TIMEOUT = 30
POLITE_DELAY_S = 1.0  # between requests to the same host


def content_hash(text: str) -> str:
    """Stable digest used to decide whether anything actually changed."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class ManifestEntry:
    content_hash: str
    local_path: str
    fetched_at: str


class Manifest:
    """Tracks what has been fetched so re-runs are no-ops.

    This is what makes the corpus reproducible: an unchanged upstream produces
    an unchanged corpus rather than a second copy of everything.
    """

    def __init__(self, path: Path, force: bool = False) -> None:
        self.path = path
        self.force = force
        self.entries: dict[str, ManifestEntry] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.entries = {
                url: ManifestEntry(**entry) for url, entry in raw.get("entries", {}).items()
            }

    def should_fetch(self, url: str, digest: str | None = None) -> bool:
        if self.force:
            return True
        entry = self.entries.get(url)
        if entry is None:
            return True
        # `digest` is None when we haven't seen the bytes yet (a plain HTTP GET);
        # in that case the URL being known is enough to skip.
        return digest is not None and entry.content_hash != digest

    def record(self, url: str, digest: str, local_path: str) -> None:
        self.entries[url] = ManifestEntry(
            content_hash=digest,
            local_path=local_path,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "entries": {url: asdict(entry) for url, entry in self.entries.items()},
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_registry() -> dict:
    return yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8"))


def _get(url: str, session: requests.Session) -> str:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    time.sleep(POLITE_DELAY_S)
    return response.text


def fetch_transcript_archive(
    registry: dict,
    manifest: Manifest,
    session: requests.Session,
    only_expert: str | None = None,
) -> list[Path]:
    """Fetch council-expert episodes from the pinned transcript archive.

    Pulls the individual files we need rather than cloning the repository: the
    archive holds 303 episodes and the council only covers about fifteen of
    them, so a targeted fetch is both faster and far less bandwidth for the
    host. Pinning to a commit SHA is what makes the result reproducible.
    """
    archive = registry["transcript_archives"][0]
    repo, ref = archive["repo"], archive["ref"]
    template = archive["path_template"]
    written: list[Path] = []

    for slug, expert in sorted(archive["episodes"].items()):
        if only_expert and expert.lower().replace(" ", "-") != only_expert:
            continue

        path_in_repo = template.format(slug=slug)
        url = f"https://raw.githubusercontent.com/{repo}/{ref}/{path_in_repo}"
        if not manifest.should_fetch(url):
            print(f"  skip  {slug} (unchanged)")
            continue

        try:
            body = _get(url, session)
        except requests.HTTPError as exc:
            print(f"  FAIL  {slug}: {exc}", file=sys.stderr)
            continue

        destination = RAW_DIR / "transcripts" / f"{slug}.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(body, encoding="utf-8")
        manifest.record(url, content_hash(body), str(destination.relative_to(PROJECT_ROOT)))
        written.append(destination)
        print(f"  ok    {slug} -> {expert} ({len(body):,} chars)")

    return written


_RSS_CANDIDATES = ("rss/", "feed/", "?feed=rss2")
_CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"


def _discover_feed(base_url: str, session: requests.Session) -> str | None:
    for suffix in _RSS_CANDIDATES:
        candidate = base_url.rstrip("/") + "/" + suffix.lstrip("/")
        try:
            response = session.get(candidate, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        except requests.RequestException:
            continue
        if response.ok and b"<item" in response.content[:200_000]:
            return candidate
    return None


def fetch_blog_feeds(
    registry: dict,
    manifest: Manifest,
    session: requests.Session,
    only_expert: str | None = None,
) -> list[Path]:
    """Fetch blog posts through each site's RSS feed.

    Feeds are the polite path: one request per site instead of one per post,
    and syndication is what a feed is published for. These two feeds also carry
    the full post in `content:encoded`, so no per-article crawling is needed.

    Every site is re-checked against robots.txt here, including the AI-ingestion
    opt-out, so adding a source to sources.yaml can never silently bypass it.
    """
    written: list[Path] = []

    for expert in registry["experts"]:
        if only_expert and expert["slug"] != only_expert:
            continue
        for source in expert.get("sources") or []:
            base_url = source["url"]

            verdict = robots.check(base_url, USER_AGENT, session)
            if not verdict.allowed:
                print(f"  SKIP  {expert['name']}: {verdict.reason}")
                continue

            feed_url = _discover_feed(base_url, session)
            if feed_url is None:
                print(f"  FAIL  {expert['name']}: no RSS feed found at {base_url}")
                continue

            try:
                feed_xml = _get(feed_url, session)
            except requests.RequestException as exc:
                print(f"  FAIL  {expert['name']}: {type(exc).__name__}", file=sys.stderr)
                continue

            items = ET.fromstring(feed_xml.encode("utf-8")).findall(".//item")
            limit = int(source.get("max_works", 30))
            kept = 0

            for item in items[:limit]:
                link = (item.findtext("link") or "").strip()
                title = (item.findtext("title") or "").strip()
                body_html = item.findtext(_CONTENT_ENCODED) or item.findtext("description") or ""
                if not (link and title and body_html):
                    continue

                digest = content_hash(body_html)
                if not manifest.should_fetch(link, digest):
                    continue

                payload = {
                    "expert": expert["name"],
                    "title": title,
                    "link": link,
                    "published": (item.findtext("pubDate") or "").strip(),
                    "html": body_html,
                }
                destination = RAW_DIR / "articles" / expert["slug"] / f"{_url_slug(link)}.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                manifest.record(link, digest, str(destination.relative_to(PROJECT_ROOT)))
                written.append(destination)
                kept += 1

            print(f"  ok    {expert['name']}: {kept} new of {len(items)} in feed ({feed_url})")

    return written


def _url_slug(url: str) -> str:
    tail = [part for part in urlparse(url).path.split("/") if part]
    slug = tail[-1] if tail else "post"
    return re.sub(r"[^A-Za-z0-9._-]", "-", slug)[:100]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expert", help="expert slug, e.g. shreyas-doshi")
    parser.add_argument("--all", action="store_true", help="fetch every configured source")
    parser.add_argument("--force", action="store_true", help="refetch even if unchanged")
    parser.add_argument(
        "--transcripts-only",
        action="store_true",
        help="fetch only the podcast archive (skip blog sources)",
    )
    args = parser.parse_args(argv)

    if not args.all and not args.expert:
        parser.error("pass --expert <slug> or --all")

    registry = load_registry()
    manifest = Manifest(MANIFEST_PATH, force=args.force)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    print("Fetching podcast transcripts (pinned commit):")
    written = fetch_transcript_archive(registry, manifest, session, only_expert=args.expert)

    if not args.transcripts_only:
        print("\nFetching blog feeds:")
        written += fetch_blog_feeds(registry, manifest, session, only_expert=args.expert)

    manifest.save()
    print(f"\n{len(written)} file(s) written; manifest at {MANIFEST_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
