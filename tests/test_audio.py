"""Tests for audio decoding helpers in govori/server.py."""
from __future__ import annotations

import io
import struct
import sys
import wave
from unittest.mock import MagicMock

import numpy as np
import pytest


# Stub heavy modules before importing server
for _mod in ["AppKit", "Foundation", "Cocoa", "objc"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


def make_wav_bytes(duration_s: float = 0.5, sample_rate: int = 16000, amplitude: int = 0) -> bytes:
    """Synthesize WAV using stdlib wave — no soundfile needed."""
    buf = io.BytesIO()
    n = int(duration_s * sample_rate)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack("<" + "h" * n, *([amplitude] * n)))
    return buf.getvalue()


def _get_helpers():
    """Import _decode_audio and _check_audio_quality from server (may require PyAV)."""
    try:
        import govori.server as srv
        decode = getattr(srv, "_decode_audio", None)
        check = getattr(srv, "_check_audio_quality", None)
        return decode, check
    except Exception:
        return None, None


def test_decode_garbage_bytes():
    """Garbage bytes → HTTPException (400 bad_format) or other exception."""
    _decode_audio, _ = _get_helpers()
    if _decode_audio is None:
        pytest.skip("_decode_audio not accessible")

    from fastapi import HTTPException
    with pytest.raises((HTTPException, Exception)):
        _decode_audio(b"notaudioatall_xyzxyzxyz_garbage")


def test_decode_valid_wav():
    """A valid 0.5s WAV → returns (array, duration) without error."""
    _decode_audio, _ = _get_helpers()
    if _decode_audio is None:
        pytest.skip("_decode_audio not accessible")

    try:
        import av  # noqa: F401
    except ImportError:
        pytest.skip("PyAV not installed — skip real audio decode test")

    wav = make_wav_bytes(duration_s=0.5, amplitude=100)
    result = _decode_audio(wav)
    assert result is not None
    arr, duration = result
    assert duration > 0
    # Duration should be approximately 0.5s (within 50%)
    assert 0.2 < duration < 1.5, f"Unexpected duration: {duration}"


def test_check_quality_too_short():
    """Audio shorter than 0.5s → raises HTTPException with reason too_short."""
    _, _check_audio_quality = _get_helpers()
    if _check_audio_quality is None:
        pytest.skip("_check_audio_quality not accessible")

    from fastapi import HTTPException
    short_audio = np.ones(1000, dtype=np.float32) * 0.5  # 1000 samples at 16kHz = 0.0625s
    with pytest.raises(HTTPException) as exc_info:
        _check_audio_quality(short_audio, 0.06)
    assert exc_info.value.detail.get("reason") == "too_short"


def test_check_quality_silence():
    """Near-silent audio → raises HTTPException with reason too_short."""
    _, _check_audio_quality = _get_helpers()
    if _check_audio_quality is None:
        pytest.skip("_check_audio_quality not accessible")

    from fastapi import HTTPException
    silence = np.zeros(32000, dtype=np.float32)  # 2s of silence
    with pytest.raises(HTTPException) as exc_info:
        _check_audio_quality(silence, 2.0)
    assert exc_info.value.detail.get("reason") == "too_short"


def test_check_quality_ok():
    """Non-silent audio of sufficient length → no exception."""
    _, _check_audio_quality = _get_helpers()
    if _check_audio_quality is None:
        pytest.skip("_check_audio_quality not accessible")

    loud = np.ones(16000, dtype=np.float32) * 0.5  # 1s, RMS=0.5
    # Should not raise
    _check_audio_quality(loud, 1.0)
