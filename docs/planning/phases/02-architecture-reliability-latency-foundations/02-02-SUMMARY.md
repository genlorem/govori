---
phase: 02-architecture-reliability-latency-foundations
plan: 02
subsystem: transcribe
tags: [python, openai-sdk, httpx, loguru, instrumentation, fallback, connection-pool]

requires:
  - phase: 02-01
    provides: govori/ package + AppState + loguru + fn_release_ts field
provides:
  - PERF-01 instrumentation (per-stage time.perf_counter spans + BENCH_MODE summary)
  - REL-05 Groq→OpenAI transcription fallback
  - Per-provider httpx connection pool (TLS keepalive across dictations)
affects: [phase-4-parallel-encoding, transcription-reliability]

tech-stack:
  added: [httpx (already a transitive dep via openai SDK)]
  patterns: [per-provider client cache, frozen Provider dataclass, contextmanager spans, atexit summary]

key-files:
  created:
    - govori/instrument.py
  modified:
    - govori/transcribe.py  # full rewrite of provider/client layer
    - govori/audio.py        # spans + dispatcher swap
    - govori/hotkey.py       # perf_counter for fn_release_ts
    - govori/macos.py        # perform_shutdown closes pool
    - govori/notes.py        # uses transcribe_with_fallback
    - govori/predict.py      # uses _get_predict_client (renamed helper)

key-decisions:
  - "Predict mode reuses the primary (Groq) provider client via _get_predict_client — Groq endpoint serves chat completions for predict_model."
  - "fn_release_ts in hotkey.py uses time.perf_counter() (was time.time()) for monotonic span math with audio.py."
  - "retry_transcription wraps its call in span('retry_total') so HUD-click retries show up separately in the BENCH summary."

patterns-established:
  - "Provider dataclass + lazy _get_provider/_get_client cache."
  - "Each provider gets its own DefaultHttpxClient (no shared TLS pool across Groq/OpenAI)."
  - "span() is a contextmanager; record_event() for cross-thread/cross-file spans (fn_release_to_stop, end_to_end)."

requirements-completed: [REL-05, PERF-01]

duration: ~45min (Claude inline; Codex unavailable due to xhigh limit)
completed: 2026-05-13T18:15:00+0500
---

# Phase 02-02 Summary

**Transcription path now emits per-stage timing to govori.log, falls back to OpenAI on Groq transient failures, and reuses TLS connections between dictations.**

## What changed

- `govori/instrument.py` (new): `span()` contextmanager + `record_event()` for cross-thread timings + `atexit`-registered BENCH_MODE p50/p95/mean summary table.
- `govori/transcribe.py` rewritten: `Provider` dataclass; lazy per-provider client cache (`_clients`); `_build_http_client` returns `DefaultHttpxClient` with explicit `Limits(max_connections=10, max_keepalive_connections=5, keepalive_expiry=30.0)`; `transcribe_with_fallback` dispatcher; `close_clients()` for shutdown; `_get_predict_client()` exposed for predict.py.
- `govori/audio.py::stop_and_transcribe`: wraps body in `span("stop_total")`; adds spans for `audio_concat`, `transcribe_full`, `paste`; records `fn_release_to_stop` (from `state.fn_release_ts` written by hotkey.py) and `end_to_end` via `record_event`. Switches from `_transcribe_with_auto_retries` to `transcribe_with_fallback`.
- `govori/hotkey.py`: captures `time.perf_counter()` into `state.fn_release_ts` on fn-up (was `time.time()` — now monotonic).
- `govori/macos.py::perform_shutdown`: also calls `transcribe.close_clients()` so httpx pools release before exit.
- `govori/notes.py` + `govori/predict.py`: updated to use the new public symbols (`transcribe_with_fallback`, `_get_predict_client`).

## Verification

| Check | Result |
|-------|--------|
| All 3 Task automated `<verify>` blocks | PASS |
| Mocked: transient → fallback runs with max_retries=1 | PASS |
| Mocked: PERMANENT_API_ERROR short-circuits, fallback NOT called | PASS |
| Mocked: missing OPENAI_API_KEY → degrades to None gracefully | PASS |
| `_build_http_client()` returns `DefaultHttpxClient` instance | PASS |
| `python -m govori --help` exits cleanly | PASS |
| Import smoke test (`tests/test_imports.py`) | PASS |
| All grep-based acceptance criteria (spans, fallback symbols, pool config) | PASS |

## Skipped / Manual checks

- **BENCH_MODE end-to-end with real dictation**: blocked because the user has a long-running old monolith at PID 30247 (singleton refuses second instance). User must stop the old daemon and run `BENCH_MODE=1 python -m govori` themselves to collect the first sample distribution.
- **TLS pool reuse measurement**: requires two consecutive real dictations; same blocker as above. The structural test confirms pool config is correct.
- **Live Groq→OpenAI fallback test**: requires temporarily setting an invalid `GROQ_API_KEY`; user can do this manually.

## Deviations from plan

1. **`_get_predict_client` added** — plan didn't address that `predict.py` previously imported `_get_openai_client` from transcribe.py. Rather than restore the deleted helper, exposed a typed accessor that reuses the primary (Groq) client; predict_model lives on the same endpoint.
2. **Plan said state.py NOT modified** — confirmed. `fn_release_ts` was already in AppState from Plan 02-01.
3. **No Codex delegation** — xhigh limit hit before 02-02 started, so this plan was executed inline by Claude Opus 4.7 rather than Codex GPT-5.5.

## Open items for Phase 4

- First real BENCH_MODE p50 numbers per stage (the 1.5s gap from spike 001 lives somewhere — Phase 4 needs that table to target the biggest contributor).
- Whether `encode` is the dominant cost (motivates parallel encoding) or whether it's something else (e.g., `transcribe_full − provider_primary` overhead).

---
*Phase: 02-architecture-reliability-latency-foundations*
*Completed: 2026-05-13*
