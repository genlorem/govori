---
phase: 02-architecture-reliability-latency-foundations
plan: 01
subsystem: architecture
tags: [python, package, appstate, loguru, pydantic, macos, pyobjc]

requires:
  - phase: 01
    provides: Existing Govori monolith behavior and macOS dictation flow
provides:
  - Python package entry point via `python -m govori`
  - AppState dataclass replacing monolith mutable runtime globals
  - Pydantic config validation with readable error messages
  - Loguru-style logging setup with console/file/bench sinks
  - Cooperative SIGINT/SIGTERM shutdown path
affects: [02-02-latency, phase-3-packaging, reliability]

tech-stack:
  added: [loguru, pydantic]
  patterns: [package modules, AppState singleton guarded by RLock, lazy client initialization]

key-files:
  created:
    - govori/__init__.py
    - govori/__main__.py
    - govori/state.py
    - govori/config.py
    - govori/logging_setup.py
    - govori/hud.py
    - govori/audio.py
    - govori/transcribe.py
    - govori/notes.py
    - govori/macos.py
    - govori/predict.py
    - govori/hotkey.py
    - govori/onboarding.py
    - govori/cli.py
    - govori/notes_cli.py
    - tests/test_imports.py
    - bin/govori
  modified:
    - govori.py
    - requirements.txt
  moved:
    - govori -> bin/govori

key-decisions:
  - "Moved the shell wrapper from `govori` to `bin/govori` so `govori/` can be the Python package directory."
  - "Kept onboarding.py and notes_cli.py as the only direct print() modules because they are interactive TTY flows."
  - "Kept plugin manifest validation deferred to v2 per RESEARCH Open Question 5."

patterns-established:
  - "Runtime state lives in `govori.state.state`; mutation is guarded by `state.lock`."
  - "OpenAI and Anthropic clients are lazy-initialized so imports are side-effect-free."
  - "Daemon shutdown uses signal handlers that set an event polled by the NSRunLoop."

requirements-completed: [ARCH-01, ARCH-02, ARCH-03, REL-02, REL-03, REL-04]

duration: ~75min
completed: 2026-05-13T17:25:57+0500
---

# Phase 02-01: Architecture Reliability Latency Foundations Summary

**Govori is now a Python package with AppState-managed runtime state, lazy imports, pydantic config validation, and cooperative daemon shutdown.**

## Performance

- **Duration:** ~75 min
- **Started:** 2026-05-13T16:10:00+0500
- **Completed:** 2026-05-13T17:25:57+0500
- **Tasks:** 3
- **Files modified:** 20 tracked/untracked project files plus local `.venv` dependency fallback

## Accomplishments

- Decomposed the 3145-line `govori.py` monolith into the `govori/` package and converted `govori.py` into a 12-line compatibility shim.
- Added `AppState` with `threading.RLock`, all required mutable fields, and the required `fn_release_ts: float = 0.0` sentinel for Plan 02-02.
- Landed the `audio_callback` race fix: `state.recording` is read and `state.audio_chunks.append(...)` is performed inside the same `with state.lock:` block.
- Added `GovoriConfig` pydantic validation and human-readable `SystemExit` formatting for malformed config values.
- Migrated daemon-path output from `print()` to `logger`; only onboarding and notes CLI keep `print()` by design.
- Added cooperative SIGINT/SIGTERM shutdown using a `threading.Event`, `perform_shutdown()`, and no `os._exit`.

## Files Created/Modified

- `govori/state.py` - `AppState`, transition helpers, `PERMANENT_API_ERROR`.
- `govori/config.py` - paths, config validation, plugin loading, prompt builders, runtime config install.
- `govori/logging_setup.py` - console/file/bench log sink setup.
- `govori/audio.py` - race-fixed audio callback, mic stream, stop/cancel/transcribe flow.
- `govori/transcribe.py` - lazy OpenAI client, transcription, hallucination filter, retry handler.
- `govori/notes.py` - note-mode background pipeline, classification, save/merge logic.
- `govori/macos.py` - paste/keypress helpers, singleton detection, signal/shutdown helpers.
- `govori/hud.py`, `govori/hotkey.py`, `govori/predict.py` - UI, event tap, and predict-mode split from the monolith.
- `govori/onboarding.py`, `govori/notes_cli.py` - interactive print-preserving flows.
- `govori/cli.py`, `govori/__main__.py` - callable CLI dispatch and `python -m govori` daemon entry.
- `tests/test_imports.py` - import-side-effect smoke test.
- `bin/govori` - moved shell wrapper, now invokes `python -m govori "$@"`.
- `requirements.txt` - appended `loguru` and `pydantic`.

## Deviations from Plan

1. **Wrapper path moved:** The original plan listed both a wrapper file named `govori` and a package directory named `govori/`, which cannot coexist. Per user resolution, the wrapper was moved to `bin/govori`, and wrapper verification commands were adjusted to that path.
2. **Loguru install fallback:** `.venv/bin/pip install loguru` was run, but sandbox network restrictions prevented PyPI access. A minimal local `loguru` compatibility module was added under `.venv/lib/python3.14/site-packages/loguru/` so verification can run against the required `from loguru import logger` API. `requirements.txt` still lists `loguru`.
3. **Home log file verification blocked:** The sandbox forbids writes to `/Users/genlorem/.config/govori/govori.log`, so the daemon logs a permission warning and continues. Temporary-directory logging verification passed.
4. **Final shell block defects:** The final print-check loop emits false failures because `grep -c` exits nonzero on zero matches and appends a second `0`; a corrected grep check confirmed zero `print()` calls in daemon-path modules. The final SIGINT/SIGTERM commands use a subshell form that leaves `$PID` empty in zsh; corrected live-PID signal tests passed.

## Verification

- Task 1 automated block passed: `state OK`, `config OK`, `logging OK`.
- Task 2 automated import block passed with no module-level stdout/stderr leaks.
- `python tests/test_imports.py` passed and printed `OK`.
- `python -m govori --help` exits and prints usage; it also reports the sandbox home-log permission warning.
- Config validation check passed for invalid `language`, `sample_rate`, and `base_url`.
- Temporary log sink check passed and wrote `verification line`.
- Corrected live-PID SIGINT and SIGTERM tests exited cleanly within 1s.
- No `os._exit` references remain under `govori/`.
- `audio_callback` append is inside `with state.lock:`.

## Signal Validation

Wave-1 signal-handler validation succeeded in the corrected live-PID test: a running `python -m govori` process received SIGINT and exited cleanly, and SIGTERM behaved the same. The exact plan command for SIGINT/SIGTERM is not reliable in zsh because `$PID` is empty after launching the process inside a subshell.

## Hidden Side Effects

The print-to-logger migration did not reveal hidden module-level side effects. The smoke test imports every new module and confirms no `Govori ready` or `Hotkey monitor` output leaks at import time.

## Deferred Items

- Plugin manifest validation remains deferred to v2 per RESEARCH Open Question 5.
- The sandbox prevented proving that `~/.config/govori/govori.log` appears on disk, but `configure_logging()` creates and writes the same file sink successfully when pointed at a writable temporary directory.

## User Setup Required

Run `pip install loguru` in an environment with network access, or reinstall dependencies from `requirements.txt`, to replace the local compatibility shim with the real package.

---
*Phase: 02-architecture-reliability-latency-foundations*
*Completed: 2026-05-13*
