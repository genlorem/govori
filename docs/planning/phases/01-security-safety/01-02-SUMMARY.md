---
phase: 01-security-safety
plan: 02
subsystem: ui, api
tags: [openai, timeout, hud, retry, nswindow, cocoa, error-handling]

# Dependency graph
requires:
  - phase: 01-01
    provides: "Existing HUD setup_hud/set_hud pattern, govori.py architecture"
provides:
  - "HUD error infrastructure (tooltip panel, error_retryable/error_fatal modes, click handler)"
  - "API timeout (30s) with specific exception handling"
  - "Retry buffer mechanism with click-to-retry (max 3 attempts)"
  - "Bilingual tooltip strings (en/ru)"
affects: [01-03, reliability, error-handling]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "HUD error modes with clickable gesture recognizer"
    - "Tooltip companion NSPanel for contextual error messages"
    - "Retry buffer pattern: save raw audio_chunks on failure for re-transcription"
    - "Specific OpenAI exception handling (APITimeoutError, APIConnectionError, APIStatusError)"

key-files:
  created: []
  modified:
    - govori.py

key-decisions:
  - "max_retries=0 on OpenAI client to prevent hidden SDK auto-retry (surfaces errors in 30s not 90s)"
  - "Retry buffer stores raw audio_chunks list, not encoded OGG -- enables re-encoding on retry"
  - "Retry always uses dictation path (paste_text) even if original was note mode -- audio preservation is the priority"

patterns-established:
  - "Error mode HUD pattern: set_hud(True, mode='error_retryable', tooltip=_tooltip('key'))"
  - "Tooltip companion panel pattern: NSPanel at x=42 next to HUD"
  - "HUDClickHandler NSObject subclass with NSClickGestureRecognizer"

requirements-completed: [SEC-03]

# Metrics
duration: 4min
completed: 2026-04-17
---

# Phase 01 Plan 02: HUD Error Infrastructure + API Timeout Summary

**HUD error modes with tooltip panel, 30s API timeout, and click-to-retry mechanism using buffered audio**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-17T16:25:50Z
- **Completed:** 2026-04-17T16:29:34Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Built tooltip companion NSPanel (240px, bilingual en/ru) positioned next to HUD for error context
- Added error_retryable (amber recycling arrow with slow pulse) and error_fatal (red cross, static) HUD modes
- Set 30s API timeout with max_retries=0 on OpenAI client constructor
- Replaced broad except Exception with specific openai.APITimeoutError/APIConnectionError/APIStatusError
- Wired retry buffer: audio_chunks saved on transcription failure, click-to-retry re-encodes and re-transcribes (max 3 attempts)

## Task Commits

Each task was committed atomically:

1. **Task 1: HUD error infrastructure** - `26bfc3d` (feat)
2. **Task 2: API timeout with error handling and retry buffer wiring** - `ced0833` (feat)

## Files Created/Modified
- `govori.py` - Added TOOLTIP_STRINGS dict, _tooltip() helper, tooltip NSPanel, HUDClickHandler class, error_retryable/error_fatal HUD modes, _retry_buffer/_retry_count globals, _retry_transcription(), 30s timeout on OpenAI client, specific exception catches

## Decisions Made
- Used max_retries=0 on OpenAI client to prevent hidden SDK auto-retry (per RESEARCH.md Pitfall 1)
- Retry buffer stores raw audio_chunks (list of numpy arrays) rather than encoded OGG -- re-encoding on each retry attempt ensures fresh buffer state
- Retry always pastes via dictation path even if original recording was in note mode -- saves the expensive audio, user can re-record for note classification

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- HUD error infrastructure complete, provides foundation for SEC-02 (permission/microphone errors) and REL-01
- error_retryable and error_fatal modes ready for use by other error surfaces
- Tooltip panel ready for permission-denied and accessibility-revoked messages

---
*Phase: 01-security-safety*
*Completed: 2026-04-17*
