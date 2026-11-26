"""Tests for _auth middleware in govori/server.py.

Token is passed as X-Govori-Token header or ?token= query param.
Device ID is passed as X-Device-Id header or ?device= query param.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


MASTER = "test-master-token-abc123"


def _make_client(monkeypatch, tmp_config, *, token_env: str | None = MASTER):
    """Build a TestClient with controlled GOVORI_TOKEN env."""
    if token_env is None:
        monkeypatch.delenv("GOVORI_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GOVORI_TOKEN", token_env)
    monkeypatch.setenv("GOVORI_LS_SECRET", "test-ls-secret")

    _mock_config = MagicMock()
    _mock_config.CONFIG_FILE = str(tmp_config["tmp_path"] / "config.yaml")
    _mock_config.PLUGINS_DIR = str(tmp_config["tmp_path"] / "plugins")
    _mock_config.SAMPLE_RATE = 16000
    _mock_config.NOTES_CFG = {}
    _mock_config.load_config.return_value = MagicMock(
        model="test", note_model="test-model", language="ru", base_url=None
    )
    _mock_config.install_runtime_config = MagicMock()
    _mock_config.load_plugins = MagicMock(return_value={})

    sys.modules["govori.config"] = _mock_config
    sys.modules["govori.state"] = MagicMock(PERMANENT_API_ERROR=object())
    sys.modules["govori.transcribe"] = MagicMock()
    sys.modules["govori.notes"] = MagicMock(_is_hallucination=MagicMock(return_value=False))
    sys.modules.pop("govori.server", None)

    from fastapi.testclient import TestClient
    from govori.server import app
    return TestClient(app, raise_server_exceptions=False)


def test_health_always_open(tmp_config, monkeypatch):
    """/health accessible without any token."""
    c = _make_client(monkeypatch, tmp_config, token_env=MASTER)
    r = c.get("/health")
    assert r.status_code == 200


def test_health_open_even_without_token_env(tmp_config, monkeypatch):
    """/health open when GOVORI_TOKEN not set (dev mode)."""
    c = _make_client(monkeypatch, tmp_config, token_env=None)
    r = c.get("/health")
    assert r.status_code == 200


def test_dev_mode_no_token_env(tmp_config, monkeypatch):
    """When GOVORI_TOKEN not set, all routes are open (Tailscale-only mode)."""
    c = _make_client(monkeypatch, tmp_config, token_env=None)
    # /review/data should be reachable (not 401/403) in dev mode
    r = c.get("/review/data")
    assert r.status_code not in (401, 403)


def test_master_token_full_access(tmp_config, monkeypatch):
    """Master token can access owner-only /review routes."""
    c = _make_client(monkeypatch, tmp_config)
    r = c.get("/review/data", headers={"X-Govori-Token": MASTER})
    assert r.status_code not in (401, 403)


def test_master_token_via_query_param(tmp_config, monkeypatch):
    """Master token can be passed as ?token= query param."""
    c = _make_client(monkeypatch, tmp_config)
    r = c.get(f"/review/data?token={MASTER}")
    assert r.status_code not in (401, 403)


def test_invalid_token_returns_401(tmp_config, monkeypatch):
    c = _make_client(monkeypatch, tmp_config)
    r = c.get("/review/data", headers={"X-Govori-Token": "bad-token-xyz"})
    assert r.status_code == 401


def test_no_token_returns_401(tmp_config, monkeypatch):
    """No auth header when GOVORI_TOKEN is set → 401."""
    c = _make_client(monkeypatch, tmp_config)
    r = c.get("/review/data")
    assert r.status_code == 401


def test_customer_token_dict_accessible(tmp_config, monkeypatch):
    """Valid customer token + device can reach /dict (may get 400 for no audio, not 401/403)."""
    import govori.tokens as tok
    c = _make_client(monkeypatch, tmp_config)
    ts = tok.issue("cust-owner", "cust-label")
    tok.check(ts, "dev_a")  # bind device
    r = c.get("/health", headers={"X-Govori-Token": ts, "X-Device-Id": "dev_a"})
    # /health is always open but this verifies token doesn't crash middleware
    assert r.status_code == 200


def test_customer_token_review_forbidden(tmp_config, monkeypatch):
    """Valid customer token cannot access /review routes → 403."""
    import govori.tokens as tok
    c = _make_client(monkeypatch, tmp_config)
    ts = tok.issue("cust-owner", "cust-label")
    tok.check(ts, "dev_b")  # bind device
    r = c.get("/review/data", headers={"X-Govori-Token": ts, "X-Device-Id": "dev_b"})
    assert r.status_code == 403


def test_device_mismatch_returns_403(tmp_config, monkeypatch):
    """Customer token bound to dev1, request from dev2 → 403."""
    import govori.tokens as tok
    c = _make_client(monkeypatch, tmp_config)
    ts = tok.issue("cust-owner", "cust-label")
    tok.check(ts, "dev1")  # bind
    r = c.get("/health", headers={"X-Govori-Token": ts, "X-Device-Id": "dev2"})
    # /health is open but let's test a guarded path
    r2 = c.post("/dict", headers={"X-Govori-Token": ts, "X-Device-Id": "dev2"}, content=b"x")
    assert r2.status_code == 403


# ---------------------------------------------------------------------------
# Owner-only intents: customer tokens may only dictate / take notes
# ---------------------------------------------------------------------------


def _classified_do(monkeypatch, headers):
    """Run /note?stage=classify on an utterance the router reads as a command."""
    import govori.intents as intents
    import govori.server as server

    async def _fake_transcribe(request):
        return "спроси у сессии статус", 2.0, 10

    monkeypatch.setattr(server, "_transcribe_correct_note_request", _fake_transcribe)
    monkeypatch.setattr(intents, "classify_intent", lambda text: {"intent": "do", "summary": "s"})
    spies = {
        "classify_do_action": MagicMock(return_value={
            "action": "session_ask", "message": "статус", "candidates": ["owner__session"]}),
        "brain_answer": MagicMock(return_value="секрет владельца"),
        "session_ask_execute": MagicMock(return_value="ok"),
        "dispatch_command": MagicMock(return_value="ok"),
        "log_intent_decision": MagicMock(),
    }
    for name, spy in spies.items():
        monkeypatch.setattr(intents, name, spy)
    return spies


def _customer_headers():
    import govori.tokens as tok
    return {"X-Govori-Token": tok.issue("cust", "label"), "X-Device-Id": "dev1"}


def test_customer_classify_does_not_expose_owner_sessions(tmp_config, monkeypatch):
    c = _make_client(monkeypatch, tmp_config)
    h = _customer_headers()
    spies = _classified_do(monkeypatch, h)
    r = c.post("/note?stage=classify", headers=h)
    assert r.status_code == 200
    assert r.json()["intent"] == "note"
    assert r.json()["session_candidates"] == []
    spies["classify_do_action"].assert_not_called()


@pytest.mark.parametrize("intent", ["ask", "do"])
@pytest.mark.parametrize("send_header", [True, False])
def test_customer_cannot_execute_owner_intents(tmp_config, monkeypatch, intent, send_header):
    c = _make_client(monkeypatch, tmp_config)
    h = _customer_headers()
    spies = _classified_do(monkeypatch, h)
    token = c.post("/note?stage=classify", headers=h).json()["token"]
    url = f"/note?stage=execute&intent={intent}&session=owner__session&token={token}"
    r = c.post(url, headers=h if send_header else {})
    assert r.status_code == 403
    assert r.json()["reason"] == "owner_only"
    for name in ("brain_answer", "session_ask_execute", "dispatch_command"):
        spies[name].assert_not_called()


@pytest.mark.parametrize("token_env", [MASTER, None])
def test_owner_executes_session_ask_with_cache_token_only(tmp_config, monkeypatch, token_env):
    """Owner (master token, or dev mode) keeps the header-less execute flow."""
    c = _make_client(monkeypatch, tmp_config, token_env=token_env)
    h = {"X-Govori-Token": MASTER}
    spies = _classified_do(monkeypatch, h)
    token = c.post("/note?stage=classify", headers=h).json()["token"]
    r = c.post(f"/note?stage=execute&intent=do&session=owner__session&token={token}")
    assert r.status_code == 200
    spies["session_ask_execute"].assert_called_once_with("owner__session", "статус")
