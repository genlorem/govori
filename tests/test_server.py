"""Tests for govori/server.py — mocks all govori internals before import."""
from __future__ import annotations

import io
import sys
import wave
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub heavy govori submodules BEFORE importing govori.server.
# We do NOT stub 'govori' itself — it must remain a real importable package
# so that 'from govori.server import app' resolves correctly.
# ---------------------------------------------------------------------------
_PERMANENT_API_ERROR_SENTINEL = object()

_mock_config_mod = MagicMock()
_mock_config_mod.CONFIG_FILE = "/tmp/govori-test-config.yaml"
_mock_config_mod.PLUGINS_DIR = "/tmp/govori-test-plugins"
_mock_config_mod.CONFIG = MagicMock(note_model="test-model")
_mock_config_mod.load_config.return_value = MagicMock(
    model="test", note_model="test-model", language="ru", base_url=None
)
_mock_config_mod.install_runtime_config = MagicMock()

_mock_state_mod = MagicMock()
_mock_state_mod.PERMANENT_API_ERROR = _PERMANENT_API_ERROR_SENTINEL

_mock_transcribe_mod = MagicMock()
_mock_transcribe_mod.transcribe_with_fallback.return_value = "тест транскрипции"

_mock_notes_mod = MagicMock()
_mock_notes_mod._is_hallucination.return_value = False
_mock_notes_mod.save_or_merge_note.return_value = {
    "title": "test-title",
    "contexts": ["personal"],
    "type": "idea",
    "urgency": "low",
    "tags": [],
    "path": "/tmp/test-note.md",
}

# Register stubs — only submodules, NOT 'govori' itself
sys.modules["govori.config"] = _mock_config_mod
sys.modules["govori.state"] = _mock_state_mod
sys.modules["govori.transcribe"] = _mock_transcribe_mod
sys.modules["govori.notes"] = _mock_notes_mod

# Safe to import server now
from fastapi.testclient import TestClient  # noqa: E402

from govori.server import app  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _make_short_wav_bytes() -> bytes:
    """0.1-second silence WAV at 16 kHz mono int16 — too short for /dict."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 1600)  # 0.1 s
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "uptime_s" in data


def test_dict_empty_payload(client):
    r = client.post("/dict")
    assert r.status_code in (400, 422)


def test_dict_bad_audio(client):
    r = client.post(
        "/dict",
        files={"audio": ("test.m4a", b"not audio data", "audio/mp4")},
    )
    assert r.status_code == 400
    body = r.json()
    reason = body.get("reason") or (body.get("detail") or {}).get("reason")
    assert reason == "bad_format"


def test_dict_too_short(client):
    wav_bytes = _make_short_wav_bytes()
    r = client.post(
        "/dict",
        files={"audio": ("short.wav", wav_bytes, "audio/wav")},
    )
    assert r.status_code == 400
    body = r.json()
    reason = body.get("reason") or (body.get("detail") or {}).get("reason")
    assert reason == "too_short"


def test_note_empty_payload(client):
    r = client.post("/note")
    assert r.status_code in (400, 422)
