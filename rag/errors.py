"""Shared error taxonomy and API-key scrubbing.

All three provider adapters map their own failures onto the types here, so the
UI renders one set of plain-language messages regardless of provider (FR-009).

The scrubber exists because a user's API key passes through this process on
every request. Provider SDKs sometimes echo request context into exception
messages, and an unscrubbed message can end up in a log file or on screen — so
every message that leaves an adapter goes through `scrub()` first
(constitution Principle I).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

# Key shapes across the three supported providers:
#   OpenAI     sk-... / sk-proj-...
#   Anthropic  sk-ant-...
#   Gemini     AIza...
# Deliberately greedy on length: over-redacting a log line is harmless, leaking
# a key is not.
_KEY_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{16,}"),
)

REDACTED = "[REDACTED]"


def scrub(text: str) -> str:
    """Replace anything key-shaped in `text` with a placeholder."""
    for pattern in _KEY_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


class KeyStatus(str, Enum):
    """Outcome of validating a user-supplied key."""

    OK = "ok"
    INVALID_KEY = "invalid_key"
    QUOTA_EXCEEDED = "quota_exceeded"
    PROVIDER_ERROR = "provider_error"
    NETWORK_ERROR = "network_error"


#: Shown to the user verbatim. No provider jargon, and each one says what to do.
KEY_STATUS_MESSAGES: dict[KeyStatus, str] = {
    KeyStatus.OK: "Key verified.",
    KeyStatus.INVALID_KEY: (
        "That API key was rejected. Check that you copied the whole key and that "
        "it belongs to the provider selected above."
    ),
    KeyStatus.QUOTA_EXCEEDED: (
        "That key is out of quota or has hit a rate limit. Check your billing "
        "with the provider, or try again in a moment."
    ),
    KeyStatus.PROVIDER_ERROR: (
        "The AI provider returned an error. This is usually temporary — please "
        "try again."
    ),
    KeyStatus.NETWORK_ERROR: (
        "Could not reach the AI provider. Check your connection and try again."
    ),
}


@dataclass(frozen=True)
class ProviderError(Exception):
    """A provider call failed. `message` is always already scrubbed."""

    status: KeyStatus
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", scrub(self.message))

    @property
    def user_message(self) -> str:
        return KEY_STATUS_MESSAGES[self.status]

    def __str__(self) -> str:
        return self.message


class _ScrubbingFilter(logging.Filter):
    """Scrub formatted log records before they reach any handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:  # a broken format string must not break logging
            return True
        cleaned = scrub(rendered)
        if cleaned != rendered:
            record.msg = cleaned
            record.args = ()
        return True


def install_log_scrubbing() -> None:
    """Attach the scrubbing filter to the root logger and its handlers.

    Called once at application startup, before any provider client is built.
    """
    root = logging.getLogger()
    log_filter = _ScrubbingFilter()
    if not any(isinstance(f, _ScrubbingFilter) for f in root.filters):
        root.addFilter(log_filter)
    for handler in root.handlers:
        if not any(isinstance(f, _ScrubbingFilter) for f in handler.filters):
            handler.addFilter(log_filter)
