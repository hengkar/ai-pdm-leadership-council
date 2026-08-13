"""The seam between the app and the three AI providers.

`rag/pipeline.py` is written against `LLMClient` and never learns which provider
a user chose. Everything provider-specific — SDK shapes, error types, structured
output mechanics — is confined to the adapters below.

Three rules hold across all of them, and are contract-tested:

* the user's key never appears in a repr, an exception, or a log record;
* a failure part-way through a generation is never retried, because a retry
  bills the user twice for one question;
* every call is bounded by an explicit token cap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterator, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from rag.config import (
    ANSWER_MAX_TOKENS,
    KEY_VALIDATION_MAX_TOKENS,
    PROVIDER_MODELS,
    ROUTER_MAX_TOKENS,
    Provider,
)
from rag.errors import KeyStatus, ProviderError, scrub

logger = logging.getLogger(__name__)

ALL_PROVIDERS: tuple[Provider, ...] = tuple(Provider)

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class Message:
    role: str  # "user" | "assistant"
    content: str


@runtime_checkable
class LLMClient(Protocol):
    """What the pipeline may assume about any provider."""

    provider: Provider

    def validate_key(self) -> KeyStatus:
        """Cheapest possible call that proves the key works. Never raises."""

    def classify(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        """Structured output for routing. Raises ProviderError on failure."""

    def stream(self, system: str, messages: list[Message], max_tokens: int) -> Iterator[str]:
        """Yield text deltas. Raises ProviderError; already-yielded text stands."""


def classify_exception(exc: BaseException) -> KeyStatus:
    """Map any SDK's failure onto the shared taxonomy.

    Ordered from most reliable signal to least: an HTTP status if the SDK
    exposes one, then the exception class name, then the message text. The
    three SDKs raise unrelated exception hierarchies, so this deliberately
    avoids importing any of them.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int) and status:
        if status in (401, 403):
            return KeyStatus.INVALID_KEY
        if status == 429:
            return KeyStatus.QUOTA_EXCEEDED
        if status >= 500:
            return KeyStatus.PROVIDER_ERROR

    name = type(exc).__name__.lower()
    text = str(exc).lower()
    haystack = f"{name} {text}"

    if any(token in haystack for token in ("authentication", "unauthorized", "permissiondenied", "api key", "invalid_api_key")):
        return KeyStatus.INVALID_KEY
    if any(token in haystack for token in ("ratelimit", "rate limit", "quota", "resource_exhausted")):
        return KeyStatus.QUOTA_EXCEEDED
    if any(token in haystack for token in ("connection", "timeout", "network", "unreachable")):
        return KeyStatus.NETWORK_ERROR
    return KeyStatus.PROVIDER_ERROR


def _fail(exc: BaseException) -> ProviderError:
    """Wrap an SDK failure, scrubbing anything key-shaped out of the message."""
    return ProviderError(classify_exception(exc), scrub(str(exc)))


class _BaseAdapter:
    """Shared key handling. Subclasses supply the SDK-specific calls."""

    provider: Provider

    def __init__(self, api_key: str, sdk_client: Any | None = None) -> None:
        # Name-mangled and never surfaced: no property, no __repr__, no logging.
        self.__key = api_key
        self._sdk = sdk_client if sdk_client is not None else self._build_sdk(api_key)
        self.model = PROVIDER_MODELS[self.provider]

    def _build_sdk(self, api_key: str) -> Any:  # pragma: no cover - needs the real SDK
        raise NotImplementedError

    @property
    def _key(self) -> str:
        return self.__key

    def __repr__(self) -> str:
        return f"<{type(self).__name__} provider={self.provider.value} model={self.model}>"

    __str__ = __repr__

    def validate_key(self) -> KeyStatus:
        """Never raises — the UI renders the returned status directly."""
        try:
            self._ping()
        except BaseException as exc:  # including SDK errors that subclass BaseException
            status = classify_exception(exc)
            logger.debug("key validation failed for %s: %s", self.provider.value, scrub(str(exc)))
            return status
        return KeyStatus.OK

    def _ping(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class OpenAIAdapter(_BaseAdapter):
    provider = Provider.OPENAI

    def _build_sdk(self, api_key: str) -> Any:
        from openai import OpenAI

        # max_retries=0: the SDK's default retry would re-send a request the
        # user has already paid for.
        return OpenAI(api_key=api_key, max_retries=0)

    def _ping(self) -> None:
        self._sdk.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=KEY_VALIDATION_MAX_TOKENS,
        )

    def classify(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        try:
            completion = self._sdk.chat.completions.parse(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format=schema,
                max_tokens=ROUTER_MAX_TOKENS,
            )
            parsed = completion.choices[0].message.parsed
        except Exception as exc:
            raise _fail(exc) from None
        if parsed is None:
            raise ProviderError(KeyStatus.PROVIDER_ERROR, "no structured output returned")
        return parsed

    def stream(
        self, system: str, messages: list[Message], max_tokens: int = ANSWER_MAX_TOKENS
    ) -> Iterator[str]:
        payload = [{"role": "system", "content": system}]
        payload += [{"role": m.role, "content": m.content} for m in messages]
        try:
            chunks = self._sdk.chat.completions.create(
                model=self.model, messages=payload, max_tokens=max_tokens, stream=True
            )
        except Exception as exc:
            raise _fail(exc) from None
        return self._iter_deltas(chunks)

    @staticmethod
    def _iter_deltas(chunks: Any) -> Iterator[str]:
        try:
            for chunk in chunks:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            # Deliberately not retried: tokens have already been billed.
            raise _fail(exc) from None


class AnthropicAdapter(_BaseAdapter):
    provider = Provider.CLAUDE

    def _build_sdk(self, api_key: str) -> Any:
        import anthropic

        return anthropic.Anthropic(api_key=api_key, max_retries=0)

    def _ping(self) -> None:
        self._sdk.messages.create(
            model=self.model,
            max_tokens=KEY_VALIDATION_MAX_TOKENS,
            messages=[{"role": "user", "content": "hi"}],
        )

    def classify(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        try:
            response = self._sdk.messages.parse(
                model=self.model,
                max_tokens=ROUTER_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
            )
            parsed = response.parsed_output
        except Exception as exc:
            raise _fail(exc) from None
        if parsed is None:
            raise ProviderError(KeyStatus.PROVIDER_ERROR, "no structured output returned")
        return parsed

    def stream(
        self, system: str, messages: list[Message], max_tokens: int = ANSWER_MAX_TOKENS
    ) -> Iterator[str]:
        # Anthropic takes the system prompt as its own argument rather than a
        # message, and `effort` is not sent: the pinned Haiku model rejects it.
        payload = [{"role": m.role, "content": m.content} for m in messages]
        return self._iter_deltas(system, payload, max_tokens)

    def _iter_deltas(self, system: str, payload: list[dict], max_tokens: int) -> Iterator[str]:
        try:
            with self._sdk.messages.stream(
                model=self.model, max_tokens=max_tokens, system=system, messages=payload
            ) as stream:
                yield from stream.text_stream
        except Exception as exc:
            raise _fail(exc) from None


class GeminiAdapter(_BaseAdapter):
    provider = Provider.GEMINI

    def _build_sdk(self, api_key: str) -> Any:
        from google import genai

        return genai.Client(api_key=api_key)

    def _ping(self) -> None:
        self._sdk.models.generate_content(
            model=self.model,
            contents="hi",
            config={"max_output_tokens": KEY_VALIDATION_MAX_TOKENS},
        )

    def classify(self, prompt: str, schema: type[SchemaT]) -> SchemaT:
        try:
            response = self._sdk.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                    "max_output_tokens": ROUTER_MAX_TOKENS,
                },
            )
            parsed = response.parsed
        except Exception as exc:
            raise _fail(exc) from None
        if parsed is None:
            raise ProviderError(KeyStatus.PROVIDER_ERROR, "no structured output returned")
        return parsed

    def stream(
        self, system: str, messages: list[Message], max_tokens: int = ANSWER_MAX_TOKENS
    ) -> Iterator[str]:
        contents = "\n\n".join(m.content for m in messages)
        try:
            chunks = self._sdk.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config={"system_instruction": system, "max_output_tokens": max_tokens},
            )
        except Exception as exc:
            raise _fail(exc) from None
        return self._iter_deltas(chunks)

    @staticmethod
    def _iter_deltas(chunks: Any) -> Iterator[str]:
        try:
            for chunk in chunks:
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            raise _fail(exc) from None


_ADAPTERS: dict[Provider, type[_BaseAdapter]] = {
    Provider.OPENAI: OpenAIAdapter,
    Provider.CLAUDE: AnthropicAdapter,
    Provider.GEMINI: GeminiAdapter,
}


def make_client(
    provider: Provider, api_key: str, sdk_client: Any | None = None
) -> LLMClient:
    """Build an adapter for `provider`.

    Constructed per request from session state rather than cached, so one
    visitor's key can never be reused for another's question.

    `sdk_client` is a test seam: it replaces the real SDK so the adapters can be
    exercised without a key or a network call.
    """
    try:
        adapter_type = _ADAPTERS[provider]
    except KeyError:
        raise ValueError(f"unsupported provider: {provider}") from None
    return adapter_type(api_key, sdk_client=sdk_client)  # type: ignore[return-value]
