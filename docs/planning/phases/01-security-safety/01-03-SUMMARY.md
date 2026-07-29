---
phase: 01-security-safety
plan: 03
subsystem: reliability
tags: [cgeventtap, portaudio, health-check, accessibility, microphone]

requires:
  - phase: 01-02
    provides: "HUD error_fatal mode with tooltip and click handler infrastructure"
provides:
  - "CGEventTap health monitoring daemon thread (SEC-02)"
  - "Microphone startup warning and recording-time error handling (REL-01)"
affects: []

tech-stack:
  added: []
  patterns:
    - "Daemon health-check thread polling macOS API state every 7s"
    - "Two-stage hardware check: non-blocking startup warning + runtime error with HUD"

key-files:
  created: []
  modified:
    - govori.py

key-decisions:
  - "Health check polls every 7s per D-09 -- within 5-10s range, balances responsiveness vs CPU"
  - "Startup mic check prints terminal warning only -- no HUD, no exit, user can plug in later"

patterns-established:
  - "Daemon thread pattern: while True + time.sleep(N) for polling macOS API state"
  - "State recovery pattern: detect failure -> attempt fix -> show error -> auto-clear on recovery"

requirements-completed: [SEC-02, REL-01]

duration: 2min
completed: 2026-04-17
status: checkpoint-pending
---

# Phase 01 Plan 03: CGEventTap Health + Mic Error Handling Summary

**CGEventTap health monitoring daemon polling every 7s with auto-recovery, plus two-stage microphone error handling (startup warning + recording-time red HUD)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-17T16:34:03Z
- **Completed:** pending (checkpoint:human-verify)
- **Tasks:** 2/3 (Task 3 is human verification checkpoint)
- **Files modified:** 1

## Accomplishments
- CGEventTap health check daemon thread detects revoked Accessibility within 7s, shows red HUD with tooltip, attempts re-enable, auto-recovers
- Microphone startup check prints terminal warning without exiting when no mic detected
- Recording-time mic failure catches sd.PortAudioError, resets state, shows red HUD with appropriate tooltip (no_mic or mic_denied)

## Task Commits

Each task was committed atomically:

1. **Task 1: CGEventTap health monitoring daemon thread (SEC-02)** - `e3512a8` (feat)
2. **Task 2: Microphone error handling -- startup warning and recording failure (REL-01)** - `a6f7941` (feat)
3. **Task 3: Human verification of all Phase 1 security and safety changes** - PENDING (checkpoint:human-verify)

## Files Created/Modified
- `govori.py` - Added _tap_health_check() daemon thread, install_monitor() return tap, start_recording() PortAudioError handling, __main__ startup mic check

## Decisions Made
- Followed plan as specified -- all decisions locked in prior planning (D-07, D-09 through D-14)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Checkpoint Pending

Task 3 (`checkpoint:human-verify`) requires human verification of all 5 Phase 1 requirements:
- SEC-01: Shell injection fix (no os.system)
- SEC-02: CGEventTap health monitoring
- SEC-03: API timeout with retry HUD
- SEC-04: Privacy notice in onboarding
- REL-01: Microphone error handling

---
*Phase: 01-security-safety*
*Completed: pending checkpoint*
