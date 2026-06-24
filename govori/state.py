"""Runtime state for the Govori daemon.

Mutate only inside ``with state.lock:``. ``RLock`` is intentional: paths such
as cancel_recording -> set_hud may re-enter state-touching code, and a regular
Lock would make those paths vulnerable to self-deadlock.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional


# Sentinel for non-retryable API errors (4xx other than 408/429).
# Distinct from None which signals transient failures eligible for retry.
PERMANENT_API_ERROR = object()


@dataclass
class AppState:
    recording: bool = False
    transcribing: bool = False
    audio_chunks: list = field(default_factory=list)
    audio_stream: Any = None
    auto_send: bool = False
    cancelled: bool = False
    predict_mode: bool = False
    note_mode: bool = False
    retry_buffer: Optional[list] = None
    retry_count: int = 0
    retry_in_progress: bool = False
    retry_mode_snapshot: Optional[dict] = None
    hud_error_mode: Optional[str] = None
    health_monitor_owns_hud: bool = False
    shutdown_requested: bool = False
    fn_release_ts: float = 0.0  # PERF-01: timestamp set by hotkey on fn-up, consumed by audio.stop_and_transcribe for the fn_release_to_stop span
    encoder: Any = None  # ParallelEncoder instance during recording; None otherwise
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)


state = AppState()


def begin_recording(*, predict: bool, note: bool, auto_send: bool) -> bool:
    """Atomically transition to recording state. Return False if already recording."""
    with state.lock:
        if state.recording:
            return False
        state.recording = True
        state.transcribing = False
        state.audio_chunks = []
        state.auto_send = auto_send
        state.cancelled = False
        state.predict_mode = predict
        state.note_mode = note
        state.retry_count = 0
        state.fn_release_ts = 0.0
        return True


def request_cancel():
    """Cancel active work; return (stream, encoder) snapshots for outside-lock cleanup."""
    with state.lock:
        stream = state.audio_stream
        state.audio_stream = None
        encoder = state.encoder
        state.encoder = None
        state.cancelled = True
        state.recording = False
        state.transcribing = False
        state.predict_mode = False
        state.note_mode = False
        state.audio_chunks = []
        return stream, encoder


def stash_retry_buffer(audio_chunks_copy: list, mode: dict) -> None:
    with state.lock:
        state.retry_buffer = audio_chunks_copy
        state.retry_count = 0
        state.retry_mode_snapshot = mode


def clear_retry() -> None:
    with state.lock:
        state.retry_buffer = None
        state.retry_count = 0
        state.retry_in_progress = False
        state.retry_mode_snapshot = None
