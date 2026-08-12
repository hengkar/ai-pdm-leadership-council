# Contract: LLM Provider Protocol (`rag/llm.py`)

The single seam between the app and the three AI providers. Every adapter (OpenAI, Gemini,
Claude) MUST satisfy this contract; contract tests in `tests/contract/` run against all three
with a fake/recorded transport.

## Protocol

```python
class LLMClient(Protocol):
    provider: ProviderName                    # "openai" | "gemini" | "claude"

    def validate_key(self) -> KeyStatus:
        """Minimal-cost ping (~1 token). Returns ok | invalid_key | quota_exceeded |
        provider_error(msg). MUST be called before first real use; MUST NOT raise."""

    def classify(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """Structured output via the provider's tool/function-calling mode.
        Used by the router. MUST return a validated instance of `schema`;
        on provider failure raises ProviderError (never returns malformed data)."""

    def stream(self, system: str, messages: list[Message],
               max_tokens: int) -> Iterator[str]:
        """Yields text deltas. MUST begin yielding or raise within 10 s.
        Raises ProviderError mid-stream on failure; already-yielded text stands."""
```

## Construction

`make_client(provider: ProviderName, api_key: str) -> LLMClient` — built per request from
session state. Model ids are fixed constants per provider (cheap tier): OpenAI `gpt-4o-mini`,
Gemini `gemini-2.0-flash`, Anthropic `claude-haiku` (current alias pinned in one constants
block).

## Hard rules (contract-tested)

1. **Key hygiene**: the key appears in no `__repr__`, no exception message, no log record.
   `ProviderError` messages are scrubbed before surfacing.
2. **No retries that spend**: at most one automatic retry, and only for transport errors —
   never after tokens were generated.
3. **Cost bounds**: `classify` calls capped at ~300 output tokens; `stream` capped by
   `max_tokens` (default 900). No other billable calls exist in the runtime path.
4. **Uniform errors**: all three adapters map provider-specific failures to the same
   `KeyStatus` / `ProviderError` taxonomy so the UI renders one set of plain-language messages
   (FR-009).
