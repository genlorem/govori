---
phase: quick
plan: 260422-bgo
subsystem: hotkey/recording
tags: [race-condition, fn-key, threading, recording]
key-files:
  modified:
    - govori.py
decisions:
  - Quick-tap cancel must fire unconditionally (before recording=True is set) to close the race
  - cancelled flag check in start_recording() is the right place to handle the "fn-up beat the thread" case
metrics:
  duration: ~5m
  completed: 2026-04-22
---

# Quick Task 260422-bgo: Fix Race Condition — fn Released Before start_recording() Ran

**One-liner:** Two surgical edits close the quick-tap race: fn-up always cancels on short holds, and start_recording() aborts silently if the cancel signal arrived first.

## Tasks Completed

| Task | Commit | Description |
|------|--------|-------------|
| 1 — Unconditional quick-tap cancel in fn-up branch | 0603c59 | Moved `held` computation outside `if recording:`, fires cancel thread regardless of recording state |
| 2 — Early-return guard in start_recording() | 0775cd2 | Checks `if cancelled:` before setting `recording=True`; resets flag and returns without starting mic |

## What Was Fixed

**Race:** fn held < 200ms → fn-up fires → `if recording:` is False (thread hasn't run yet) → cancel skipped → thread runs → `recording=True` → mic stream starts and can never stop.

**Fix 1 (cg_event_callback):** The `held` time is now computed unconditionally. On quick tap the cancel thread is spawned without checking `recording`. The stop-and-transcribe dispatch retains its `elif recording:` guard.

**Fix 2 (start_recording):** After acquiring `_state_lock`, if `cancelled` is already True it means fn-up beat this thread to the lock. The function resets the flag and returns early — `recording` stays False, no mic stream is opened.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- govori.py modified: FOUND
- Commit 0603c59: FOUND
- Commit 0775cd2: FOUND
- AST syntax check: PASSED

## Self-Check: PASSED
