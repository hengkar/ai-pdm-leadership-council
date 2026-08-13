"""The user's API key must not escape the adapter.

A key passes through this process on every request. Provider SDKs sometimes
echo request context into exception messages, and a key that reaches a log file
or an error bubble on screen is compromised — so these tests hunt for it in
every channel an adapter can write to (constitution Principle I).
"""

from __future__ import annotations

import logging

import pytest

from rag.config import Provider
from rag.errors import ProviderError, install_log_scrubbing, scrub
from rag.llm import ALL_PROVIDERS, Message, make_client

# Shaped like a real key so the scrubber's patterns are genuinely exercised.
SECRET = "sk-proj-abcdefghijklmnop1234567890ABCDEFGHIJKLMNOP"


@pytest.fixture(params=ALL_PROVIDERS, ids=lambda p: p.value)
def provider(request: pytest.FixtureRequest) -> Provider:
    return request.param


def test_key_is_absent_from_repr_and_str(provider: Provider) -> None:
    client = make_client(provider, SECRET)
    assert SECRET not in repr(client)
    assert SECRET not in str(client)


def test_key_is_absent_from_the_adapters_public_attributes(provider: Provider) -> None:
    """Anything printable on the object is a leak path — Gradio renders state."""
    client = make_client(provider, SECRET)
    for name in dir(client):
        if name.startswith("_"):
            continue
        value = getattr(client, name, None)
        if isinstance(value, str):
            assert SECRET not in value, f"key exposed via .{name}"


def test_key_is_absent_from_error_messages(provider: Provider, stub_sdk) -> None:
    """SDKs sometimes interpolate request context, key included, into errors."""

    class LeakyTransport:
        def __getattr__(self, _name: str):
            raise RuntimeError(f"request failed with Authorization: Bearer {SECRET}")

    client = make_client(provider, SECRET, sdk_client=LeakyTransport())

    client.validate_key()  # must not raise

    with pytest.raises(ProviderError) as caught:
        client.classify("x", _Schema)
    assert SECRET not in str(caught.value)
    assert SECRET not in caught.value.message
    assert SECRET not in repr(caught.value)


def test_key_is_absent_from_log_records(provider: Provider, caplog) -> None:
    install_log_scrubbing()

    class LeakyTransport:
        def __getattr__(self, _name: str):
            raise RuntimeError(f"boom key={SECRET}")

    client = make_client(provider, SECRET, sdk_client=LeakyTransport())
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("rag.llm").error("failure while calling provider: key=%s", SECRET)
        client.validate_key()

    for record in caplog.records:
        assert SECRET not in record.getMessage(), "key reached a log record"


def test_scrubber_redacts_every_supported_provider_key_shape() -> None:
    for shape in (
        "sk-proj-abcdefghijklmnop1234567890",
        "sk-ant-api03-abcdefghijklmnop1234567890",
        "AIzaSyD-abcdefghijklmnop1234567890",
    ):
        assert shape not in scrub(f"failed with {shape} at boundary")


class _Schema(__import__("pydantic").BaseModel):
    kind: str = "x"
