"""Long audio is split on pauses: one Whisper call on 4+ minutes drops whole pieces."""
from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

for _mod in ["AppKit", "Foundation", "Cocoa", "objc"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

SR = 16000


@pytest.fixture(scope="module")
def tr():
    """Real govori.transcribe — test_server.py replaces it with a MagicMock globally."""
    saved = sys.modules.pop("govori.transcribe", None)
    mod = importlib.import_module("govori.transcribe")
    yield mod
    if saved is not None:
        sys.modules["govori.transcribe"] = saved


def _speech_with_pauses(total_sec: float, pause_every: float, pause_len: float = 0.4):
    t = np.arange(int(total_sec * SR)) / SR
    audio = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    k = pause_every
    while k < total_sec:
        audio[int(k * SR): int((k + pause_len) * SR)] = 0.0
        k += pause_every
    return audio


def test_split_keeps_every_sample_and_bounds(tr):
    audio = _speech_with_pauses(257, 7.0)
    pieces = tr.split_on_pauses(audio, SR)
    assert sum(len(p) for p in pieces) == len(audio)
    assert all(len(p) / SR <= tr.CHUNK_MAX_SEC + 0.05 for p in pieces)
    assert all(len(p) / SR >= tr.CHUNK_MIN_SEC - 0.05 for p in pieces[:-1])


def test_cuts_land_in_pauses(tr):
    audio = _speech_with_pauses(120, 7.0)
    pieces = tr.split_on_pauses(audio, SR)
    pos = 0
    for p in pieces[:-1]:
        pos += len(p)
        assert audio[pos] == 0.0


def test_short_audio_not_split(tr):
    assert len(tr.split_on_pauses(_speech_with_pauses(25, 7.0), SR)) == 1


def test_long_audio_transcribed_by_chunks_in_order(tr, monkeypatch):
    calls = []

    def fake_try(provider, client, audio, duration_sec, **kw):
        calls.append(duration_sec)
        return "Продолжение следует" if duration_sec < 1 else f"кусок{round(duration_sec)}"

    monkeypatch.setattr(tr, "_get_client", lambda p: object())
    monkeypatch.setattr(tr, "_try_transcribe", fake_try)
    audio = np.concatenate([_speech_with_pauses(90, 7.0), np.zeros(int(0.5 * SR), np.float32)])
    text = tr.transcribe_with_fallback(audio, len(audio) / SR)
    pieces = tr.split_on_pauses(audio, SR)
    assert len(calls) == len(pieces) > 1
    assert text == " ".join(f"кусок{round(len(p) / SR)}" for p in pieces if len(p) / SR >= 1)


def test_chunk_failure_fails_whole(tr, monkeypatch):
    monkeypatch.setattr(tr, "_get_client", lambda p: object())
    monkeypatch.setattr(tr, "_get_provider", lambda name: MagicMock(name=name))
    seq = iter(["a", None, "c", None, None, None])
    monkeypatch.setattr(tr, "_try_transcribe", lambda *a, **kw: next(seq, None))
    monkeypatch.setattr(tr, "CHUNK_WORKERS", 1)
    assert tr.transcribe_with_fallback(_speech_with_pauses(90, 7.0), 90.0) is None
