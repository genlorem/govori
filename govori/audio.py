"""Audio capture, recording lifecycle, and transcription dispatch."""

from __future__ import annotations

import threading
import time

import AppKit
import numpy as np
import sounddevice as sd
from loguru import logger

from . import config as cfg
from . import transcribe as t
from .hud import _tooltip, set_hud
from .instrument import record_event, span
from .macos import _press_enter, paste_text
from .notes import _note_pipeline_background
from .state import PERMANENT_API_ERROR, request_cancel, stash_retry_buffer, state
from .transcribe import (
    WHISPER_HALLUCINATIONS,
    _apply_self_corrections,
    _is_hallucination,
)


def audio_callback(indata, frames, time_info, status):
    with state.lock:
        if state.recording:
            state.audio_chunks.append(indata.copy())
            if state.encoder is not None:
                state.encoder.feed(indata.copy())


def _start_mic_stream():
    with state.lock:
        if not state.recording or state.cancelled:
            return
        old_stream = state.audio_stream
        state.audio_stream = None

    if old_stream is not None:
        try:
            old_stream.stop()
            old_stream.close()
        except Exception:
            pass

    try:
        stream = sd.InputStream(
            samplerate=cfg.SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=audio_callback,
        )
        stream.start()
    except sd.PortAudioError as e:
        with state.lock:
            state.recording = False
            state.audio_stream = None
        err_str = str(e).lower()
        tooltip_key = "mic_denied" if "permission" in err_str or "denied" in err_str else "no_mic"
        set_hud(True, mode="error_fatal", tooltip=_tooltip(tooltip_key))
        logger.error(f"Mic error: {e}")
        return

    # Create ParallelEncoder outside the lock (starts a thread), then assign under lock.
    from .transcribe import ParallelEncoder
    encoder = ParallelEncoder()

    with state.lock:
        if not state.recording or state.cancelled:
            close_now = True
        else:
            state.audio_stream = stream
            state.encoder = encoder
            close_now = False
    if close_now:
        encoder.discard()
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass


def _show_recording_hud():
    with state.lock:
        note_mode = state.note_mode
        predict_mode = state.predict_mode
    if note_mode:
        hud_mode = "note"
        icon = "✎"
    elif predict_mode:
        hud_mode = "predict"
        icon = "✦"
    else:
        hud_mode = "recording"
        icon = "●"
    set_hud(True, hud_mode)
    logger.bind(event="rec_start").info("Recording")


def _timeout_for_duration(duration_sec):
    """Scale request timeout with audio length."""
    if duration_sec >= 60:
        return 60.0
    if duration_sec >= 30:
        return 45.0
    if duration_sec >= 20:
        return 35.0
    return 30.0


def stop_and_transcribe():
    with state.lock:
        fn_release_ts = state.fn_release_ts
        state.fn_release_ts = 0.0
    end_to_end_start = time.perf_counter()
    if fn_release_ts:
        record_event("fn_release_to_stop", (end_to_end_start - fn_release_ts) * 1000)

    with span("stop_total"):
        with state.lock:
            state.recording = False
            stream = state.audio_stream
            state.audio_stream = None
            encoder = state.encoder
            state.encoder = None
            cancelled = state.cancelled
            chunks_snapshot = list(state.audio_chunks)
            note_mode = state.note_mode
            predict_mode = state.predict_mode
            auto_send = state.auto_send

        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                logger.warning(f"Audio stream close failed: {e}")

        if not chunks_snapshot or cancelled:
            if encoder is not None:
                encoder.discard()
            set_hud(False)
            return

        total_samples = sum(len(c) for c in chunks_snapshot)
        duration = total_samples / cfg.SAMPLE_RATE
        logger.debug(f"Recording stats chunks={len(chunks_snapshot)} total_samples={total_samples} dur={duration:.2f}s")
        if duration < 0.5:
            if encoder is not None:
                encoder.discard()
            set_hud(False)
            logger.debug("Too short, skipping")
            return

        with span("audio_concat"):
            audio = np.concatenate(chunks_snapshot, axis=0).flatten()
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < 0.0001:
            if encoder is not None:
                encoder.discard()
            set_hud(False)
            logger.debug(f"Silence skipped rms={rms:.4f}")
            return

        if note_mode:
            if encoder is not None:
                encoder.discard()
            if not cfg.NOTES_CFG:
                logger.warning("notes plugin not installed - run: govori plugin init notes")
                set_hud(False)
                return
            audio_copy = audio.copy()
            set_hud(True, "note_saved")
            logger.success("Note captured (background pipeline running)")

            def _hide_check():
                time.sleep(1.2)
                set_hud(False)

            threading.Thread(target=_hide_check, daemon=True).start()
            threading.Thread(
                target=lambda a=audio_copy, d=duration: _note_pipeline_background(a, d),
                daemon=True,
            ).start()
            return

        with state.lock:
            state.transcribing = True
        set_hud(True, "transcribing")
        logger.bind(event="rec_stop").info("Transcribing")

        with span("encode_flush"):
            pre_encoded = encoder.flush() if encoder is not None else None
        if pre_encoded is not None:
            logger.debug("Using pre-encoded OGG from ParallelEncoder")
        else:
            logger.debug("ParallelEncoder unavailable or failed — will re-encode")

        def _show_progress(n, total, sec_left):
            set_hud(True, mode="countdown", count=sec_left)

        with span("transcribe_full"):
            text = t.transcribe_with_fallback(audio, duration, on_progress=_show_progress,
                                              pre_encoded=pre_encoded)
        with state.lock:
            state.transcribing = False
            cancelled = state.cancelled
            predict_mode = state.predict_mode
            auto_send = state.auto_send
            note_mode = state.note_mode

        if text is PERMANENT_API_ERROR:
            if not cancelled:
                set_hud(True, mode="error_fatal", tooltip=_tooltip("api_network"))
            else:
                set_hud(False)
            return

        if text is None:
            if not cancelled:
                stash_retry_buffer(
                    list(chunks_snapshot),
                    {
                        "note_mode": bool(note_mode),
                        "predict_mode": bool(predict_mode),
                        "auto_send": bool(auto_send),
                        "duration": duration,
                    },
                )
                set_hud(True, mode="error_retryable", tooltip=_tooltip("api_network"))
            else:
                set_hud(False)
            return

        set_hud(False)

        if cancelled:
            return

        if _is_hallucination(text):
            logger.bind(event="hallucination").info(f"hallucination filtered: {text}")
            return

        if text:
            logger.bind(event="transcript").info(text)
            if not predict_mode:
                cleaned = _apply_self_corrections(text)
                if cleaned != text:
                    logger.info(f"Cleaned transcript: {cleaned}")
                    text = cleaned
            with span("paste"):
                paste_text(text + " ")
            if predict_mode:
                from .predict import show_predict_menu

                AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                    lambda tx=text: show_predict_menu(tx)
                )
            elif auto_send:
                time.sleep(0.3)
                _press_enter()
        else:
            logger.debug("Empty transcript")

    record_event("end_to_end", (time.perf_counter() - end_to_end_start) * 1000)


def cancel_recording(skip_hud=False, quiet=False):
    stream, encoder = request_cancel()
    if stream is not None:
        try:
            stream.stop()
            stream.close()
        except Exception as e:
            logger.warning(f"Audio stream close failed: {e}")
    if encoder is not None:
        encoder.discard()
    if not skip_hud:
        set_hud(False)
    if not quiet:
        logger.debug("Cancelled")
