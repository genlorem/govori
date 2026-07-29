---
phase: 01-security-safety
plan: 01
subsystem: security
tags: [shell-injection, subprocess, privacy-notice, onboarding]

# Dependency graph
requires: []
provides:
  - "Shell injection fix (os.system eliminated)"
  - "Privacy notice in onboarding (en/ru)"
  - "4-step onboarding flow (was 3)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "subprocess.run with list args for external process execution"

key-files:
  created: []
  modified:
    - "govori.py"

key-decisions:
  - "Privacy notice is informational-only (no confirmation prompt) per D-02"

patterns-established:
  - "subprocess.run([cmd, arg]) pattern for all external process calls"
  - "Bilingual onboarding strings keyed in SETUP_STRINGS dict"

requirements-completed: [SEC-01, SEC-04]

# Metrics
duration: 2min
completed: 2026-04-17
---

# Phase 01 Plan 01: Shell Injection Fix and Privacy Notice Summary

**Replaced os.system shell injection with subprocess.run list-form and added bilingual privacy notice to 4-step onboarding**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-17T16:41:14Z
- **Completed:** 2026-04-17T16:42:49Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Eliminated the only shell injection vector in the codebase (os.system -> subprocess.run with list args)
- Added privacy disclosure for OpenAI/Anthropic data flow in both English and Russian
- Updated onboarding from 3-step to 4-step flow with correct numbering across both languages

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix shell injection -- replace os.system with subprocess.run** - `14dce2b` (fix)
2. **Task 2: Add privacy notice to onboarding and update step numbering** - `403159c` (feat)

## Files Created/Modified
- `govori.py` - Replaced os.system with subprocess.run; added step_privacy strings (en/ru); renumbered all step headers from X/3 to X/4; inserted privacy notice print in cli_setup()

## Decisions Made
- Privacy notice is informational-only (no confirmation prompt) per D-02 design decision

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SEC-01 and SEC-04 resolved; govori.py ready for Plan 02 (error handling patterns) and Plan 03 (HUD error states)
- No blockers

## Self-Check: PASSED

- govori.py: FOUND
- 01-01-SUMMARY.md: FOUND
- Commit 14dce2b (Task 1): FOUND
- Commit 403159c (Task 2): FOUND

---
*Phase: 01-security-safety*
*Completed: 2026-04-17*
