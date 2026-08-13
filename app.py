"""AI PDM Leadership Council — Gradio entry point.

A renderer, deliberately. It collects the user's provider and key, forwards
questions to `rag.pipeline.answer`, and displays the events that come back. All
retrieval and prompting logic lives in `rag/`, so the whole flow stays testable
without a browser (see contracts/ui-contract.md).

The key lives in per-session `gr.State` and nowhere else — not in a file, not in
a module global, and never written back into the textbox it came from
(constitution Principle I).

    .venv/bin/python app.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

import gradio as gr

import rag
import ui_content
from rag import roster
from rag.config import (
    DEFAULT_PROVIDER,
    ENABLED_PROVIDERS,
    PROVIDER_KEY_URLS,
    PROVIDER_LABELS,
    PROVIDER_MODELS,
    Mode,
    Provider,
)
from rag.errors import KEY_STATUS_MESSAGES, KeyStatus, install_log_scrubbing
from rag.llm import make_client
from rag.pipeline import EventType, answer

install_log_scrubbing()

# Built from ENABLED_PROVIDERS rather than every known label, so a withheld
# provider cannot be reached by editing the page or replaying an old request:
# an unrecognised label falls back to the default instead.
_LABEL_TO_PROVIDER = {PROVIDER_LABELS[p]: p for p in ENABLED_PROVIDERS}
COUNCIL_LABEL = "Ask the Council"
EXPERT_LABEL = "Ask an Expert"


@dataclass
class SessionState:
    """One visitor's session. Dies with the browser tab."""

    provider: Provider = DEFAULT_PROVIDER
    api_key: str = ""
    key_status: KeyStatus | None = None
    history: list[dict[str, str]] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return self.key_status is KeyStatus.OK

    def __repr__(self) -> str:  # keep the key out of any Gradio debug output
        return f"<SessionState provider={self.provider.value} ready={self.is_ready}>"


# --- key handling -----------------------------------------------------------


def connect(provider_label: str, api_key: str, state: SessionState | None):
    """Validate the key on an explicit Connect (FR-009, FR-022).

    Connecting is a deliberate act, not something inferred from focus moving.
    An earlier version validated on `blur`, which meant that clearing the field
    after a successful check — done so the key is not left in the DOM — caused
    the next incidental blur to arrive empty and revoke a perfectly good key.
    Binding to a button removes that entire class of failure: nothing happens to
    the key unless the user asks for it to.
    """
    state = state or SessionState()
    state.provider = _LABEL_TO_PROVIDER.get(provider_label, DEFAULT_PROVIDER)
    typed = (api_key or "").strip()

    if not typed:
        # Guard anyway: an empty submission must never downgrade a live key.
        return (
            state,
            _status_html(state.key_status),
            gr.update(interactive=state.is_ready),
            "",
        )

    state.api_key = typed
    state.key_status = make_client(state.provider, state.api_key).validate_key()

    return (
        state,
        _status_html(state.key_status, state.provider),
        gr.update(interactive=state.is_ready),
        "",  # clear the visible field; the value lives on in session state
    )


def disconnect(state: SessionState | None):
    """Drop the key on request, so 'connected' is reversible without a reload."""
    state = state or SessionState()
    state.api_key = ""
    state.key_status = None
    return state, _status_html(None), gr.update(interactive=False), ""


def switch_provider(provider_label: str, state: SessionState | None):
    """Changing provider invalidates the key — one provider's key is not another's.

    Without this the dropdown could read "Anthropic" while the session quietly
    kept using the previously validated OpenAI key.
    """
    state = state or SessionState()
    provider = _LABEL_TO_PROVIDER.get(provider_label, DEFAULT_PROVIDER)

    if provider is not state.provider:
        state.provider = provider
        state.api_key = ""
        state.key_status = None

    return (
        state,
        gr.update(value=_key_link(provider_label)),
        _status_html(state.key_status),
        gr.update(interactive=state.is_ready),
    )


def _status_html(status: KeyStatus | None, provider: Provider | None = None) -> str:
    if status is None:
        return "<span style='opacity:.6'>Not connected — paste a key and press Connect.</span>"
    if status is KeyStatus.OK:
        who = f" to {PROVIDER_LABELS[provider]}" if provider else ""
        return (f"<span style='color:#1a7f37'><strong>Connected{who}.</strong> "
                "Your key is held for this session only.</span>")
    return f"<span style='color:#b3261e'>{KEY_STATUS_MESSAGES[status]}</span>"


# --- conversation -----------------------------------------------------------

_NOTICE_STYLES = {
    EventType.OFF_TOPIC: ("#6b7280", "Outside the council's scope"),
    EventType.COVERAGE_GAP: ("#b45309", "Not enough published material"),
    EventType.FAILURE: ("#b3261e", "Something went wrong"),
    EventType.KEY_PROBLEM: ("#b3261e", "API key problem"),
}


def _notice(event_type: EventType, text: str) -> str:
    """Render a terminal outcome so it cannot be mistaken for advice.

    A coverage gap or an error styled like a normal answer would read as the
    council's opinion; these are explicitly not that (contracts/ui-contract.md).
    """
    colour, heading = _NOTICE_STYLES[event_type]
    return (
        f"<div style='border-left:3px solid {colour}; padding:.5rem .85rem; opacity:.95'>"
        f"<strong style='color:{colour}'>{heading}</strong><br>{text}</div>"
    )


def _sources_html(citations) -> str:
    if not citations:
        return ""
    rows = "".join(
        f"<li style='margin:.3rem 0'><a href='{c.link}' target='_blank' "
        f"rel='noopener noreferrer'>{c.display}</a></li>"
        for c in citations
    )
    return (
        "<div style='font-size:.9rem'><strong>Sources</strong>"
        f"<ul style='margin:.4rem 0 0; padding-left:1.1rem'>{rows}</ul></div>"
    )


def respond(question: str, mode_label: str, expert_choice: str, state: SessionState | None):
    """Stream one answer, yielding progressively so text appears as it arrives."""
    state = state or SessionState()
    question = (question or "").strip()

    if not question:
        yield state, state.history, "", ""
        return
    if not state.is_ready:
        history = state.history + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": _notice(
                EventType.KEY_PROBLEM, "Add a valid API key in the sidebar to ask the council."
            )},
        ]
        state.history = history
        yield state, history, "", ""
        return

    mode = Mode.EXPERT if mode_label == EXPERT_LABEL else Mode.COUNCIL
    selected = expert_choice if mode is Mode.EXPERT and expert_choice else None

    history = state.history + [{"role": "user", "content": question}, {"role": "assistant", "content": ""}]
    yield state, history, "", ""

    client = make_client(state.provider, state.api_key)
    answer_text = ""
    sources = ""

    for event in answer(question, client, mode=mode, selected_expert=selected):
        if event.type is EventType.ANSWER_DELTA:
            answer_text += event.text
            history[-1]["content"] = answer_text
        elif event.type is EventType.SOURCES:
            sources = _sources_html(event.citations)
        elif event.type in _NOTICE_STYLES:
            history[-1]["content"] = _notice(event.type, event.text)
        elif event.type is EventType.DONE:
            continue
        yield state, history, sources, ""

    state.history = history
    yield state, history, sources, ""


def _roster_summary() -> str:
    entries = roster.load()
    if not entries:
        return "no indexed experts yet — build the index first"
    names = ", ".join(entry.name for entry in entries)
    works = sum(entry.work_count for entry in entries)
    return f"{len(entries)} product leaders ({works} works): {names}"


def _roster_markdown() -> str:
    entries = roster.load()
    if not entries:
        return "_No index found. Run the data pipeline to build the council._"
    return "\n".join(
        f"- {e.source_hint} **{e.name}** · {e.work_count} works" for e in entries
    )


# --- layout -----------------------------------------------------------------


def build_ui() -> gr.Blocks:
    # Load the local models before serving. Left lazy, the ~27s cost lands on
    # the first question and breaks the five-second first-token budget.
    rag.warmup()
    experts = roster.names()

    with gr.Blocks(title="AI PDM Leadership Council", fill_height=True) as demo:
        # No default value: Gradio serialises a State's default into the page
        # config, so a credential-holding object must never be seeded here.
        state = gr.State()

        gr.Markdown(f"# 🏛 AI PDM Leadership Council\n{ui_content.TAGLINE}")

        with gr.Row():
            with gr.Column(scale=1, min_width=270):
                gr.Markdown("### Setup")
                provider_picker = gr.Dropdown(
                    choices=[PROVIDER_LABELS[p] for p in ENABLED_PROVIDERS],
                    value=PROVIDER_LABELS[DEFAULT_PROVIDER],
                    label="AI provider",
                    info=None if len(ENABLED_PROVIDERS) > 1 else
                    "Gemini and Claude are temporarily unavailable.",
                )
                key_box = gr.Textbox(
                    label="API key", type="password", placeholder="sk-…",
                    info="Nothing is sent until you press Connect.",
                )
                with gr.Row():
                    connect_btn = gr.Button("Connect", variant="primary", size="sm")
                    disconnect_btn = gr.Button("Disconnect", size="sm")
                key_link = gr.Markdown(_key_link(PROVIDER_LABELS[DEFAULT_PROVIDER]))
                status = gr.HTML(_status_html(None))
                gr.Markdown(f"<small>{ui_content.KEY_NOTE}</small>")

                gr.Markdown("### Mode")
                mode_picker = gr.Radio(
                    choices=[COUNCIL_LABEL, EXPERT_LABEL],
                    value=COUNCIL_LABEL,
                    label=None,
                    show_label=False,
                )
                expert_picker = gr.Dropdown(
                    choices=experts,
                    value=experts[0] if experts else None,
                    label="Expert",
                    visible=False,
                )
                gr.Markdown("### The council")
                gr.Markdown(_roster_markdown())

            with gr.Column(scale=3):
                empty_state = gr.HTML(ui_content.empty_state_html(_roster_summary()))
                with gr.Row():
                    example_buttons = [
                        gr.Button(example.title, size="sm") for example in ui_content.EXAMPLES
                    ]
                # allow_tags is pinned rather than left to the default, which
                # flips to True in Gradio 6: answers are model output, and
                # anything that looks like a tag should stay text, not render.
                chat = gr.Chatbot(
                    type="messages",
                    height=430,
                    label=None,
                    show_label=False,
                    allow_tags=False,
                )
                sources = gr.HTML()
                question = gr.Textbox(
                    placeholder="Describe your situation…",
                    show_label=False,
                    lines=2,
                )
                submit = gr.Button("Ask the council", variant="primary", interactive=False)

        # --- wiring ---
        provider_picker.change(
            switch_provider, [provider_picker, state], [state, key_link, status, submit]
        )
        key_inputs = [provider_picker, key_box, state]
        key_outputs = [state, status, submit, key_box]
        connect_btn.click(connect, key_inputs, key_outputs)
        key_box.submit(connect, key_inputs, key_outputs)  # Enter is an explicit act too
        disconnect_btn.click(disconnect, [state], key_outputs)

        mode_picker.change(
            lambda label: gr.update(visible=label == EXPERT_LABEL), mode_picker, expert_picker
        )

        outputs = [state, chat, sources, question]
        inputs = [question, mode_picker, expert_picker, state]
        submit.click(respond, inputs, outputs).then(
            lambda: gr.update(visible=False), None, empty_state
        )
        question.submit(respond, inputs, outputs).then(
            lambda: gr.update(visible=False), None, empty_state
        )

        # An example card fills the box and asks in one click (FR-021).
        for button, example in zip(example_buttons, ui_content.EXAMPLES):
            button.click(lambda s=example.situation: s, None, question).then(
                respond, inputs, outputs
            ).then(lambda: gr.update(visible=False), None, empty_state)

    return demo


def _key_link(provider_label: str) -> str:
    provider = _LABEL_TO_PROVIDER.get(provider_label, DEFAULT_PROVIDER)
    return (
        f"<small>Get a key: [{PROVIDER_LABELS[provider]}]({PROVIDER_KEY_URLS[provider]}) "
        f"· uses `{PROVIDER_MODELS[provider]}`</small>"
    )


if __name__ == "__main__":
    build_ui().launch()
