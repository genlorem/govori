#!/usr/bin/env python3
"""Bench Phase 4: parallel encoding vs serial encoding.

Simulates a recording session: chunks arrive over time (like sounddevice
audio_callback), then fn is released. Measures how long each path takes
from fn-release to having a BytesIO ready for the API.

Old path: collect all chunks → encode full audio at stop
New path: ParallelEncoder encodes during recording → flush only tail at stop

Run:
    .venv/bin/python bench/encoding_bench.py
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import av
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

# Stub macOS-only modules
import unittest.mock as mock
for _mod in ["AppKit", "Foundation", "Cocoa", "objc"]:
    sys.modules.setdefault(_mod, mock.MagicMock())

import govori.config as cfg
cfg.SAMPLE_RATE = 16000


def make_audio(duration_s: float, freq: float = 440.0) -> np.ndarray:
    t = np.linspace(0, duration_s, int(duration_s * cfg.SAMPLE_RATE), endpoint=False)
    return (np.sin(2 * np.pi * freq * t) * 0.5).astype(np.float32)


def serial_encode(audio: np.ndarray) -> io.BytesIO:
    """Current (pre-Phase-4) encoding path: full audio at once."""
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.9
    buf = io.BytesIO()
    buf.name = "audio.ogg"
    audio_int16 = (audio * 32767).astype(np.int16)
    container = av.open(buf, mode="w", format="ogg")
    stream = container.add_stream("libopus", rate=cfg.SAMPLE_RATE, layout="mono")
    frame = av.AudioFrame.from_ndarray(audio_int16.reshape(1, -1), format="s16", layout="mono")
    frame.rate = cfg.SAMPLE_RATE
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    buf.seek(0)
    return buf


def bench_duration(duration_s: float, chunk_samples: int = 1024, n_runs: int = 8) -> dict:
    """
    Measures:
      - serial_ms: time to encode at fn-release (old path, no parallelism)
      - flush_ms: time to flush tail at fn-release (Phase 4 path)

    The parallel encoder starts when "recording" begins and runs during
    the simulated recording time. At fn-release it only flushes the tail.
    """
    from govori.transcribe import ParallelEncoder

    audio = make_audio(duration_s)
    chunks = [
        audio[i : i + chunk_samples].reshape(-1, 1).copy()
        for i in range(0, len(audio), chunk_samples)
    ]

    serial_times = []
    flush_times = []

    for _ in range(n_runs):
        # ── old path: serial encode at fn-release ────────────────────────
        t0 = time.perf_counter()
        serial_encode(audio)
        serial_times.append((time.perf_counter() - t0) * 1000)

        # ── new path: parallel encode during "recording", flush at stop ──
        enc = ParallelEncoder()

        # Feed all but the last chunk, then wait for the encoder to drain the
        # queue — this replicates production: chunks arrive every ~64ms so the
        # encoder is never backed up; at fn-release only the tail is left.
        for c in chunks[:-1]:
            enc.feed(c)
        # Drain: wait until the background thread has consumed everything
        while not enc._q.empty():
            time.sleep(0.001)
        time.sleep(0.002)  # one more tick so the current chunk finishes encoding

        # fn-release: only the last chunk needs encoding
        t1 = time.perf_counter()
        enc.feed(chunks[-1])
        enc.flush(timeout=5.0)
        flush_times.append((time.perf_counter() - t1) * 1000)

    def p50(xs):
        s = sorted(xs)
        return s[len(s) // 2]

    def p95(xs):
        s = sorted(xs)
        return s[int(len(s) * 0.95)]

    return {
        "duration_s": duration_s,
        "serial_p50": p50(serial_times),
        "serial_p95": p95(serial_times),
        "flush_p50": p50(flush_times),
        "flush_p95": p95(flush_times),
        "savings_p50": p50(serial_times) - p50(flush_times),
    }


def main():
    durations = [2.0, 5.0, 10.0, 20.0, 30.0]
    print(f"\n{'Dur':>5} │ {'Serial p50':>10} {'Serial p95':>10} │ {'Flush p50':>9} {'Flush p95':>9} │ {'Saved p50':>9}")
    print("─" * 70)
    for d in durations:
        r = bench_duration(d)
        print(
            f"{d:>4.0f}s │ {r['serial_p50']:>9.1f}ms {r['serial_p95']:>9.1f}ms │"
            f" {r['flush_p50']:>8.1f}ms {r['flush_p95']:>8.1f}ms │ {r['savings_p50']:>8.1f}ms"
        )
    print()
    print("Serial = encode full audio at fn-release (old path)")
    print("Flush  = encoder ran during recording; only flush tail (Phase 4)")
    print("Saved  = latency eliminated from the critical path")


if __name__ == "__main__":
    main()
