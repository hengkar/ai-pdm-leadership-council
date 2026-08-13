# Contract: UI Surface (`app.py` ↔ `rag/`)

What the Gradio layer owes the user and what it may assume from the runtime packages. The UI
is a renderer: it holds no retrieval or prompting logic, and every answer byte it shows comes
from [pipeline-events](./pipeline-events.md). Layout rationale lives in research.md R13.

## Regions

| Region | Contents | Contract |
|---|---|---|
| Sidebar — setup | Provider selector, API-key field (masked), key status indicator | Key lives only in `gr.State`; never echoed back into the field's value, never in any label or log (FR-008) |
| Sidebar — roster | Expert list from `rag.roster.load()`, with source-kind hints | Shows exactly the experts with indexed material; council mode = all shown as participating, expert mode = single selection (FR-021, FR-003) |
| Main — empty state | Product framing + ~4 `ExamplePrompt` cards | Rendered before any provider call; clicking a card submits its `situation` verbatim as the user's question (FR-021) |
| Main — conversation | User turns + streamed answers, council sections rendered as Situation / Perspective / Recommended Actions | Text appended only from `AnswerDelta`; section structure comes from the model's markdown, not UI parsing (FR-004, FR-010) |
| Main — sources panel | One entry per `Citation` | 📄 title → original URL; 🎙 episode + mm:ss → timestamped link. Rendered only from the `Sources` event (FR-011) |
| Input bar | Question box, provider chip, submit | Submit disabled while no key is present; a fresh submit supersedes any in-flight answer (pipeline guarantee 4) |

## Session key lifecycle

Added after two bugs in this exact area reached a running app. Both came from
one unstated assumption: that the key *field* is the record of truth. It is not
— it is an input. The record of truth is session state.

| Trigger | Required behaviour |
|---|---|
| Key entered and accepted | Store in session state; clear the visible field so the value is not left in the DOM; enable asking |
| Validation handler fires with an **empty** field | **No change.** An empty input must never revoke a key already accepted — this is the direct consequence of clearing the field above, and the source of the "Key verified / API key problem" contradiction |
| A different key typed | Replace and re-validate |
| Provider changed | Discard the key and require a new one (FR-023); a key issued for one provider must never be sent to another |
| Same provider re-selected | No-op — must not cost the user their key |
| Session ends | Everything discarded (FR-008) |

The general rule: **only an explicit user action may invalidate an accepted
key.** Incidental UI events — focus changes, clicks elsewhere, re-render — must
leave it alone. Any handler wired to an incidental event (`blur`, `change`)
therefore needs to distinguish "the user cleared this" from "this happens to be
empty right now".

## Rules

1. **No business logic in `app.py`**: it may call `rag.pipeline.answer(...)`, `rag.roster.load()`,
   and read `ui_content`; it may not import `retrieve`, `rerank`, `router`, or `llm` directly.
   This keeps the flow testable headlessly against the event stream.
2. **Terminal events render distinctly**: `KeyProblem`, `OffTopic`, `CoverageGap`, and `Failure`
   each get their own visual treatment — never styled as a normal answer, so users can tell an
   honest gap from advice (FR-005, FR-012).
3. **Zero-cost surfaces**: empty state, roster, mode switching, and key entry trigger no
   provider call. The first billable call happens on question submit (Principle I, SC-008).
4. **Roster is never hardcoded**: expert names in the sidebar, the expert-mode selector, and
   router validation all come from `rag.roster` (see [data-schemas](./data-schemas.md) rule 5).
5. **Session isolation**: all mutable UI state is per-session `gr.State`; nothing about one
   visitor's session may leak into another's on the shared Space process.
