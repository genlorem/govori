"""Unit tests for govori.session_control — the session-manager HTTP client."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from govori import session_control


def test_list_sessions_returns_list_on_success():
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = [{"id": "govori__main", "status": "idle"}]
    with patch("govori.session_control.httpx.get", return_value=fake_resp) as mock_get:
        result = session_control.list_sessions()
    assert result == [{"id": "govori__main", "status": "idle"}]
    assert mock_get.call_args.kwargs.get("timeout") == 5.0 or mock_get.call_args[1].get("timeout") == 5.0


def test_list_sessions_returns_empty_on_non_list_json():
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {"unexpected": "shape"}
    with patch("govori.session_control.httpx.get", return_value=fake_resp):
        result = session_control.list_sessions()
    assert result == []


def test_list_sessions_returns_empty_on_error():
    with patch("govori.session_control.httpx.get", side_effect=ConnectionError("refused")):
        result = session_control.list_sessions()
    assert result == []


def test_ask_session_returns_json_on_success():
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {"ok": True, "delivered": True}
    with patch("govori.session_control.httpx.post", return_value=fake_resp) as mock_post:
        result = session_control.ask_session("govori__main", "привет")
    assert result == {"ok": True, "delivered": True}
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"target": "govori__main", "question": "привет"}


def test_ask_session_returns_error_dict_on_failure():
    with patch("govori.session_control.httpx.post", side_effect=TimeoutError("slow")):
        result = session_control.ask_session("govori__main", "привет")
    assert result["ok"] is False
    assert "error" in result


def test_base_url_env_override(monkeypatch):
    monkeypatch.setenv("GOVORI_SM_URL", "http://127.0.0.1:9999")
    assert session_control._base_url() == "http://127.0.0.1:9999"


def test_base_url_default(monkeypatch):
    monkeypatch.delenv("GOVORI_SM_URL", raising=False)
    assert session_control._base_url() == "http://localhost:3007"
