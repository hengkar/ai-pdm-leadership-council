"""A stub standing in for all three provider SDKs.

The adapters are thin wrappers around three quite different SDK surfaces, and
the bugs worth catching live in that wrapping — error mapping, token caps,
whether a mid-stream failure gets retried. Mocking at the SDK boundary keeps
the adapters' real code paths under test while needing no key and no network.

One stub exposes all three shapes (`.chat`, `.messages`, `.models`) so the same
contract assertions can run against every adapter.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Iterator

import pytest


class StubError(Exception):
    """Carries the failure kind so adapters can classify it like a real error."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"stub {kind} failure")
        self.kind = kind
        self.status_code = {"auth": 401, "rate_limit": 429, "server": 500}.get(kind, 0)


class _StubSDK:
    def __init__(
        self,
        deltas: list[str] | None = None,
        parsed: dict[str, Any] | None = None,
        fails_with: str | None = None,
        fails_mid_stream: bool = False,
    ) -> None:
        self._deltas = deltas or []
        self._parsed = parsed
        self._fails_with = fails_with
        self._fails_mid_stream = fails_mid_stream

        self.call_count = 0
        self.last_max_tokens: int | None = None

        # OpenAI shape
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(parse=self._openai_parse, create=self._openai_create)
        )
        # Anthropic shape
        self.messages = SimpleNamespace(
            parse=self._anthropic_parse, stream=self._anthropic_stream, create=self._ping
        )
        # Gemini shape
        self.models = SimpleNamespace(
            generate_content=self._gemini_generate,
            generate_content_stream=self._gemini_stream,
            list=self._ping,
        )

    # -- shared helpers -------------------------------------------------
    def _record(self, max_tokens: int | None) -> None:
        self.call_count += 1
        if max_tokens is not None:
            self.last_max_tokens = max_tokens
        if self._fails_with:
            raise StubError(self._fails_with)

    def _text_iter(self) -> Iterator[str]:
        for delta in self._deltas:
            yield delta
        if self._fails_mid_stream:
            raise StubError("server")

    def _ping(self, *args: Any, **kwargs: Any) -> Any:
        self._record(kwargs.get("max_tokens") or kwargs.get("max_output_tokens"))
        return SimpleNamespace(id="ok")

    # -- OpenAI ---------------------------------------------------------
    def _openai_parse(self, **kwargs: Any) -> Any:
        self._record(kwargs.get("max_tokens"))
        message = SimpleNamespace(parsed=self._build(kwargs.get("response_format")))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    def _openai_create(self, **kwargs: Any) -> Any:
        self._record(kwargs.get("max_tokens"))
        return (
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])
            for text in self._text_iter()
        )

    # -- Anthropic ------------------------------------------------------
    def _anthropic_parse(self, **kwargs: Any) -> Any:
        self._record(kwargs.get("max_tokens"))
        return SimpleNamespace(parsed_output=self._build(kwargs.get("output_format")))

    @contextmanager
    def _anthropic_stream(self, **kwargs: Any):
        self._record(kwargs.get("max_tokens"))
        yield SimpleNamespace(text_stream=self._text_iter())

    # -- Gemini ---------------------------------------------------------
    def _gemini_generate(self, **kwargs: Any) -> Any:
        config = kwargs.get("config") or {}
        self._record(config.get("max_output_tokens"))
        return SimpleNamespace(parsed=self._build(config.get("response_schema")), text="{}")

    def _gemini_stream(self, **kwargs: Any) -> Any:
        config = kwargs.get("config") or {}
        self._record(config.get("max_output_tokens"))
        return (SimpleNamespace(text=text) for text in self._text_iter())

    # -- parsing --------------------------------------------------------
    def _build(self, schema: Any) -> Any:
        """Return a schema instance, or None to simulate a refusal/truncation."""
        if self._parsed is None or schema is None:
            return None
        return schema(**self._parsed)


@pytest.fixture
def stub_sdk():
    def factory(**kwargs: Any) -> _StubSDK:
        return _StubSDK(**kwargs)

    return factory
