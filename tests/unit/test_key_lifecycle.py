"""Session key lifecycle in the UI layer (FR-022, FR-023; US3 scenarios 4-5).

These cover bugs found by using the running app, not by reasoning about it —
the kind that only appear once real browser events fire in sequence, which is
why 155 passing tests missed them. The behaviour they pin down is specified in
contracts/ui-contract.md under "Session key lifecycle".
"""

from __future__ import annotations

import pytest

import app
from rag.config import ENABLED_PROVIDERS, PROVIDER_LABELS, Provider
from rag.errors import KeyStatus


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch):
    """Accept any non-empty key without calling a provider."""

    class Stub:
        def validate_key(self) -> KeyStatus:
            return KeyStatus.OK

    monkeypatch.setattr(app, "make_client", lambda provider, key: Stub())


def _validated() -> app.SessionState:
    state, _, _, _ = app.connect("OpenAI", "sk-proj-valid000000000000000", None)
    assert state.is_ready
    return state


def test_an_empty_submission_never_revokes_a_live_key() -> None:
    """FR-022 / US3 scenario 4 — the reported bug.

    Validation clears the visible field for hygiene. When that was wired to
    `blur`, the next incidental focus change arrived with an empty box and
    revoked a perfectly good key. Validation is now bound to an explicit
    Connect, and this guard keeps the empty case harmless regardless.
    """
    state = _validated()

    state, _, submit, _ = app.connect("OpenAI", "", state)

    assert state.is_ready, "an empty box must not revoke an already-validated key"
    assert submit.get("interactive") is True


def test_the_field_is_cleared_but_the_key_is_retained() -> None:
    """FR-008 (never echoed back) and FR-022 (still usable) together."""
    state, _, _, field_value = app.connect("OpenAI", "sk-proj-valid000000000000000", None)

    assert field_value == "", "the key must not be echoed back into the DOM"
    assert state.api_key, "but it must still be usable from session state"


def test_typing_a_new_key_replaces_the_old_one() -> None:
    state = _validated()
    state, _, _, _ = app.connect("OpenAI", "sk-proj-different0000000000", state)

    assert state.api_key.endswith("different0000000000")
    assert state.is_ready


def test_switching_provider_revokes_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-023 / US3 scenario 5 — a key for one provider is not valid for another.

    Without this the dropdown could read "Anthropic" while the session quietly
    kept using the validated OpenAI key.

    The provider table is restored for this test rather than using whatever
    ENABLED_PROVIDERS currently ships. Withholding a provider from the UI is a
    presentation decision, and it must not quietly retire the revocation
    guarantee that has to hold the moment one is offered again.
    """
    monkeypatch.setitem(app._LABEL_TO_PROVIDER, "Anthropic Claude", Provider.CLAUDE)

    state = _validated()
    assert state.provider is Provider.OPENAI

    state, _, _, submit = app.switch_provider("Anthropic Claude", state)

    assert state.provider is Provider.CLAUDE
    assert state.api_key == ""
    assert state.is_ready is False
    assert submit.get("interactive") is False


def test_reselecting_the_same_provider_keeps_the_key() -> None:
    """FR-022: only an explicit change may cost the user their key."""
    state = _validated()
    state, _, _, submit = app.switch_provider("OpenAI", state)

    assert state.is_ready, "a no-op change must not cost the user their key"
    assert submit.get("interactive") is True


def test_asking_without_a_key_never_reaches_a_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _boom(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("no provider call may happen without a key")

    monkeypatch.setattr(app, "answer", _boom)
    updates = list(app.respond("a question", app.COUNCIL_LABEL, "", None))

    assert not called
    assert "API key" in updates[-1][1][-1]["content"]


def test_disconnect_clears_the_key_on_request() -> None:
    """Connecting must be reversible without reloading the page."""
    state = _validated()
    state, _, submit, field = app.disconnect(state)

    assert state.api_key == ""
    assert state.is_ready is False
    assert submit.get("interactive") is False
    assert field == ""


def test_connect_is_the_only_path_that_validates() -> None:
    """No incidental event may touch the key (contracts/ui-contract.md).

    Binding validation to focus changes is what caused the original defect, so
    the absence of that wiring is worth asserting rather than trusting.
    """
    source = open("app.py", encoding="utf-8").read()
    assert "key_box.blur" not in source, "validation must not hang off blur"
    assert "connect_btn.click(connect" in source


def test_withheld_providers_cannot_be_selected() -> None:
    """A provider absent from ENABLED_PROVIDERS must be unreachable, not merely
    hidden.

    The dropdown is client-side, so an edited page or a replayed request can
    still submit any label. Resolution has to reject a withheld provider rather
    than trusting the widget to have limited the choice.
    """
    for provider in Provider:
        label = PROVIDER_LABELS[provider]
        if provider in ENABLED_PROVIDERS:
            assert app._LABEL_TO_PROVIDER[label] is provider
        else:
            assert label not in app._LABEL_TO_PROVIDER, (
                f"{label} is withheld but still resolvable"
            )


def test_a_forged_provider_label_falls_back_to_an_enabled_one() -> None:
    state, _, _, _ = app.switch_provider("Anthropic Claude", None)
    assert state.provider in ENABLED_PROVIDERS
