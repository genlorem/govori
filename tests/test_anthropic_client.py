"""Anthropic client: OAuth subscription token preferred over pay-as-you-go key."""
import importlib.util
from pathlib import Path
from unittest import mock

import pytest

# test_server.py swaps sys.modules["govori.notes"] for a mock at import time;
# load the real module from its file so the order of test files does not matter.
_spec = importlib.util.spec_from_file_location(
    "govori._notes_under_test", Path(__file__).parent.parent / "govori" / "notes.py")
notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(notes)


@pytest.fixture(autouse=True)
def _reset():
    notes._anthropic_client = None
    yield
    notes._anthropic_client = None


def test_oauth_token_preferred_and_identity_prepended(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_OAUTH_TOKEN", "oauth-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-x")
    with mock.patch.object(notes, "Anthropic") as A:
        client = notes._get_anthropic_client()
        kwargs = A.call_args.kwargs
        assert kwargs["auth_token"] == "oauth-x"
        assert kwargs["api_key"] is None
        assert kwargs["default_headers"]["anthropic-beta"] == "oauth-2025-04-20"
        client.messages.create(model="m", max_tokens=1, system="router", messages=[])
        sent = A.return_value.messages.create.call_args.kwargs["system"]
        assert sent[0]["text"] == notes.CLAUDE_CODE_IDENTITY
        assert sent[1] == {"type": "text", "text": "router"}


def test_api_key_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-x")
    with mock.patch.object(notes, "Anthropic") as A:
        client = notes._get_anthropic_client()
        A.assert_called_once_with(api_key="key-x")
        assert client is A.return_value


def test_nothing_configured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with mock.patch.object(notes, "Anthropic"):
        assert notes._get_anthropic_client() is None
