"""Environment smoke test: dependencies resolve and the foundations behave.

Run: .venv/bin/python -m pytest tests/unit/test_imports.py -v
"""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "gradio",
        "chromadb",
        "sentence_transformers",
        "rank_bm25",
        "anthropic",
        "openai",
        "google.genai",
        "pydantic",
        "yaml",
        "trafilatura",
        "bs4",
        "fitz",          # pymupdf
        "frontmatter",   # python-frontmatter
    ],
)
def test_dependency_imports(module: str) -> None:
    importlib.import_module(module)


def test_project_packages_import() -> None:
    importlib.import_module("rag.config")
    importlib.import_module("rag.errors")
    importlib.import_module("data_collection.schemas")
    importlib.import_module("data_collection.vocabulary")


def test_runtime_package_does_not_import_the_offline_pipeline() -> None:
    """Constitution II, enforced as a test rather than a convention.

    `rag/` may only read committed index artifacts. If it ever imports the
    fetch/enrich code it would also acquire the developer key path, so the
    separation is checked at the source level.
    """
    import pkgutil

    import rag

    offenders = []
    for module_info in pkgutil.iter_modules(rag.__path__):
        source = (
            importlib.import_module(f"rag.{module_info.name}").__file__ or ""
        )
        if source and "data_collection" in open(source, encoding="utf-8").read():
            # A comment mentioning the package is fine; an import is not.
            text = open(source, encoding="utf-8").read()
            if "import data_collection" in text or "from data_collection" in text:
                offenders.append(module_info.name)
    assert not offenders, f"rag modules importing the offline pipeline: {offenders}"


def test_sources_registry_is_loadable_and_covers_the_roster() -> None:
    import yaml

    from rag.config import PROJECT_ROOT

    registry = yaml.safe_load(
        (PROJECT_ROOT / "data_collection" / "sources.yaml").read_text(encoding="utf-8")
    )

    names = {e["name"] for e in registry["experts"]}
    assert len(names) == len(registry["experts"]), "duplicate expert names"

    # Every expert must be reachable through at least one source: their own
    # site, the transcript archive, or both.
    archive = registry["transcript_archives"][0]
    covered = {e["name"] for e in registry["experts"] if e["sources"]}
    covered |= set(archive["episodes"].values())
    assert names <= covered, f"experts with no fetchable source: {sorted(names - covered)}"

    # The archive is pinned to a commit, not a branch, so rebuilds reproduce.
    assert len(archive["ref"]) == 40, "transcript archive must pin a full commit SHA"
