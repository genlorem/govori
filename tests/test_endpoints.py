"""Integration tests for FastAPI endpoints via TestClient.

External API calls (transcribe, anthropic, correct_transcript AI path) are mocked.
Audio decoding (_decode_audio) is patched to bypass real PyAV dependency.
"""
from __future__ import annotations

import io
import json
import struct
import sys
import wave
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


MASTER = "test-master-token-abc123"
AUTH = {"X-Govori-Token": MASTER}


def make_wav_bytes(duration_s: float = 1.0) -> bytes:
    buf = io.BytesIO()
    n = int(duration_s * 16000)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
        # Use non-zero amplitude so audio is not silent
        wf.writeframes(struct.pack("<" + "h" * n, *([500] * n)))
    return buf.getvalue()


FAKE_AUDIO = np.ones(16000, dtype=np.float32) * 0.1  # 1s non-silent


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("ok") is True


# ---------------------------------------------------------------------------
# /dict-test
# ---------------------------------------------------------------------------

def test_dict_test_post(client):
    r = client.post("/dict-test", headers=AUTH)
    assert r.status_code == 200
    assert "text" in r.json()


def test_dict_test_text_mode(client):
    r = client.post("/dict-test?text=1", headers=AUTH)
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# /dict
# ---------------------------------------------------------------------------

def test_dict_empty_body(client):
    """Empty body → 400 bad_format."""
    r = client.post(
        "/dict",
        content=b"",
        headers={**AUTH, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 400
    assert r.json().get("detail", {}).get("reason") == "bad_format"


def test_dict_with_mock_audio(client):
    """Mocked audio decode + transcription → 200."""
    wav = make_wav_bytes()
    with patch("govori.server._decode_audio", return_value=(FAKE_AUDIO, 1.0)), \
         patch("govori.server._check_audio_quality", return_value=None), \
         patch("govori.transcribe.transcribe_with_fallback", return_value="тестовый текст"), \
         patch("govori.correct.correct_transcript", return_value=("тестовый текст", [])), \
         patch("govori.notes._is_hallucination", return_value=False):
        r = client.post(
            "/dict",
            content=wav,
            headers={**AUTH, "Content-Type": "application/octet-stream"},
        )
    assert r.status_code == 200
    assert "text" in r.json()


def test_dict_text_mode(client):
    """?text=1 returns plain text."""
    wav = make_wav_bytes()
    with patch("govori.server._decode_audio", return_value=(FAKE_AUDIO, 1.0)), \
         patch("govori.server._check_audio_quality", return_value=None), \
         patch("govori.transcribe.transcribe_with_fallback", return_value="тестовый текст"), \
         patch("govori.correct.correct_transcript", return_value=("тестовый текст", [])), \
         patch("govori.notes._is_hallucination", return_value=False):
        r = client.post(
            "/dict?text=1",
            content=wav,
            headers={**AUTH, "Content-Type": "application/octet-stream"},
        )
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# /note
# ---------------------------------------------------------------------------

_NOTE_META = {
    "contexts": ["personal"], "type": "todo", "urgency": "low",
    "title": "купить молоко", "tags": [],
}


def test_note_preview_does_not_save(client):
    """/note?preview=1 must NOT call save_or_merge_note."""
    wav = make_wav_bytes()
    with patch("govori.server._decode_audio", return_value=(FAKE_AUDIO, 1.0)), \
         patch("govori.server._check_audio_quality", return_value=None), \
         patch("govori.transcribe.transcribe_with_fallback", return_value="купить молоко"), \
         patch("govori.correct.correct_transcript", return_value=("купить молоко", [])), \
         patch("govori.notes._is_hallucination", return_value=False), \
         patch("govori.notes.classify_note", return_value=_NOTE_META), \
         patch("govori.notes.save_or_merge_note") as mock_save:
        r = client.post(
            "/note?preview=1",
            content=wav,
            headers={**AUTH, "Content-Type": "application/octet-stream"},
        )
    assert r.status_code == 200
    mock_save.assert_not_called()


def test_note_saves_by_default(client):
    """/note (no preview) calls save_or_merge_note."""
    wav = make_wav_bytes()
    save_result = {"meta": _NOTE_META, "merged": False, "path": "/tmp/t.md"}
    with patch("govori.server._decode_audio", return_value=(FAKE_AUDIO, 1.0)), \
         patch("govori.server._check_audio_quality", return_value=None), \
         patch("govori.transcribe.transcribe_with_fallback", return_value="купить молоко"), \
         patch("govori.correct.correct_transcript", return_value=("купить молоко", [])), \
         patch("govori.notes._is_hallucination", return_value=False), \
         patch("govori.notes.save_or_merge_note", return_value=save_result) as mock_save:
        r = client.post(
            "/note",
            content=wav,
            headers={**AUTH, "Content-Type": "application/octet-stream"},
        )
    assert r.status_code == 200
    mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# /note stage=classify/execute — session_ask (voice control of session-manager)
# ---------------------------------------------------------------------------

_DO_META = {
    "contexts": ["default"], "type": "other", "urgency": "low",
    "title": "команда", "tags": [], "related_stuck": [],
    "intent": "do", "target": "session-manager",
    "summary": "спроси у session-manager", "confidence": "high",
}

_SESSION_ASK_ACTION = {
    "action": "session_ask",
    "message": "когда будет готово",
    "candidates": ["session-manager__spark", "session-manager__main"],
}

_OTHER_ACTION = {"action": "other", "message": None, "candidates": []}


def _classify_do(client, action_info):
    """POST /note?stage=classify with intent=do routed to `action_info`. Returns JSON."""
    wav = make_wav_bytes()
    with patch("govori.server._decode_audio", return_value=(FAKE_AUDIO, 1.0)), \
         patch("govori.server._check_audio_quality", return_value=None), \
         patch("govori.transcribe.transcribe_with_fallback",
               return_value="спроси у session-manager когда будет готово"), \
         patch("govori.correct.correct_transcript",
               return_value=("спроси у session-manager когда будет готово", [])), \
         patch("govori.notes._is_hallucination", return_value=False), \
         patch("govori.intents.classify_intent", return_value=dict(_DO_META)), \
         patch("govori.intents.classify_do_action", return_value=dict(action_info)):
        r = client.post(
            "/note?stage=classify",
            content=wav,
            headers={**AUTH, "Content-Type": "application/octet-stream"},
        )
    assert r.status_code == 200
    return r.json()


def test_note_classify_session_ask_forces_confirm_menu(client):
    """action=session_ask must force confirm=1 even though confidence=high (Q3)."""
    data = _classify_do(client, _SESSION_ASK_ACTION)
    assert data["action"] == "session_ask"
    assert data["confirm"] == 1
    assert data["session_candidates"] == _SESSION_ASK_ACTION["candidates"]
    assert data["session_message"] == _SESSION_ASK_ACTION["message"]  # phone needs this field to render the menu prompt
    assert "когда будет готово" in data["line"]


def test_note_classify_non_session_do_keeps_confidence_gate(client):
    """Regular do-commands (action=other) keep the existing confidence-gated menu."""
    data = _classify_do(client, _OTHER_ACTION)
    assert data["action"] == "other"
    assert data["confirm"] == 0  # confidence=high in _DO_META -> no forced menu
    assert data["session_candidates"] == []


def test_note_execute_session_ask_sends_to_chosen_session(client):
    data = _classify_do(client, _SESSION_ASK_ACTION)
    token = data["token"]

    with patch("govori.intents.session_ask_execute",
               return_value="✓ отправлено в session-manager__spark") as mock_send, \
         patch("govori.intents.log_intent_decision") as mock_log:
        r = client.post(
            f"/note?stage=execute&token={token}&intent=do&session=session-manager__spark",
            headers=AUTH,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "✓ отправлено в session-manager__spark"
    assert body["action"] == "session_ask"
    mock_send.assert_called_once_with("session-manager__spark", "когда будет готово")
    logged = mock_log.call_args[0][0]
    assert logged["chosen_target"] == "session-manager__spark"
    assert logged["predicted_target"] == "session-manager__spark"  # top candidate


def test_note_execute_session_ask_empty_session_cancels(client):
    data = _classify_do(client, _SESSION_ASK_ACTION)
    token = data["token"]

    with patch("govori.intents.session_ask_execute") as mock_send, \
         patch("govori.intents.log_intent_decision") as mock_log:
        r = client.post(f"/note?stage=execute&token={token}&intent=do&session=", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["answer"] == "❌ отменено"
    mock_send.assert_not_called()
    logged = mock_log.call_args[0][0]
    assert logged["chosen_target"] is None


def test_note_execute_session_ask_explicit_cancel_label(client):
    data = _classify_do(client, _SESSION_ASK_ACTION)
    token = data["token"]

    with patch("govori.intents.session_ask_execute") as mock_send, \
         patch("govori.intents.log_intent_decision"):
        r = client.post(f"/note?stage=execute&token={token}&intent=do&session=Отмена", headers=AUTH)
    assert r.json()["answer"] == "❌ отменено"
    mock_send.assert_not_called()


def test_note_execute_do_falls_back_to_dispatch_when_not_session_ask(client):
    """action=other (not session-related) keeps the existing dispatch_command stub."""
    data = _classify_do(client, _OTHER_ACTION)
    token = data["token"]

    with patch("govori.intents.dispatch_command", return_value="Команда сохранена.") as mock_dispatch, \
         patch("govori.intents.session_ask_execute") as mock_send, \
         patch("govori.intents.log_intent_decision"):
        r = client.post(f"/note?stage=execute&token={token}&intent=do", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["answer"] == "Команда сохранена."
    mock_dispatch.assert_called_once()
    mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# /review/* endpoints
# ---------------------------------------------------------------------------

def test_review_data_returns_json(client):
    r = client.get("/review/data", headers=AUTH)
    assert r.status_code == 200
    assert "application/json" in r.headers.get("content-type", "")
    assert isinstance(r.json(), list)


def test_review_dict_returns_json(client):
    r = client.get("/review/dict", headers=AUTH)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_review_action_accept(client, tmp_config):
    """accept=true writes entry to corrections map via /review/action."""
    body = {"accept": True, "from": "тестслово", "to": "TestWord", "ts": "2024-01-01T00:00:00"}
    r = client.post("/review/action", json=body, headers=AUTH)
    assert r.status_code == 200
    assert r.json().get("ok") is True
    # Verify it was actually written to the tmp corrections file
    data = json.loads(tmp_config["corrections_file"].read_text())
    assert "тестслово" in data


def test_review_action_remove(client, tmp_config):
    """remove=key deletes entry."""
    # Add first
    client.post(
        "/review/action",
        json={"accept": True, "from": "удали", "to": "Delete", "ts": "2024-01-01T00:00:00"},
        headers=AUTH,
    )
    # Remove
    r = client.post("/review/action", json={"remove": "удали"}, headers=AUTH)
    assert r.status_code == 200
    data = json.loads(tmp_config["corrections_file"].read_text())
    assert "удали" not in data


def test_review_action_manual_add(client, tmp_config):
    """Manual add (no ts) works."""
    r = client.post(
        "/review/action",
        json={"accept": True, "from": "ручной", "to": "Manual"},
        headers=AUTH,
    )
    assert r.status_code == 200
