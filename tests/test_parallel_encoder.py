"""Tests for Phase 4 parallel encoding: ParallelEncoder, pre_encoded path, state wiring."""
from __future__ import annotations

import io
import sys
import threading
import time
from unittest.mock import MagicMock, call, patch

import av
import numpy as np
import pytest

# Stub macOS-only modules so transcribe.py can be imported on Linux
for _mod in ["AppKit", "Foundation", "Cocoa", "objc"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


# ── helpers ─────────────────────────────────────────────────────────────────

SAMPLE_RATE = 16000


def _make_audio(duration_s: float = 1.0, freq: float = 440.0) -> np.ndarray:
    """Sine tone as float32 mono, shape (N,)."""
    t = np.linspace(0, duration_s, int(duration_s * SAMPLE_RATE), endpoint=False)
    return (np.sin(2 * np.pi * freq * t) * 0.5).astype(np.float32)


def _make_chunks(audio: np.ndarray, chunk_samples: int = 1024) -> list[np.ndarray]:
    """Split flat audio into (N,1) chunks as sounddevice would deliver them."""
    chunks = []
    for start in range(0, len(audio), chunk_samples):
        chunk = audio[start : start + chunk_samples].reshape(-1, 1)
        chunks.append(chunk.astype(np.float32))
    return chunks


OPUS_DECODE_RATE = 48000  # libopus always outputs 48kHz regardless of encoding rate


def _decode_ogg_to_float(buf: io.BytesIO) -> tuple[np.ndarray, int]:
    """Decode OGG/Opus BytesIO → (float32 PCM, sample_rate).

    libopus decodes at 48kHz even when encoded at 16kHz.
    """
    buf.seek(0)
    container = av.open(buf, "r")
    frames = []
    rate = OPUS_DECODE_RATE
    for packet in container.demux():
        for frame in packet.decode():
            rate = frame.rate
            arr = frame.to_ndarray()
            frames.append(arr.flatten().astype(np.float32) / 32767.0)
    container.close()
    pcm = np.concatenate(frames) if frames else np.array([], dtype=np.float32)
    return pcm, rate


@pytest.fixture(autouse=True)
def _mock_config(monkeypatch):
    """Provide SAMPLE_RATE and stub other config so transcribe imports cleanly."""
    import govori.config as cfg
    monkeypatch.setattr(cfg, "SAMPLE_RATE", SAMPLE_RATE, raising=False)
    monkeypatch.setattr(cfg, "LANGUAGE", "ru", raising=False)
    monkeypatch.setattr(cfg, "WHISPER_PROMPT", "", raising=False)
    monkeypatch.setattr(cfg, "CONFIG", None, raising=False)


# ── ParallelEncoder: core behaviour ─────────────────────────────────────────

class TestParallelEncoder:
    def _make(self):
        from govori.transcribe import ParallelEncoder
        return ParallelEncoder()

    def test_flush_returns_bytesio(self):
        enc = self._make()
        audio = _make_audio(1.0)
        for chunk in _make_chunks(audio):
            enc.feed(chunk)
        buf = enc.flush(timeout=5.0)
        assert buf is not None
        assert isinstance(buf, io.BytesIO)

    def test_flush_produces_nonempty_ogg(self):
        enc = self._make()
        for chunk in _make_chunks(_make_audio(0.5)):
            enc.feed(chunk)
        buf = enc.flush(timeout=5.0)
        assert buf is not None
        data = buf.read()
        assert len(data) > 0
        # OGG files start with "OggS" magic
        assert data[:4] == b"OggS"

    def test_flush_output_is_decodable(self):
        audio = _make_audio(1.0)
        enc = self._make()
        for chunk in _make_chunks(audio):
            enc.feed(chunk)
        buf = enc.flush(timeout=5.0)
        assert buf is not None
        decoded, rate = _decode_ogg_to_float(buf)
        assert len(decoded) > 0
        # Opus always decodes at 48kHz; duration should be ~1s
        assert abs(len(decoded) / rate - 1.0) < 0.1

    def test_multi_chunk_pts_monotonic(self):
        """Multiple chunks produce a valid OGG with correct total duration."""
        audio = _make_audio(3.0)
        enc = self._make()
        for chunk in _make_chunks(audio, chunk_samples=512):
            enc.feed(chunk)
        buf = enc.flush(timeout=5.0)
        decoded, rate = _decode_ogg_to_float(buf)
        assert abs(len(decoded) / rate - 3.0) < 0.15

    def test_no_feed_flush_returns_bytesio(self):
        """flush() with zero chunks returns a BytesIO (may be empty — no frames to encode)."""
        enc = self._make()
        buf = enc.flush(timeout=3.0)
        assert buf is not None
        assert isinstance(buf, io.BytesIO)

    def test_discard_is_nonblocking(self):
        """discard() must return in well under 1s even with queued chunks."""
        enc = self._make()
        for chunk in _make_chunks(_make_audio(2.0)):
            enc.feed(chunk)
        t0 = time.perf_counter()
        enc.discard()
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.5, f"discard took {elapsed:.3f}s — should be near-instant"

    def test_flush_after_discard_returns_none_or_bytes(self):
        """After discard(), a subsequent flush() call should not deadlock."""
        enc = self._make()
        for chunk in _make_chunks(_make_audio(0.5)):
            enc.feed(chunk)
        enc.discard()
        # Thread received the sentinel from discard; a second flush might get None
        # (sentinel already consumed) but must not hang
        buf = enc.flush(timeout=2.0)
        # either None or BytesIO — both are acceptable; the key is no deadlock
        assert buf is None or isinstance(buf, io.BytesIO)

    def test_queue_full_drops_gracefully(self):
        """Overfilling the queue (> 60s) should log a warning and not raise."""
        from govori.transcribe import ParallelEncoder
        # Small maxsize to force Full quickly
        enc = ParallelEncoder()
        enc._q.maxsize = 4  # override to test the drop path
        chunk = np.zeros((1024, 1), dtype=np.float32)
        for _ in range(10):
            enc.feed(chunk)  # must not raise even when Full
        enc.discard()

    def test_feed_from_multiple_threads(self):
        """Concurrent feed() calls must be safe — queue is thread-safe."""
        enc = self._make()
        audio = _make_audio(1.0)
        chunks = _make_chunks(audio)
        errors = []

        def _feed_all():
            try:
                for c in chunks:
                    enc.feed(c)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_feed_all) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        enc.discard()
        assert not errors


# ── _try_transcribe: pre_encoded routing ────────────────────────────────────

class TestTryTranscribePreEncoded:
    """Verify that attempt 1 uses pre_encoded buffer; retries fall back to re-encode."""

    def _make_provider_client(self):
        from govori.transcribe import Provider
        p = Provider(name="groq", api_key_env="GROQ_API_KEY",
                     base_url="https://api.groq.com/openai/v1", model="whisper-large-v3-turbo")
        client = MagicMock()
        return p, client

    def test_first_attempt_calls_transcribe_preencoded(self):
        from govori.transcribe import _try_transcribe

        pre_buf = io.BytesIO(b"fake-ogg")
        pre_buf.name = "audio.ogg"
        audio = _make_audio(1.0)
        p, client = self._make_provider_client()

        with patch("govori.transcribe._transcribe_preencoded", return_value="hello") as mock_pre, \
             patch("govori.transcribe._encode_and_transcribe") as mock_enc:
            result = _try_transcribe(p, client, audio, 1.0, pre_encoded=pre_buf, max_retries=0)

        mock_pre.assert_called_once_with(client, p.model, pre_buf, timeout=30.0)
        mock_enc.assert_not_called()
        assert result == "hello"

    def test_retry_uses_encode_and_transcribe(self):
        """On retry (attempt > 1), must re-encode from raw audio, not pre_encoded."""
        from govori.transcribe import _try_transcribe

        pre_buf = io.BytesIO(b"fake-ogg")
        audio = _make_audio(1.0)
        p, client = self._make_provider_client()

        call_count = {"n": 0}

        def _pre_side(*args, **kwargs):
            call_count["n"] += 1
            return None  # force retry on first attempt

        with patch("govori.transcribe._transcribe_preencoded", side_effect=_pre_side), \
             patch("govori.transcribe._encode_and_transcribe", return_value="retry-ok") as mock_enc:
            result = _try_transcribe(p, client, audio, 1.0, pre_encoded=pre_buf, max_retries=1)

        assert call_count["n"] == 1  # pre_encoded called exactly on attempt 1
        mock_enc.assert_called_once()  # raw encode on attempt 2
        assert result == "retry-ok"

    def test_no_pre_encoded_uses_encode(self):
        """Without pre_encoded, always calls _encode_and_transcribe."""
        from govori.transcribe import _try_transcribe

        audio = _make_audio(1.0)
        p, client = self._make_provider_client()

        with patch("govori.transcribe._transcribe_preencoded") as mock_pre, \
             patch("govori.transcribe._encode_and_transcribe", return_value="plain") as mock_enc:
            result = _try_transcribe(p, client, audio, 1.0, pre_encoded=None, max_retries=0)

        mock_pre.assert_not_called()
        mock_enc.assert_called_once()
        assert result == "plain"


# ── transcribe_with_fallback: threads pre_encoded through ───────────────────

class TestTranscribeWithFallbackPreEncoded:
    def test_pre_encoded_passed_to_primary(self):
        from govori.transcribe import transcribe_with_fallback

        pre_buf = io.BytesIO(b"fake")
        audio = _make_audio(1.0)

        with patch("govori.transcribe._try_transcribe", return_value="ok") as mock_try, \
             patch("govori.transcribe._get_client", return_value=MagicMock()):
            transcribe_with_fallback(audio, 1.0, pre_encoded=pre_buf)

        first_call_kwargs = mock_try.call_args
        assert first_call_kwargs.kwargs.get("pre_encoded") is pre_buf


# ── State: encoder field and request_cancel ──────────────────────────────────

class TestStateEncoder:
    def test_appstate_has_encoder_field(self):
        from govori.state import AppState
        s = AppState()
        assert hasattr(s, "encoder")
        assert s.encoder is None

    def test_begin_recording_leaves_encoder_none(self):
        """begin_recording() doesn't create the encoder — _start_mic_stream does."""
        from govori.state import AppState, begin_recording
        import govori.state as state_mod

        s = AppState()
        old_state = state_mod.state
        state_mod.state = s
        try:
            begin_recording(predict=False, note=False, auto_send=False)
            assert s.encoder is None
        finally:
            state_mod.state = old_state

    def test_request_cancel_clears_encoder(self):
        """request_cancel() must clear state.encoder and return it."""
        from govori.state import AppState, request_cancel
        import govori.state as state_mod

        fake_encoder = MagicMock()
        s = AppState()
        s.recording = True
        s.encoder = fake_encoder
        old_state = state_mod.state
        state_mod.state = s
        try:
            stream, enc = request_cancel()
            assert s.encoder is None
            assert enc is fake_encoder
        finally:
            state_mod.state = old_state


# ── Round-trip quality check ─────────────────────────────────────────────────

class TestRoundTripQuality:
    """ParallelEncoder output is decodable and duration-accurate vs the serial path."""

    def test_duration_matches_serial_encode(self):
        """Both paths encode the same audio to approximately the same duration."""
        from govori.transcribe import ParallelEncoder

        audio = _make_audio(2.0)
        chunks = _make_chunks(audio)

        # Parallel path
        enc = ParallelEncoder()
        for c in chunks:
            enc.feed(c)
        par_buf = enc.flush(timeout=5.0)
        par_decoded, par_rate = _decode_ogg_to_float(par_buf)

        # Serial path (what _encode_and_transcribe does)
        peak = np.max(np.abs(audio))
        norm = audio / peak * 0.9
        ser_buf = io.BytesIO()
        ser_buf.name = "audio.ogg"
        container = av.open(ser_buf, mode="w", format="ogg")
        stream = container.add_stream("libopus", rate=SAMPLE_RATE, layout="mono")
        frame = av.AudioFrame.from_ndarray(
            (norm * 32767).astype(np.int16).reshape(1, -1), format="s16", layout="mono"
        )
        frame.rate = SAMPLE_RATE
        for pkt in stream.encode(frame):
            container.mux(pkt)
        for pkt in stream.encode(None):
            container.mux(pkt)
        container.close()
        ser_buf.seek(0)
        ser_decoded, ser_rate = _decode_ogg_to_float(ser_buf)

        par_dur = len(par_decoded) / par_rate
        ser_dur = len(ser_decoded) / ser_rate
        assert abs(par_dur - ser_dur) < 0.05, (
            f"Duration mismatch: parallel={par_dur:.3f}s serial={ser_dur:.3f}s"
        )
