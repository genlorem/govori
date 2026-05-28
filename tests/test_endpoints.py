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
