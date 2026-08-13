"""The three provider adapters must be interchangeable.

`rag/pipeline.py` is written against one interface and must not care which
provider a user picked, so every rule in contracts/provider-protocol.md is
checked against all three adapters with the same assertions.

No network: each adapter is built with a stub SDK client, so these tests need
no API key and cost nothing to run.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from pydantic import BaseModel

from rag.config import Provider
from rag.errors import KeyStatus, ProviderError
from rag.llm import ALL_PROVIDERS, Message, make_client

FAKE_KEY = "sk-proj-notarealkey000000000000000000000000000"


class Route(BaseModel):
    kind: str


@pytest.fixture(params=ALL_PROVIDERS, ids=lambda p: p.value)
def provider(request: pytest.FixtureRequest) -> Provider:
    return request.param


def test_every_provider_has_an_adapter(provider: Provider) -> None:
    client = make_client(provider, FAKE_KEY)
    assert client.provider is provider


def test_adapters_expose_the_whole_protocol(provider: Provider) -> None:
    client = make_client(provider, FAKE_KEY)
    for method in ("validate_key", "classify", "stream"):
        assert callable(getattr(client, method)), f"{provider.value} is missing {method}"


def test_validate_key_never_raises(provider: Provider) -> None:
    """The UI calls this before anything else; it must always return a status.

    An adapter that raises here would surface a stack trace instead of the
    plain-language message the key field is supposed to show (FR-009).
    """

    class Exploding:
        def __getattr__(self, _name: str):
            raise RuntimeError("transport is down")

    client = make_client(provider, FAKE_KEY, sdk_client=Exploding())
    status = client.validate_key()

    assert isinstance(status, KeyStatus)
    assert status is not KeyStatus.OK


def test_stream_yields_text_deltas(provider: Provider, stub_sdk) -> None:
    client = make_client(provider, FAKE_KEY, sdk_client=stub_sdk(deltas=["Hel", "lo"]))
    chunks = list(client.stream("system", [Message(role="user", content="hi")], max_tokens=50))

    assert "".join(chunks) == "Hello"
    assert all(isinstance(chunk, str) for chunk in chunks)


def test_stream_is_lazy_rather_than_buffered(provider: Provider, stub_sdk) -> None:
    """A generator that buffers defeats the point of streaming (FR-010)."""
    client = make_client(provider, FAKE_KEY, sdk_client=stub_sdk(deltas=["a", "b", "c"]))
    stream = client.stream("system", [Message(role="user", content="hi")], max_tokens=50)

    assert isinstance(stream, Iterator)
    assert next(iter(stream)) == "a"


def test_classify_returns_a_validated_schema_instance(provider: Provider, stub_sdk) -> None:
    client = make_client(provider, FAKE_KEY, sdk_client=stub_sdk(parsed={"kind": "pm_question"}))
    result = client.classify("classify this", Route)

    assert isinstance(result, Route)
    assert result.kind == "pm_question"


def test_classify_raises_provider_error_on_malformed_output(provider: Provider, stub_sdk) -> None:
    """Never hand back a half-parsed object — the router branches on this."""
    client = make_client(provider, FAKE_KEY, sdk_client=stub_sdk(parsed=None))
    with pytest.raises(ProviderError):
        client.classify("classify this", Route)


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("auth", KeyStatus.INVALID_KEY),
        ("rate_limit", KeyStatus.QUOTA_EXCEEDED),
        ("connection", KeyStatus.NETWORK_ERROR),
        ("server", KeyStatus.PROVIDER_ERROR),
    ],
)
def test_failures_map_onto_one_shared_taxonomy(
    provider: Provider, stub_sdk, failure: str, expected: KeyStatus
) -> None:
    """One set of user-facing messages regardless of which SDK failed."""
    client = make_client(provider, FAKE_KEY, sdk_client=stub_sdk(fails_with=failure))
    assert client.validate_key() is expected


def test_generation_is_bounded_by_max_tokens(provider: Provider, stub_sdk) -> None:
    """A runaway generation would spend the user's money past the $0.50 cap."""
    sdk = stub_sdk(deltas=["x"])
    client = make_client(provider, FAKE_KEY, sdk_client=sdk)
    list(client.stream("system", [Message(role="user", content="hi")], max_tokens=123))

    assert sdk.last_max_tokens == 123, "max_tokens must reach the provider call"


def test_classify_output_is_capped(provider: Provider, stub_sdk) -> None:
    sdk = stub_sdk(parsed={"kind": "off_topic"})
    client = make_client(provider, FAKE_KEY, sdk_client=sdk)
    client.classify("classify", Route)

    assert sdk.last_max_tokens is not None
    assert sdk.last_max_tokens <= 300, "routing calls must stay cheap"


def test_adapters_do_not_retry_after_output_has_been_generated(
    provider: Provider, stub_sdk
) -> None:
    """Retrying a partly-generated answer bills the user twice for one question."""
    sdk = stub_sdk(deltas=["partial"], fails_mid_stream=True)
    client = make_client(provider, FAKE_KEY, sdk_client=sdk)

    with pytest.raises(ProviderError):
        list(client.stream("system", [Message(role="user", content="hi")], max_tokens=50))

    assert sdk.call_count == 1, "a mid-stream failure must not be retried"
