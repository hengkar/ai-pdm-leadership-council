# Contract: Runtime Pipeline Events (`rag/pipeline.py` → `app.py`)

The runtime pipeline is a generator; the Gradio layer is a dumb renderer of its events. This
keeps `app.py` logic-free and the whole flow testable headlessly (integration tests consume
the same events the UI does).

## Entry point

```python
def answer(question: str, mode: Mode, selected_expert: str | None,
           session: SessionState) -> Iterator[PipelineEvent]
```

`Mode ∈ {council, expert}`; `selected_expert` required iff mode == expert.

## Event taxonomy (in emission order)

| Event | Payload | UI rendering |
|---|---|---|
| `KeyProblem` | `KeyStatus` | plain-language error, how to fix; **terminal** |
| `OffTopic` | short scope message | scope reply bubble; **terminal** (FR-012, SC-008) |
| `Routed` | `Route` | status line ("asking the council…" / "asking {expert}…") |
| `CoverageGap` | mode, expert(s) checked | honest gap message; **terminal** (FR-005) |
| `AnswerDelta` | text delta | append to streaming answer bubble (FR-010) |
| `Sources` | list[Citation] | sources panel: 📄 title→url / 🎙 episode (mm:ss)→deep-link (FR-011) |
| `Failure` | scrubbed `ProviderError` | error + retry hint; partial answer marked incomplete |
| `Done` | token usage summary | (optional) subtle cost hint |

## Guarantees

1. Exactly one terminal outcome per call: (`AnswerDelta`* → `Sources` → `Done`) or one of
   `KeyProblem` / `OffTopic` / `CoverageGap` / `Failure`.
2. `Sources` lists only chunks whose content contributed to the prompt of the generated
   answer — citations are constructed from `RetrievalResult`s, never parsed from model text.
3. No event payload ever contains the API key or raw provider exception text.
4. A new `answer()` call for the same session supersedes any in-flight one; the superseded
   generator is closed (stops streaming, makes no further provider calls).
5. First event MUST be emitted within 10 s (router timeout); `AnswerDelta` flow targets
   first-token <5 s after `Routed` (SC-007).
