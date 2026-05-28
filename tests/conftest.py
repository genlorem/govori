"""Shared fixtures for govori test suite.

CRITICAL: All file paths are redirected to tmp_path so real ~/.config/govori
files are never touched. All external API calls (Anthropic, Groq) are mocked.
"""
from __future__ import annotations

import io
import json
import os
import socket
import struct
import sys
import threading
import time
import wave
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_wav_bytes(duration_s: float = 0.5, sample_rate: int = 16000) -> bytes:
    """Synthesize a minimal silent WAV clip (stdlib wave, no soundfile needed)."""
    buf = io.BytesIO()
    n = int(duration_s * sample_rate)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack("<" + "h" * n, *([0] * n)))
    return buf.getvalue()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Stub macOS-only modules (same pattern as existing test_server.py)
# ---------------------------------------------------------------------------
for _mod in ["AppKit", "Foundation", "Cocoa", "objc"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


# ---------------------------------------------------------------------------
# Master token constant
# ---------------------------------------------------------------------------
MASTER_TOKEN = "test-master-token-abc123"


# ---------------------------------------------------------------------------
# tmp_config: redirect all govori file paths to tmp_path
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_config(tmp_path, monkeypatch):
    """Redirect govori file paths to tmp_path. Never touches ~/.config/govori."""
    tokens_file = tmp_path / "tokens.json"
    corrections_file = tmp_path / "corrections.json"
    corrections_log = tmp_path / "corrections.jsonl"

    tokens_file.write_text("{}", encoding="utf-8")
    corrections_file.write_text("{}", encoding="utf-8")
    corrections_log.write_text("", encoding="utf-8")

    # Patch govori.tokens
    import govori.tokens as tok_mod
    monkeypatch.setattr(tok_mod, "TOKENS_FILE", tokens_file)
    # Reset in-memory cache so each test starts cold
    monkeypatch.setattr(tok_mod, "_cache", None)
    monkeypatch.setattr(tok_mod, "_cache_mtime", 0.0)

    # Patch govori.correct
    import govori.correct as cor_mod
    monkeypatch.setattr(cor_mod, "CORRECTIONS_MAP", corrections_file)
    monkeypatch.setattr(cor_mod, "CORRECTIONS_LOG", corrections_log)
    # Reset glossary cache
    monkeypatch.setattr(cor_mod, "_glossary_cache", None)
    monkeypatch.setattr(cor_mod, "_glossary_mtime", 0.0)

    # Patch govori.review (imports CORRECTIONS_LOG and CORRECTIONS_MAP from correct)
    import govori.review as rev_mod
    monkeypatch.setattr(rev_mod, "CORRECTIONS_LOG", corrections_log)
    monkeypatch.setattr(rev_mod, "CORRECTIONS_MAP", corrections_file)

    return {
        "tmp_path": tmp_path,
        "tokens_file": tokens_file,
        "corrections_file": corrections_file,
        "corrections_log": corrections_log,
    }


# ---------------------------------------------------------------------------
# TestClient fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def master_token():
    return MASTER_TOKEN


@pytest.fixture()
def client(tmp_config, monkeypatch):
    """FastAPI TestClient with master token and tmp config paths.

    We use the same heavy-mock pattern as test_server.py so that macOS-only
    imports and real external API calls are never triggered.
    """
    monkeypatch.setenv("GOVORI_TOKEN", MASTER_TOKEN)
    monkeypatch.setenv("GOVORI_LS_SECRET", "test-ls-secret")

    from fastapi.testclient import TestClient

    # Build app with mocked heavy deps (same as test_server.py approach)
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

    _mock_state = MagicMock()
    _mock_state.PERMANENT_API_ERROR = object()

    _mock_transcribe = MagicMock()
    _mock_transcribe.transcribe_with_fallback.return_value = "тест транскрипции"

    _mock_notes = MagicMock()
    _mock_notes._is_hallucination.return_value = False
    _mock_notes.save_or_merge_note.return_value = {
        "title": "test", "contexts": ["personal"], "type": "idea",
        "urgency": "low", "tags": [], "path": "/tmp/test.md",
    }

    # Register mocks into sys.modules for this test's scope
    old_mods = {}
    for name, mock in [
        ("govori.config", _mock_config),
        ("govori.state", _mock_state),
        ("govori.transcribe", _mock_transcribe),
        ("govori.notes", _mock_notes),
    ]:
        old_mods[name] = sys.modules.get(name)
        sys.modules[name] = mock

    # Remove cached govori.server so it re-imports with fresh mocks
    old_server = sys.modules.pop("govori.server", None)

    try:
        from govori.server import app  # noqa: PLC0415
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        # Restore
        for name, orig in old_mods.items():
            if orig is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = orig
        if old_server is not None:
            sys.modules["govori.server"] = old_server
        else:
            sys.modules.pop("govori.server", None)


@pytest.fixture()
def customer_token(tmp_config):
    """Issue an active customer token into the tmp tokens file."""
    import govori.tokens as tok
    tok_str = tok.issue("test-owner", "test-label")
    return tok_str


# ---------------------------------------------------------------------------
# Live server for Playwright (session-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def live_server(tmp_path_factory):
    """Start uvicorn on a free port. Yields base URL. Used by Playwright tests."""
    uvicorn = pytest.importorskip("uvicorn")
    pytest.importorskip("playwright")

    tmp = tmp_path_factory.mktemp("live")
    tokens_file = tmp / "tokens.json"
    tokens_file.write_text("{}", encoding="utf-8")
    corrections_file = tmp / "corrections.json"
    corrections_file.write_text('{"тестовый": "Тестовый"}', encoding="utf-8")
    corrections_log = tmp / "corrections.jsonl"
    corrections_log.write_text("", encoding="utf-8")

    os.environ["GOVORI_TOKEN"] = MASTER_TOKEN
    os.environ["GOVORI_LS_SECRET"] = "test-ls-secret"

    # Patch file paths for live server (module-level since session-scoped)
    import govori.tokens as tok_mod
    import govori.correct as cor_mod
    import govori.review as rev_mod

    tok_mod.TOKENS_FILE = tokens_file
    cor_mod.CORRECTIONS_MAP = corrections_file
    cor_mod.CORRECTIONS_LOG = corrections_log
    rev_mod.CORRECTIONS_LOG = corrections_log
    rev_mod.CORRECTIONS_MAP = corrections_file

    # Use mock heavy deps for live server too
    _mock_config = MagicMock()
    _mock_config.CONFIG_FILE = str(tmp / "config.yaml")
    _mock_config.PLUGINS_DIR = str(tmp / "plugins")
    _mock_config.SAMPLE_RATE = 16000
    _mock_config.NOTES_CFG = {}
    _mock_config.load_config.return_value = MagicMock(
        model="test", note_model="test-model", language="ru", base_url=None
    )
    _mock_config.install_runtime_config = MagicMock()
    _mock_config.load_plugins = MagicMock(return_value={})

    sys.modules["govori.config"] = _mock_config
    sys.modules.pop("govori.server", None)

    from govori.server import app  # noqa: PLC0415

    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server to be ready
    import httpx
    for _ in range(40):
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
            break
        except Exception:
            time.sleep(0.2)

    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
