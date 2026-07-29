# Phase 2: Architecture & Reliability + Latency Foundations — Research

**Researched:** 2026-05-13
**Domain:** Python package decomposition, structured logging, state management, HTTP client pooling, multi-provider transcription fallback
**Confidence:** HIGH (architecture / loguru / openai-sdk) — MEDIUM (signal handling in NSRunLoop) — LOW (REL-05 fallback ordering trade-offs)

## Summary

Phase 2 takes a 3,145-line monolith (`govori.py`) and extracts it into a proper Python package while landing four orthogonal reliability improvements: structured logging, explicit state, clean shutdown, and config validation. **Three of the eight success criteria are latency/transcribe-module changes** (PERF-01 instrumentation, REL-05 Groq→OpenAI fallback, HTTP connection pooling) — they belong to this phase only because the `transcribe` module is being carved out anyway. Bolting them on while everything else is in flux is cheaper than two passes.

The monolith already has the architectural seams in place — ASCII section separators map almost 1:1 to target modules (Paths → `config`, Audio → `audio`, etc.), and `_state_lock` already guards the 11 mutable globals, so the extraction is mechanical rather than conceptual. The harder design questions are: (1) whether AppState should be frozen-immutable with `replace()` or mutable-with-lock (recommend the latter — locking is already in place), (2) where to inject the per-provider HTTP client to actually get keep-alive (recommend module-level singleton in `transcribe`), and (3) how to wire `signal.signal(SIGINT)` so it actually fires inside `NSRunLoop` (recommend swapping `os._exit(0)` for `NSApp.terminate_(None)` triggered by a shared shutdown event — current implementation is broken-by-design but works due to `os._exit`).

**Primary recommendation:** Land architecture first (modules + AppState + loguru + signal handling + config validation), then layer transcribe-only changes (per-provider clients + fallback + PERF-01 spans) on top. The transcribe work depends on the new module structure for clean seams; doing it first would mean rewriting it twice.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Module decomposition (ARCH-01) | Python package (`govori/`) | — | Source tree reorganization, no runtime tier change |
| AppState dataclass (ARCH-02) | In-process Python | — | Shared in-memory state; lives wherever the daemon runs |
| Loguru file logging (REL-02) | Filesystem (`~/.config/govori/govori.log`) | stdout/stderr | File is durable, console mirrors for foreground runs |
| Signal handling (REL-03) | Process-level (NSApplication + signal module) | — | macOS NSRunLoop owns the main thread; signal must integrate |
| Config validation (REL-04) | Filesystem (`~/.config/govori/config.yaml`) | — | YAML parsed at startup, validated before use |
| PERF-01 instrumentation | In-process timing (`time.perf_counter`) | loguru sink | Spans recorded as structured log events |
| REL-05 fallback | API tier (Groq primary, OpenAI fallback) | — | Two cloud providers, single decision point in `transcribe` |
| HTTP connection pool | httpx client (in-process) | — | One singleton per provider, reused across dictations |
| CLI entry point (ARCH-03) | OS process (pyproject `[project.scripts]`) | — | `govori` command installed via pipx — feeds Phase 3 |

## User Constraints (from CONTEXT.md)

**No CONTEXT.md exists for Phase 2** — `/gsd-discuss-phase` was not run for this phase. All decisions are at Claude's discretion within the success criteria locked in ROADMAP.md.

### Locked Decisions (from ROADMAP/REQUIREMENTS)

1. govori.py must be replaced by a `govori/` package (ARCH-01)
2. Module list is fixed: `config, state, hud, audio, transcribe, notes, macos, predict, cli` (ARCH-01, plus `__main__` per REQUIREMENTS)
3. Loguru is the chosen logger (per STATE.md decision log: "loguru over stdlib logging") — no alternative needed
4. AppState dataclass replaces 11 globals (ARCH-02)
5. Log destination: `~/.config/govori/govori.log` with rotation (REL-02)
6. Clean shutdown: no `os._exit(0)` (REL-03)
7. Config validation must produce human-readable errors, not silent `{}` (REL-04)
8. REL-05 fallback path is Groq → OpenAI (not OpenAI → Groq) — Groq is already configured as primary via `base_url`
9. PERF-01 stages are exactly: `stop_and_transcribe → encode → API → paste`
10. BENCH_MODE environment variable triggers per-stage summary (REQ wording: "running `./govori --bench-mode` (or similar)" — flag and env var both acceptable)
11. Single HTTP client per provider (no per-request instantiation)

### Claude's Discretion

- Mutable vs frozen AppState (recommend mutable + reuse existing `_state_lock`)
- pydantic vs cerberus vs hand-rolled for config validation (recommend pydantic — already installed as transitive dep, see Standard Stack)
- BENCH_MODE: env var vs CLI flag (recommend env var — matches the `BENCH_ITER` precedent in `bench/latency_bench.py`)
- Signal handling: bare `signal.signal` vs `NSApplicationDelegate.applicationWillTerminate_` (recommend signal + shared event)
- Span-recording mechanism: contextmanager vs dataclass vs ContextVar (recommend `@contextmanager` + loguru `bind()`)
- Number of OpenAI fallback retries (recommend 1 attempt at OpenAI — Groq already gets 1+2 retries via `_transcribe_with_auto_retries`)

### Deferred Ideas (OUT OF SCOPE — these belong to Phase 3 or v2)

- Adding pytest infrastructure (Phase 3 DIST-04)
- Removing `soundfile` from requirements.txt (Phase 3 housekeeping)
- Hardcoded model names refactor (v2 cleanup, not in any phase)
- Local Whisper STT (v2 ARCH-04)
- Native HUD overlay replacing Hammerspoon (v2 ARCH-05)
- Clipboard race fix (v2 REL-06)
- Parallel encoding (Phase 4 — but PERF-01 instrumentation here is the prerequisite)
- pyproject.toml entry point wiring (Phase 3 DIST-01) — though ARCH-03 calls for `govori.cli:main` to be _callable_, actual `[project.scripts]` declaration is Phase 3

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ARCH-01 | Module extraction: `config, state, hud, audio, transcribe, notes, macos, predict, cli, __main__` | See **Module Decomposition Plan** below — 1:1 mapping from existing ASCII-separated sections |
| ARCH-02 | Replace 11 mutable globals with AppState dataclass + explicit transitions | See **AppState Design** below — recommend mutable dataclass + `RLock` (extend current `_state_lock` pattern) |
| ARCH-03 | `govori.cli:main()` callable from `pyproject.toml` scripts | Make `cli.py` expose `main()`; `__main__.py` just calls it. Actual `[project.scripts]` wire-up is Phase 3 (DIST-01) |
| REL-02 | Loguru file logging at `~/.config/govori/govori.log` with rotation | See **Loguru Integration** — recommend size-based 10 MB rotation, retention 30 days, `enqueue=True` |
| REL-03 | Graceful shutdown — proper signal handling, audio stream cleanup, no `os._exit(0)` | See **Signal Handling on NSRunLoop** — `signal.signal(SIGINT, _request_shutdown)` + cooperative `NSApp.terminate_(None)` |
| REL-04 | Config validation: invalid YAML → user-friendly error, not silent `{}` | See **Config Validation** — recommend pydantic (already installed) with custom `model_validator` for path expansion |
| REL-05 | Groq 5xx/timeout/connection-error → automatic OpenAI fallback if `OPENAI_API_KEY` present | See **REL-05 Fallback Strategy** — wrap `_encode_and_transcribe` with provider-routing layer; reuse existing retry budget |
| PERF-01 | Instrument `stop_and_transcribe → encode → API → paste` with `time.perf_counter()`; structured events; `BENCH_MODE` summary | See **PERF-01 Instrumentation** — `@contextmanager` span helper + loguru `extra={"stage": ...}` + atexit summary printer |

## Project Constraints (from CLAUDE.md)

The repo-level CLAUDE.md is mostly user/global rules (debugging discipline, response style). Project-specific directives extracted:

- **GSD workflow enforcement is active.** All edits go through `/gsd-execute-phase` or equivalent commands — plans should NOT bypass with raw edits.
- **Single-file architecture is being abandoned.** Phase 2 _is_ the abandonment work; don't second-guess it.
- **Debug discipline (global):** Identify root cause before fixing. Don't patch symptoms. Fix at owner layer, not where the symptom surfaces. Be skeptical of one-file fixes. — Applies to research recommendations: prefer cohesive modules over scattered shims.
- **Response language: Russian.** Technical artifacts (code, RESEARCH.md) can stay English; conversational responses to user should be Russian. (This is a researcher hint, not a code-output constraint.)
- **Bug Fix Protocol:** Find root cause → minimal fix → don't patch symptom. — Inform extraction: don't carry forward known bugs unchanged; fix the small ones during extraction (e.g., `delayed_start()` stale-closure bug noted in CONCERNS.md is dead code in current state since the function was removed during phase 01.1, verified by `grep -n "delayed_start" govori.py` returning nothing).
- **No tests today** — CLAUDE.md confirms project has no test framework. Phase 2 should leave _test seams_ behind (importable modules with mockable boundaries), but adding pytest is Phase 3 work.

## Standard Stack

### Core (already in project)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `openai` | 2.36.0 latest / 2.32.0 installed | Whisper API client (used against both OpenAI native + Groq via `base_url`) | Official; Groq is OpenAI-API-compatible per [Groq docs](https://console.groq.com/docs/speech-to-text) [CITED] |
| `httpx` | 0.28.1 (transitive via openai) | Underlying HTTP client; controls keep-alive pool | OpenAI SDK exposes `http_client` parameter accepting custom `DefaultHttpxClient` [CITED: github.com/openai/openai-python] |
| `numpy` | 2.4.4 | Audio array math | Already used in `_encode_and_transcribe` |
| `av` (PyAV) | 17.0.1 | OGG/Opus encoding | Already used; not touched in Phase 2 |
| `sounddevice` | 0.5.5 | PortAudio binding | Already used; cleanup behaviour relevant for REL-03 |
| `pyobjc-core` | 12.1 | Quartz / AppKit bridge | Already used; relevant for signal-handling research |
| `PyYAML` | 6.0.3 | YAML parsing | Already used for config |

### New for Phase 2

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `loguru` | 0.7.3 (latest) | Structured file logging with rotation | Project decision logged in STATE.md (`loguru over stdlib logging`); rich rotation/retention/`bind()` semantics out-of-box [VERIFIED: Context7 /delgan/loguru] |
| `pydantic` | 2.13.4 latest / 2.12.5 installed | Config validation with rich error messages | **Already installed transitively** (likely via openai or anthropic dep chain) — adopting it adds zero new install footprint [VERIFIED: pip list output] |

**Already-installed pydantic confirmation:** `/Users/genlorem/Projects/govori/.venv/bin/pip list` shows `pydantic 2.13.2 / pydantic_core 2.46.2`. The OpenAI Python SDK declares pydantic as a runtime dep, so it's transitively present. Using it for config validation costs nothing in install size. [VERIFIED: local pip list 2026-05-13]

**Version verification (run before writing pyproject.toml in Phase 3):**

```bash
npm view openai version          # → 6.37.0 (which is for the npm wrapper, ignore — use pip)
pip index versions openai        # → 2.36.0 latest
pip index versions loguru        # → 0.7.3 latest
pip index versions pydantic      # → 2.13.4 latest
```

[VERIFIED: 2026-05-13 via pip index versions]

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pydantic for config | cerberus | Cerberus has dict-based schemas (less code than pydantic class), but requires new install (pydantic is already present). Cerberus also has [worse error formatting](https://docs.pydantic.dev/latest/errors/validation_errors/) for nested paths. Recommend pydantic. |
| pydantic for config | hand-rolled validation | Saves one import line but reinvents error formatting; pydantic gives free location pointers (`whisper_prompt: -> language: ` style paths). Use pydantic. |
| loguru | stdlib `logging` | stdlib needs handlers + formatters + rotating-file-handler manual wire-up. Loguru is one-line. Project already decided (STATE.md). |
| Mutable AppState dataclass + lock | `frozen=True` + `dataclasses.replace()` everywhere | Frozen would force every state mutation to `state = replace(state, recording=True)`. Existing code mutates inside `with _state_lock:` — keep that pattern. Frozen would require rewriting every callsite. **Save frozen for v2 if it becomes a concurrency problem.** [CITED: pyblog.in 2026 dataclass guide — "frozen by default unless you have a specific reason to mutate"] [ASSUMED: mutating in-place under existing lock is acceptable for this app's single-recording-at-a-time semantics] |
| Custom NSApplicationDelegate for shutdown | `signal.signal()` + cooperative shutdown | Subclassing `NSApplicationDelegate` is more macOS-native but requires Objective-C bridge boilerplate. signal+event is portable and matches existing style (signal is already imported at line 43). |

**Installation:**

```bash
pip install loguru
# pydantic already installed transitively
```

## Module Decomposition Plan

govori.py has clean ASCII-separated sections. Each maps to one module. **Mapping is canonical — no creativity required.** Line numbers below are from `grep -n` on current `govori.py` @ 3145 lines.

### Proposed `govori/` package structure

```
govori/
├── __init__.py        # package marker; re-export logger setup
├── __main__.py        # `python -m govori` entry; calls cli.main()
├── config.py          # paths, load_config, load_plugins, build_whisper_prompt, build_notes_config, _load_yaml*, _tokenize_prompt_terms, _notes_corpus_text
├── state.py           # AppState dataclass + _state_lock + transitions; PERMANENT_API_ERROR sentinel
├── logging_setup.py   # loguru configuration; called once at startup
├── hud.py             # setup_hud, set_hud, _show_*/_hide_* helpers, _route_mouse_to_hud, _hud_click_action, _retry_transcription, tooltip strings
├── audio.py           # audio_callback, _start_mic_stream, _show_recording_hud, _timeout_for_duration, _save_note_audio_background, stop_and_transcribe, cancel_recording
├── transcribe.py      # _encode_and_transcribe, _transcribe_with_auto_retries, _is_hallucination, WHISPER_HALLUCINATIONS, _FOREIGN_SCRIPT_RE, NEW: provider clients + fallback + PERF-01 spans
├── notes.py           # classify_note, save_or_merge_note, _save_note_with_meta, _decide_merge, _confirm_merge, _apply_merge_append, _find_merge_candidates, _read_index_entries, segment_by_context, _apply_self_corrections, _validate_meta, _sanitize_slug, _resolve_path
├── macos.py           # paste_text, _press_enter, _delete_chars, signal handling, NSApp lifecycle, _ensure_singleton, _find_other_govori_pids
├── predict.py         # generate_rephrasings, PredictController, setup_predict, show_predict_menu
├── hotkey.py          # cg_event_callback, install_monitor, _tap_health_check, FN_KEYCODE constants
├── onboarding.py      # cli_setup, SETUP_STRINGS, TOOLTIP_STRINGS, _tooltip, _ask
├── cli.py             # cli_main, cli_plugin, cli_add, cli_notes (picker + amend), main() entry point
└── notes_cli.py       # _curses_pick, _fzf_pick, _record_until_enter, _amend_via_haiku, _split_frontmatter, _update_frontmatter_amended
                       # (split out because notes CLI is ~350 lines and has no overlap with notes.py business logic except _read_index_entries)
```

### Line-by-line section map (current govori.py → target module)

| Lines | Section | Target Module |
|-------|---------|---------------|
| 1–45 | Imports + module docstring | top of `govori/cli.py` for CLI imports, distributed elsewhere as needed |
| 46–49 | `# ── Paths ──` | `config.py` |
| 51–280 | `# ── Config loading ──` (`_load_yaml`, `load_config`, `load_plugins`, `build_whisper_prompt`, `build_notes_config`) | `config.py` |
| 280–281 | `VALID_TYPES`, `VALID_URGENCY` constants | `notes.py` |
| 283–628 | `# ── Onboarding / Setup ──` (`SETUP_STRINGS`, `cli_setup`, `_ask`, `_tooltip`, `TOOLTIP_STRINGS`, `_is_first_run`) | `onboarding.py` (tooltip strings stay here, imported by `hud.py`) |
| 630–807 | `# ── CLI subcommands ──` (`cli_plugin`, `cli_add`) | `cli.py` |
| 809 | `VERSION` | `cli.py` or `__init__.py` |
| 812–858 | `cli_main()` | `cli.py` |
| 861–874 | `WHISPER_HALLUCINATIONS` | `transcribe.py` |
| 876–903 | OpenAI/Anthropic client construction (line 882) — **CRITICAL — see HTTP Pooling section**; `_get_anthropic_client` lazy init | `transcribe.py` (OpenAI) + `notes.py` (anthropic) |
| 905–924 | `# ── State ──` (11 globals + `PERMANENT_API_ERROR` sentinel + `_state_lock`) | `state.py` — replace with AppState |
| 934–1423 | `# ── HUD ──` (panels, countdown, tooltip, click routing, retry transcription, `set_hud`) | `hud.py` |
| 1425–1604 | `# ── Audio ──` + `# ── Note pipeline ──` parts | `audio.py` (stream, callback, stop, cancel) and `transcribe.py` (encode + retries + hallucination) |
| 1607–1678 | `_save_note_audio_background`, `_note_pipeline_background` | `notes.py` (delegates to `transcribe.py`) |
| 1681–1731 | `# ── SPIKE: self-corrections cleanup ──` | `notes.py` (used only after dictate paste in non-note mode — actually consumed in `audio.py:stop_and_transcribe`. Place in `notes.py` and import from there, OR keep in `transcribe.py`. Recommend `transcribe.py` since it's a post-processing step on transcribed text.) |
| 1733–1870 | `stop_and_transcribe`, `cancel_recording` | `audio.py` |
| 1872–1900 | `# ── Paste / Enter ──` | `macos.py` |
| 1902–2389 | `# ── Note mode ──` + `# ── Merge-check ──` | `notes.py` |
| 2391–2495 | `# ── Predict mode ──` | `predict.py` |
| 2497–2677 | `# ── Hotkey (fn) ──` + `_tap_health_check` | `hotkey.py` |
| 2680–3036 | `# ── Notes CLI ──` | `notes_cli.py` (called from `cli.py:cli_notes`) |
| 3038–3104 | `# ── Singleton enforcement ──` | `macos.py` |
| 3107–3145 | `# ── Main ──` | `__main__.py` (very thin: parse argv, call `cli.main()`) |

### Import graph (target — acyclic)

```
__main__.py
  └─→ cli.py
        ├─→ config.py
        ├─→ onboarding.py
        ├─→ notes.py (for note-text CLI path)
        ├─→ notes_cli.py
        ├─→ hud.py (for daemon startup setup_hud)
        ├─→ hotkey.py
        ├─→ audio.py
        ├─→ predict.py
        ├─→ macos.py
        ├─→ state.py
        └─→ logging_setup.py

audio.py
  ├─→ state.py
  ├─→ transcribe.py
  ├─→ hud.py
  ├─→ notes.py (for note pipeline)
  └─→ macos.py (for paste_text)

hud.py
  ├─→ state.py
  ├─→ onboarding.py (for tooltip strings) -- OR move TOOLTIP_STRINGS into hud.py itself
  └─→ transcribe.py (for retry — _retry_transcription lives here today)

hotkey.py
  ├─→ state.py
  ├─→ audio.py (stop_and_transcribe, cancel_recording)
  └─→ hud.py

transcribe.py
  ├─→ state.py (for AppState retry fields + lock)
  ├─→ config.py (for SAMPLE_RATE, LANGUAGE, MODEL, WHISPER_PROMPT)
  └─→ (NEW) provider clients module-internal

notes.py
  ├─→ config.py
  ├─→ state.py (NOTES_CFG access)
  └─→ transcribe.py (for _apply_self_corrections — OR keep that in transcribe.py)

predict.py
  ├─→ config.py
  ├─→ state.py
  └─→ macos.py (paste_text, _delete_chars)

state.py
  └─→ (no internal imports — leaf)

config.py
  └─→ (no internal imports — leaf)

logging_setup.py
  └─→ config.py (for CONFIG_DIR path)

macos.py
  └─→ state.py (for shutdown event)
```

### Cyclic dependency risks and mitigations

1. **`hud` ↔ `transcribe`:** `_retry_transcription` lives in HUD section today (line 1268) because it's triggered from the HUD click handler. **Mitigation:** move `_retry_transcription` to `transcribe.py`; `hud.py` calls it but doesn't define it. Click handler in `hud.py` does `threading.Thread(target=transcribe.retry, daemon=True).start()`.

2. **`audio` ↔ `notes`:** `stop_and_transcribe` calls `_note_pipeline_background` which calls back into transcription. **Mitigation:** `notes.py` imports from `transcribe.py` (one-way); `audio.py` imports from `notes.py` only at the dispatch point — fine because `notes` doesn't import `audio`.

3. **`hud` ↔ `audio`:** `cancel_recording` updates HUD; HUD click triggers retry which may need audio buffer. **Mitigation:** state lives in `state.py`. HUD reads state to know what mode it's in; audio reads state to know if cancelled. Neither imports the other directly — both import `state`.

4. **`hud` ↔ `state`:** Trivial — `hud.py` imports `state.py` (one-way). `state.py` exports a global `app_state` instance.

5. **Tooltip strings:** Currently in `onboarding.py` section (TOOLTIP_STRINGS at line 454). Used by `hud.py` via `_tooltip()` helper. **Mitigation:** move `TOOLTIP_STRINGS` and `_tooltip()` into `hud.py` itself, since onboarding doesn't use them. Onboarding keeps only `SETUP_STRINGS`.

6. **`audio` ↔ `hotkey`:** Hotkey callback calls `stop_and_transcribe` and `cancel_recording`. **Mitigation:** one-way: `hotkey` imports `audio`; `audio` does NOT import `hotkey`.

## AppState Design

### Current globals inventory (lines 905–924, 2392, 2501)

| Variable | Type | Mutated by | Read by | Current lock guard |
|----------|------|-----------|---------|-------------------|
| `recording` | bool | hotkey, audio, cancel | hotkey, audio, hud, callback | partial (`_state_lock`) |
| `transcribing` | bool | audio | hotkey, cancel | partial |
| `audio_chunks` | list[np.ndarray] | audio_callback (no lock!), audio, cancel | audio | NO (race per CONCERNS.md) |
| `audio_stream` | sd.InputStream\|None | audio, cancel | audio | yes |
| `auto_send` | bool | hotkey | audio | yes |
| `cancelled` | bool | hotkey, cancel | audio, hud | yes |
| `predict_mode` | bool | hotkey, cancel | audio, hud | yes |
| `note_mode` | bool | hotkey, cancel | audio | yes |
| `_retry_buffer` | list\|None | audio (after err), retry | retry handler | yes |
| `_retry_count` | int | hotkey (reset), retry | retry handler | yes |
| `_retry_in_progress` | bool | retry single-flight | retry handler | yes |
| `_retry_mode_snapshot` | dict\|None | audio (on err) | retry handler | yes |
| `_hud_error_mode` | str\|None | set_hud | _hud_apply_press | NO (UI-thread only by convention) |
| `_health_monitor_owns_hud` | bool | _tap_health_check | _tap_health_check | NO |
| `_fn_press_time` | float | hotkey | hotkey | NO (single thread) |
| `_shift_held`, `_option_held` | bool | hotkey | hotkey | NO (single thread) |
| `_predict_controller` | PredictController\|None | setup_predict | show_predict_menu | NO (set once at startup) |
| `_anthropic_client` | Anthropic\|None | lazy init | classify_note | NO (lazy, written once) |
| `prev_fn_down` | bool | hotkey | hotkey | NO (single thread) |
| `client` (OpenAI) | OpenAI | module init | _encode_and_transcribe | N/A (set once at startup) |

### Recommended AppState design

**Mutable dataclass + `threading.RLock`** (extends existing `_state_lock` pattern). Reasons:

1. Code currently mutates 11 globals under `_state_lock` — keeping the same pattern means a mechanical extraction, not a redesign.
2. Frozen-dataclass approach (`state = replace(state, recording=True)`) would force every callsite to be rewritten, AND every "I want to reassign the global" would need a `state` local rebind — error-prone in the existing thread model.
3. The state isn't being shared across processes; it's a single in-process daemon. Lock-protected mutation is the standard Python pattern for this scale.

```python
# state.py
from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Optional, Any
import numpy as np  # for type hint only

PERMANENT_API_ERROR = object()  # Sentinel — preserved from current code

@dataclass
class AppState:
    """Single source of truth for runtime state. Mutate only inside `with state.lock:`.

    Why not frozen=True: code currently relies on in-place updates from
    multiple threads under a shared lock. Switching to frozen would force
    `replace()` calls everywhere — high refactor cost for unclear win.

    Why RLock not Lock: cancel_recording → set_hud → may call back into
    state-touching code. RLock prevents self-deadlock on re-entrant paths.
    """
    # Active recording state
    recording: bool = False
    transcribing: bool = False
    audio_chunks: list = field(default_factory=list)
    audio_stream: Optional[Any] = None  # sd.InputStream

    # Mode flags set before recording starts
    auto_send: bool = False
    cancelled: bool = False
    predict_mode: bool = False
    note_mode: bool = False

    # Retry / error recovery
    retry_buffer: Optional[list] = None
    retry_count: int = 0
    retry_in_progress: bool = False
    retry_mode_snapshot: Optional[dict] = None

    # HUD state (UI-thread only, no lock needed but lives here for completeness)
    hud_error_mode: Optional[str] = None        # "error_retryable" | "error_fatal" | None
    health_monitor_owns_hud: bool = False

    # Hotkey monitor state (single-threaded — main runloop)
    fn_press_time: float = 0.0
    shift_held: bool = False
    option_held: bool = False
    prev_fn_down: bool = False

    # Shutdown coordination
    shutdown_requested: bool = False

    # Re-entrant lock to guard all the above
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

# Module-level singleton (only one daemon per process — singleton enforcement
# at process layer already exists, see _ensure_singleton).
state = AppState()
```

**Explicit transitions:** instead of scattered `state.recording = True; state.cancelled = False; ...`, define named transitions:

```python
def begin_recording(*, predict: bool, note: bool) -> bool:
    """Atomically transition to recording state. Returns False if already recording."""
    with state.lock:
        if state.recording:
            return False
        state.recording = True
        state.cancelled = False
        state.auto_send = False
        state.audio_chunks = []
        state.retry_count = 0
        state.predict_mode = predict
        state.note_mode = note
        return True

def request_cancel() -> None:
    with state.lock:
        state.cancelled = True
        state.recording = False
        state.transcribing = False
        state.predict_mode = False
        state.note_mode = False
        # audio_stream cleanup handled by caller (needs to be done outside lock
        # to avoid blocking other threads on PortAudio close)

def stash_retry_buffer(audio_chunks_copy: list, mode: dict) -> None:
    with state.lock:
        state.retry_buffer = audio_chunks_copy
        state.retry_count = 0
        state.retry_mode_snapshot = mode
```

**The `audio_chunks` race fix (CONCERNS.md bug):** `audio_callback` currently appends to `audio_chunks` without holding the lock (line 1428). Phase 2 should fix this opportunistically while extracting:

```python
def audio_callback(indata, frames, time_info, status):
    # Read recording flag under lock to avoid TOCTOU; append is fast.
    with state.lock:
        if state.recording:
            state.audio_chunks.append(indata.copy())
```

[ASSUMED: holding the lock inside the audio callback is acceptable. Risk: lock contention with stop_and_transcribe could drop a frame. Mitigation: the lock is held for <1µs per callback. Verify in practice — if it causes audio drops, fall back to a thread-safe deque without explicit locking.]

## Loguru Integration

### Print() inventory (must be replaced)

`grep -c 'print(' govori.py` → ~120 occurrences. Categories:

| Pattern | Example | Loguru replacement | Level |
|---------|---------|-------------------|-------|
| `print(f"● Recording…", flush=True)` | line 1474 | `logger.info("Recording", extra={"event": "rec_start"})` (and let console formatter render `●`) | INFO |
| `print(f"■ Transcribing…", flush=True)` | line 1792 | `logger.info("Transcribing")` | INFO |
| `print(f"→ {text}", flush=True)` | line 1677, 1835 | `logger.info(text, extra={"event": "transcript"})` | INFO |
| `print(f"✎ saved: {note_path.name}…")` | line 2157 | `logger.info(f"Note saved: {note_path.name}", extra={"event": "note_saved", "path": str(note_path)})` | INFO |
| `print(f"! Mic error: {e}", flush=True)` | line 1460 | `logger.error(f"Mic error: {e}")` | ERROR |
| `print("(empty)", flush=True)` | line 1675 | `logger.debug("Empty transcript")` | DEBUG |
| `print("(too short)", flush=True)` | line 1756 | `logger.debug("Too short, skipping")` | DEBUG |
| `print("(cancelled)", flush=True)` | line 1869 | `logger.debug("Cancelled")` | DEBUG |
| `print(f"[mode] shift=… → note=…", flush=True)` | line 2592 | `logger.debug("Mode set", extra={"shift": ..., "note": ..., "predict": ...})` | DEBUG |
| `print(f"[debug] chunks=…", flush=True)` | line 1753 | `logger.debug("Recording stats", extra={"chunks": ..., "duration_s": ...})` | DEBUG |
| `print(f"Classify error: {e}", flush=True)` | line 2090 | `logger.exception(f"Classify error: {e}")` | EXCEPTION |

### Console format that preserves Unicode symbol semantics

```python
# logging_setup.py
import sys
from loguru import logger
from .config import CONFIG_DIR

# Symbol prefix map — preserves the visual language users are accustomed to.
_LEVEL_TO_SYMBOL = {
    "DEBUG": " ",      # quiet
    "INFO": "●",       # default green-ish
    "SUCCESS": "✓",
    "WARNING": "⚠",
    "ERROR": "✗",
    "CRITICAL": "✗",
}

# Map "event" extras to override the symbol for narrative consistency
_EVENT_SYMBOLS = {
    "rec_start": "●",
    "rec_stop": "■",
    "transcript": "→",
    "note_saved": "✎",
    "merge": "⇪",
    "hallucination": "·",
}

def _format_console(record):
    event = record["extra"].get("event")
    symbol = _EVENT_SYMBOLS.get(event) or _LEVEL_TO_SYMBOL.get(record["level"].name, "·")
    return f"{symbol} {record['message']}\n"

def configure_logging(level: str = "INFO", bench_mode: bool = False):
    logger.remove()  # drop default stderr handler
    # Console handler — keeps the foreground "looks like ./govori is alive" feel
    logger.add(sys.stdout, level=level, format=_format_console, colorize=False)
    # File handler — durable, structured
    log_file = CONFIG_DIR / "govori.log"
    logger.add(
        str(log_file),
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        level="DEBUG",  # file gets everything, console gets less
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra} | {message}",
        encoding="utf-8",
        enqueue=True,  # non-blocking writes — important for low-latency dictation path
    )
    if bench_mode:
        # Extra structured JSON sink for parsing PERF-01 spans
        logger.add(
            str(CONFIG_DIR / "bench.jsonl"),
            rotation="50 MB",
            level="DEBUG",
            serialize=True,  # one JSON object per line
            filter=lambda rec: "stage" in rec["extra"],  # only spans
        )
```

[VERIFIED: Context7 /delgan/loguru — rotation/retention/compression/enqueue all valid 0.7.3 syntax]

### Rotation strategy decision

| Strategy | Pros | Cons | Choice |
|----------|------|------|--------|
| Size-based: `rotation="10 MB"` | Predictable disk usage; rotation happens when needed | Long-idle sessions never rotate | **Selected** — primary |
| Time-based: `rotation="00:00"` | Easy to reason about logs by day | Tiny logs for low-use days clutter directory | Not selected |
| Combined: `rotation=["10 MB", "00:00"]` | Both axes | Slight complexity | **Selected as fallback if users complain** |
| Retention: `retention="30 days"` | Caps lifetime of historical data | Loses old debugging context | Selected — 30 days is plenty for "did this happen last week?" |
| Compression: `compression="zip"` | ~10× smaller archives | None meaningful | Selected |

**Decision: 10 MB rotation, 30 days retention, zip compression.** Each transcription emits ~5 INFO lines + 5–15 DEBUG lines ≈ 1 KB. At 100 dictations/day = 100 KB/day → ~3 MB/month. 10 MB rotation gives ~3 months per file; retention=30 days means roughly 1 active file + 1 archive at any time. Plenty.

### `enqueue=True` for the dictation hot path

`enqueue=True` puts log writes on a background queue, returning instantly to the caller. **Critical for PERF-01 instrumentation** — synchronous file I/O on the transcription path would add 1–5ms per log call to the very latency we're measuring. [VERIFIED: Context7 loguru — "All sinks registered with the logger are thread-safe by default. For multiprocess safety, messages can be enqueued. This `enqueue` argument also enables asynchronous logging."]

### Migration approach for ~120 print() calls

Tackle by file section, not by print-call. For each module after extraction:

1. `from loguru import logger`
2. Replace `print("● Recording…", flush=True)` → `logger.info("Recording", extra={"event": "rec_start"})`
3. The console formatter restores the `●` prefix.
4. `print(f"Error: {e}", flush=True)` → `logger.error(f"Error: {e}")`
5. `print("(empty)", flush=True)` → `logger.debug("Empty transcript")`

**Don't try to preserve exact wording in every line.** The goal is the log content has equivalent information, not byte-identical output. Phase 2 prints become structured events; if a downstream consumer was grepping `→` lines, that's a v2 problem.

## Signal Handling on NSRunLoop

### Current state (line 3139)

```python
signal.signal(signal.SIGINT, lambda *_: os._exit(0))
run_loop = AppKit.NSRunLoop.mainRunLoop()
while True:
    run_loop.runMode_beforeDate_(
        AppKit.NSDefaultRunLoopMode,
        AppKit.NSDate.dateWithTimeIntervalSinceNow_(0.5),
    )
```

**This works only because `os._exit(0)` bypasses every cleanup hook in Python AND macOS.** SIGTERM is not handled. The 0.5s `runMode_beforeDate_` polling loop gives Python's signal handler a chance to run between iterations — which is the only reason SIGINT is observed at all. [VERIFIED: confirmed by code inspection]

### Recommended pattern

1. **Use a `threading.Event` for shutdown signaling** (or `state.shutdown_requested` flag).
2. **Signal handler is small** — just sets the event; does NO cleanup work (signal handlers in Python run on the main thread between bytecode instructions; doing I/O or acquiring locks risks deadlock).
3. **Main runloop polls the event** between `runMode_beforeDate_` iterations.
4. **When event is set:** stop audio stream, close OpenAI client, flush loguru queue, call `NSApp.terminate_(None)` (or just break the loop).

```python
# macos.py (or in __main__.py)
import signal
import threading
from loguru import logger
import AppKit
from . import state as state_mod

_shutdown_event = threading.Event()

def _request_shutdown(signum, frame):
    # Keep this tiny — signal handlers must be reentrant-safe.
    _shutdown_event.set()

def install_signal_handlers():
    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

def perform_shutdown():
    """Called from main loop after _shutdown_event is set. Single-threaded."""
    logger.info("Shutdown requested — cleaning up")
    with state_mod.state.lock:
        stream = state_mod.state.audio_stream
        state_mod.state.audio_stream = None
        state_mod.state.recording = False
    if stream is not None:
        try:
            stream.stop()
            stream.close()
        except Exception as e:
            logger.warning(f"Audio stream close failed: {e}")
    logger.complete()  # flush enqueued log writes — see loguru docs
    # Tell Cocoa to wind down
    AppKit.NSApp.terminate_(None)

# In __main__.py main loop:
def run_event_loop():
    run_loop = AppKit.NSRunLoop.mainRunLoop()
    while not _shutdown_event.is_set():
        run_loop.runMode_beforeDate_(
            AppKit.NSDefaultRunLoopMode,
            AppKit.NSDate.dateWithTimeIntervalSinceNow_(0.5),
        )
    perform_shutdown()
```

[CITED: prodisup.com Swift signal capture pattern — same shape, different language. The Python idiom is identical: signal handler is minimal, main loop checks flag.]

### Why NOT use NSApplicationDelegate's `applicationWillTerminate_`

- `applicationWillTerminate_` fires when Cocoa initiates shutdown (Cmd+Q, system logout). It does NOT fire on SIGINT/SIGTERM — Python signal handlers run BEFORE NSApp ever knows.
- Implementing a Delegate adds an Objective-C bridge class for one method. The signal-handler-plus-flag approach is one fewer abstraction.
- [ASSUMED: existing daemon has no Cmd+Q path because it runs as accessory (`NSApplicationActivationPolicyAccessory`) and has no UI to receive Cmd+Q. So `applicationWillTerminate_` would essentially never fire from user action — only from system shutdown — which is exactly when SIGTERM also fires. Signal handler covers both cases.]

### Race conditions to watch

1. **Signal fires during `_encode_and_transcribe` HTTP request:** the request is on a daemon thread; when main thread exits, daemon thread is killed mid-request. **Mitigation:** call `client.close()` in `perform_shutdown` to close the httpx pool, then daemon thread fails fast. Acceptable for a "user pressed Ctrl+C" path.
2. **Signal fires while audio callback is mid-append:** PortAudio's callback runs on a real-time thread; on `stream.stop()` it gets joined cleanly. Existing code handles this.
3. **Loguru queue not yet flushed:** `logger.complete()` blocks until the enqueue queue drains. Call it before `NSApp.terminate_`.

## Config Validation

### Current broken behavior (line 52–63)

```python
def _load_yaml(path):
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if yaml:
        return yaml.safe_load(text) or {}
    try:
        return json.loads(text)  # fallback if pyyaml missing
    except Exception:
        return {}  # SILENTLY RETURNS {} ON YAML ERROR
```

Per CONCERNS.md: "If pyyaml is not installed, `_load_yaml()` falls back to `json.loads()`. A valid YAML config (which is not valid JSON) will silently return `{}`, causing all settings to revert to defaults with no error." Same happens if YAML is malformed — `yaml.safe_load` raises, `_load_yaml` catches and returns `{}`.

### Recommended pydantic-based replacement

```python
# config.py
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field, field_validator, ValidationError

class GovoriConfig(BaseModel):
    language: str = Field(default="ru", pattern=r"^(en|ru)$")
    model: str = Field(default="whisper-1")
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    whisper_prompt: str = Field(default="")
    base_url: Optional[str] = Field(default=None)
    api_key_env: str = Field(default="OPENAI_API_KEY")
    predict_model: str = Field(default="llama-3.3-70b-versatile")

    @field_validator("base_url")
    @classmethod
    def base_url_must_be_http(cls, v):
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v

def load_config(path: Path = CONFIG_FILE) -> GovoriConfig:
    if not path.exists():
        return GovoriConfig()  # defaults
    text = path.read_text(encoding="utf-8")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SystemExit(
            f"\n✗ Invalid YAML in {path}:\n  {e}\n\n"
            f"  Check syntax (indentation, quotes, colons). Run `govori setup` "
            f"to regenerate the config from scratch.\n"
        )
    if raw is None:
        return GovoriConfig()  # empty file
    if not isinstance(raw, dict):
        raise SystemExit(
            f"\n✗ Config in {path} must be a YAML mapping (key: value pairs), "
            f"got {type(raw).__name__}.\n"
        )
    try:
        return GovoriConfig(**raw)
    except ValidationError as e:
        # Pydantic v2 formats errors with field paths and human descriptions
        lines = ["", f"✗ Invalid config in {path}:"]
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            lines.append(f"  {loc}: {err['msg']}")
        lines.append("")
        raise SystemExit("\n".join(lines))
```

**Output example for an invalid config:**

```
✗ Invalid config in /Users/genlorem/.config/govori/config.yaml:
  sample_rate: Input should be greater than or equal to 8000
  base_url: Value error, base_url must start with http:// or https://
```

[VERIFIED: pydantic v2 ValidationError.errors() output format from docs.pydantic.dev/2.13]

### Pydantic vs cerberus rationale

| Criterion | pydantic 2.13 | cerberus |
|-----------|--------------|----------|
| Already installed in venv | ✓ (transitive via openai/anthropic) | ✗ (would add new dep) |
| Error message quality (field path) | Excellent — nested loc paths | Good — flat dict by field |
| Type hints in schema | Native (class-based) | Dict-based (less IDE help) |
| Modification cost when adding fields | Add line to dataclass | Edit dict |
| Speed | Fast (Rust core) | Slower (pure Python) but irrelevant at config-load size |

**Decision: pydantic.** Zero new deps + better error formatting wins. [CITED: medium.com 2026 pydantic guide; pydantic docs]

### Plugin YAML validation (notes plugin)

The notes plugin loads `plugin.yaml`, `contexts.yaml`, `stuck.yaml` (line 90–116). These are also vulnerable. Recommendation: add a `PluginManifest` pydantic model and a `NotesPluginConfig` model, validate at `load_plugins()` time. Out-of-scope ideas like "what if plugins should be hot-reloadable" are deferred. Keep scope tight: validate the same files currently loaded; error out loudly on bad data.

## PERF-01 Instrumentation

### Stages to instrument

Per success criterion: `stop_and_transcribe → encode → API → paste`.

Concretely, in current code:

| Stage name | What it measures | Where to wrap |
|------------|------------------|---------------|
| `fn_release_to_stop` | Time from fn-up event to start of `stop_and_transcribe` | hotkey callback to start of audio.stop_and_transcribe |
| `stop_total` | Whole `stop_and_transcribe` | wrap call |
| `audio_concat` | `np.concatenate(chunks_snapshot, axis=0).flatten()` (line 1759) | small span inside stop_and_transcribe |
| `encode` | PyAV OGG/Opus encode inside `_encode_and_transcribe` (lines 1497–1508) | span around the encode loop |
| `api_call` | `client.audio.transcriptions.create(...)` (line 1512) | span around just the API call |
| `hallucination_filter` | `_apply_self_corrections` Haiku pass (line 1837) | optional, often short |
| `paste` | `paste_text(text + " ")` and Cmd+V (lines 1873–1890) | span around paste_text |
| `end_to_end` | fn-release to paste-complete | outermost span |

### Span helper pattern

```python
# transcribe.py or a new instrument.py
import os
import time
from contextlib import contextmanager
from collections import defaultdict
from loguru import logger
import atexit

BENCH_MODE = os.environ.get("BENCH_MODE") == "1"

# Aggregator — keyed by stage name, list of milliseconds
_bench_samples: dict[str, list[float]] = defaultdict(list)

@contextmanager
def span(name: str, **extra):
    """Time a code block. Emits a structured loguru event and (if BENCH_MODE)
    accumulates samples for end-of-run summary."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.bind(stage=name, elapsed_ms=round(elapsed_ms, 2), **extra).debug(
            f"span {name} {elapsed_ms:.1f}ms"
        )
        if BENCH_MODE:
            _bench_samples[name].append(elapsed_ms)

def _print_bench_summary():
    if not BENCH_MODE or not _bench_samples:
        return
    print("\n── PERF-01 summary ─────────────────────────────────")
    print(f"{'stage':<25} {'n':>4} {'p50':>8} {'p95':>8} {'mean':>8}")
    for stage, samples in sorted(_bench_samples.items()):
        s = sorted(samples)
        n = len(s)
        p50 = s[n // 2]
        p95 = s[int(n * 0.95)] if n >= 20 else s[-1]
        mean = sum(s) / n
        print(f"{stage:<25} {n:>4} {p50:>7.1f}ms {p95:>7.1f}ms {mean:>7.1f}ms")

atexit.register(_print_bench_summary)
```

**Usage:**

```python
# audio.py
def stop_and_transcribe():
    with span("stop_total"):
        # ... existing logic ...
        with span("audio_concat"):
            audio = np.concatenate(chunks_snapshot, axis=0).flatten()
        # ...
        with span("transcribe_full"):
            text = _transcribe_with_auto_retries(audio, duration, on_progress=_show_progress)
        # ...
        with span("paste"):
            paste_text(text + " ")
```

```python
# transcribe.py
def _encode_and_transcribe(audio, timeout=30.0):
    # ... peak normalization ...
    with span("encode"):
        # ... PyAV encode loop ...
    with span("api_call", provider=current_provider, model=MODEL):
        result = client.audio.transcriptions.create(...)
```

### Watch-out: `_transcribe_with_auto_retries` thread spawn

Existing code at line 1558 spawns a worker thread per attempt to enable timeout-with-cancel semantics:

```python
worker = threading.Thread(target=_do, daemon=True)
worker.start()
sec_left_in_attempt = int(timeout)
while not result["done"] and sec_left_in_attempt > 0:
    time.sleep(1)
    sec_left_in_attempt -= 1
worker.join(timeout=timeout + 2)
```

This means PERF-01 must measure the **wall-clock** time of the retry-wrapping function, not just the `_encode_and_transcribe` call inside the thread. Wrap the outer call site with `span("transcribe_full")` and put `span("api_call")` _inside_ `_encode_and_transcribe`. The difference between them = thread overhead + retry budget.

### BENCH_MODE summary mechanism

- `BENCH_MODE=1 ./govori` enables sample aggregation
- `atexit.register(_print_bench_summary)` runs on clean exit (works with SIGINT after Phase 2's graceful shutdown landing)
- Summary lists p50/p95/mean per stage across the session

Alternative: a `--bench-mode` CLI flag. **Recommendation: env var** — matches the precedent in `bench/latency_bench.py` which uses `BENCH_ITER=2`. Env var is also easier to set in a wrapper script for daily measurement.

### ContextVar consideration

For nested spans (e.g., `stop_total` containing `encode` containing `api_call`), a `ContextVar` could thread parent-span context through to enable hierarchical reporting. **Recommend NOT using ContextVar for Phase 2.** The flat structure is sufficient to answer "where does the 1.5s go" — adding parent/child tracking is premature complexity. If Phase 4 needs flame-graph-style data, revisit then.

## REL-05 Fallback Strategy (Groq → OpenAI)

### Current state

govori.py line 882 instantiates **one** OpenAI client pointed at Groq via `base_url`:

```python
client = (
    OpenAI(api_key=_api_key, base_url=_base_url, timeout=30.0, max_retries=0)
    if _base_url
    else OpenAI(api_key=_api_key, timeout=30.0, max_retries=0)
)
```

`_base_url` comes from config; user has set it to `https://api.groq.com/openai/v1`. `_api_key` is GROQ_API_KEY (via `api_key_env: GROQ_API_KEY` in config.yaml — same key the bench script uses). [VERIFIED: bench/latency_bench.py loads GROQ_API_KEY from `~/.config/govori/env` same way]

### Recommended architecture

```python
# transcribe.py
from dataclasses import dataclass
from typing import Optional
import os
from openai import OpenAI

@dataclass(frozen=True)
class Provider:
    name: str             # "groq" | "openai"
    api_key_env: str
    base_url: Optional[str]
    model: str

PROVIDER_GROQ = Provider(
    name="groq",
    api_key_env="GROQ_API_KEY",   # or whatever CONFIG.api_key_env says
    base_url="https://api.groq.com/openai/v1",
    model="whisper-large-v3-turbo",
)
PROVIDER_OPENAI = Provider(
    name="openai",
    api_key_env="OPENAI_API_KEY",
    base_url=None,                # default openai.com
    model="whisper-1",
)

# Module-level singletons — see HTTP Pooling section
_clients: dict[str, OpenAI] = {}

def _get_client(p: Provider) -> Optional[OpenAI]:
    if p.name in _clients:
        return _clients[p.name]
    api_key = os.environ.get(p.api_key_env)
    if not api_key:
        return None
    # NOTE: passing http_client explicitly to get a known-good connection pool;
    # see HTTP Pooling section for the DefaultHttpxClient construction.
    _clients[p.name] = OpenAI(
        api_key=api_key,
        base_url=p.base_url,
        timeout=30.0,
        max_retries=0,
        http_client=_build_http_client(),
    )
    return _clients[p.name]
```

### Fallback dispatcher

```python
# transcribe.py
def transcribe_with_fallback(audio, duration_sec, *, on_progress=None):
    """
    Try primary provider (Groq) with full retry budget. On final failure
    that's not PERMANENT_API_ERROR, try OpenAI once if available.
    Returns text, None (caller may show retryable HUD), or PERMANENT_API_ERROR.
    """
    primary = PROVIDER_GROQ
    fallback = PROVIDER_OPENAI

    primary_client = _get_client(primary)
    if primary_client is None:
        # Misconfigured — fail loud
        logger.error(f"Primary provider {primary.name} not configured")
        return None

    with span("provider_primary", provider=primary.name):
        text = _try_transcribe(primary, primary_client, audio, duration_sec,
                                on_progress=on_progress, max_retries=2)

    if text is PERMANENT_API_ERROR:
        logger.warning(f"Primary {primary.name}: permanent error — no fallback")
        return PERMANENT_API_ERROR
    if text is not None:
        logger.bind(provider=primary.name).info("Transcribed via primary")
        return text

    # Primary returned None — transient failure. Try fallback.
    fallback_client = _get_client(fallback)
    if fallback_client is None:
        logger.info(f"Fallback {fallback.name} not configured — giving up")
        return None
    logger.warning(f"Primary {primary.name} failed — falling back to {fallback.name}")
    with span("provider_fallback", provider=fallback.name):
        text = _try_transcribe(fallback, fallback_client, audio, duration_sec,
                               on_progress=on_progress, max_retries=1)
    if text and text is not PERMANENT_API_ERROR:
        logger.bind(provider=fallback.name).info("Transcribed via fallback")
    return text
```

### Wrapping vs interleaving retries

**Two valid designs:**

**A. Wrap (recommended):** primary gets its full 1 + 2 = 3 attempts; fallback gets 1 attempt. Total worst-case latency: 4 attempts × ~30s timeout = 2 minutes. But each attempt typically completes in <1s on success.

**B. Interleave:** alternate primary/fallback per retry. Faster recovery if primary is genuinely down but adds per-attempt complexity. Harder to log "which provider answered."

**Recommend A** — simpler to log and reason about. The 5% Groq drop rate measured in Spike 001 means fallback is rare; minimizing fallback latency isn't worth the architectural cost. [ASSUMED: 5% drop rate observed in spike (1/40 iteration) generalizes — could be specific to that day's Groq capacity]

### What "5xx / timeout / connection error" maps to in openai SDK

| openai exception | HTTP analogue | Action |
|------------------|---------------|--------|
| `openai.APITimeoutError` | timeout (no response) | retry → fall back |
| `openai.APIConnectionError` | DNS / TCP / TLS handshake failure | retry → fall back |
| `openai.APIStatusError` with `status_code >= 500` | 5xx | retry → fall back |
| `openai.APIStatusError` with `status_code == 429` | rate limit | retry (with backoff) → fall back |
| `openai.APIStatusError` with `status_code == 408` | server-side timeout | retry → fall back |
| `openai.APIStatusError` with other 4xx | bad request / auth / not found | PERMANENT — do NOT fall back |

Current `_encode_and_transcribe` (line 1520–1533) already classifies correctly. Reuse that logic. [VERIFIED: lines 1520–1533 of govori.py + Groq error doc]

### Logging which provider answered

```python
logger.bind(provider="groq", status="success").info("Transcribed")
# In log: {extra: {provider: "groq", status: "success"}}
# In console: ● Transcribed
```

User-visible disclosure (success criterion 7): "log shows which provider answered." The structured `extra={"provider": ...}` field in loguru's serialized output plus the console message satisfies this. Optionally, add the provider to the user-facing INFO line: `logger.info(f"→ {text}  [{provider}]")` — but this clutters normal output. Recommend: provider in log file always, in console only on fallback (`logger.warning(f"Fell back to {fallback.name}")`).

## HTTP Connection Pooling

### Problem statement (per success criterion 8)

Current code instantiates `OpenAI()` **once** at module import (line 882). The OpenAI SDK 2.32 uses httpx under the hood. Whether keep-alive actually works depends on:

1. Whether httpx's default `Limits(max_connections=1000, max_keepalive_connections=100)` permits keep-alive (yes by default per [httpx docs](https://www.python-httpx.org/advanced/resource-limits/))
2. Whether the same `OpenAI` client is reused across calls (yes — module-level singleton)
3. Whether httpx's connection pool actually holds the TCP/TLS connection idle between calls (yes, default keepalive timeout is ~5 seconds)

[VERIFIED: openai-python README via Context7 — `DefaultHttpxClient` is the public API for tuning pool limits]

### Recommended: explicit `DefaultHttpxClient` per provider

```python
# transcribe.py
import httpx
from openai import OpenAI, DefaultHttpxClient

def _build_http_client() -> DefaultHttpxClient:
    # Defaults are: max_connections=1000, max_keepalive_connections=100,
    # keepalive_expiry=5.0s. For a single-user dictation daemon, 1 connection
    # is enough — but the OpenAI SDK's defaults are fine and reduce surprise.
    # The CRITICAL thing is that this client is reused across all transcriptions.
    return DefaultHttpxClient(
        # Override timeout to match SEC-03 (30s for read, faster for connect)
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        limits=httpx.Limits(
            max_connections=10,
            max_keepalive_connections=5,  # plenty for a single user
            keepalive_expiry=30.0,        # hold connections idle longer
        ),
    )
```

**Why `keepalive_expiry=30.0` instead of default 5.0:** typical dictation interval is 2–60 seconds. Default 5s expiry means the second dictation may need a fresh TLS handshake (~200–500ms cost). Bumping to 30s captures most rapid-fire usage. Trade-off: server may have already closed the connection — httpx handles this gracefully (retries on a new connection). [VERIFIED: httpx Limits documentation]

### Verifying that pooling works

A round-trip diagnostic: log httpx connection state via a custom transport, or simpler — measure the `api_call` span across consecutive dictations. If the first dictation shows `api_call=600ms` and subsequent show `api_call=400ms`, the 200ms delta is TLS handshake amortized away. This is one of the things PERF-01 is designed to detect.

### Lifecycle: when to close

The clients should be closed on shutdown. Add to `perform_shutdown`:

```python
def perform_shutdown():
    # ... existing cleanup ...
    for client in _clients.values():
        try:
            client.close()
        except Exception:
            pass
```

Python garbage collection will eventually close httpx connections per [OpenAI SDK docs](https://github.com/openai/openai-python) ("HTTP connections are closed whenever the client is garbage collected") but explicit close is cleaner.

## Architecture Patterns

### Pattern 1: Module-level singletons via lazy init

**What:** Heavy resources (OpenAI clients, HTTP pools, Anthropic client) initialized once on first use; never re-created.
**When to use:** any expensive object that the same process uses repeatedly.
**Example:**

```python
# transcribe.py
_clients: dict[str, OpenAI] = {}

def _get_client(provider: Provider) -> Optional[OpenAI]:
    if provider.name in _clients:
        return _clients[provider.name]
    # ... construct and cache ...
```

[VERIFIED: govori.py already uses this for `_anthropic_client` at line 891]

### Pattern 2: span-based timing via contextmanager

**What:** `@contextmanager` that captures perf_counter delta around a block of code.
**When to use:** any latency-critical path that benefits from per-stage instrumentation.

```python
@contextmanager
def span(name, **extra):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        logger.bind(stage=name, elapsed_ms=(time.perf_counter() - t0) * 1000, **extra).debug(...)
```

[CITED: realpython.com timer functions; bugs.python.org issue 19495 — context manager for code blocks]

### Pattern 3: state-machine transitions as named functions

**What:** Don't mutate state fields directly from callers; expose `begin_recording()`, `request_cancel()`, etc., that own the transition logic.
**When to use:** any state with multiple legal transitions and multi-threaded mutators.

```python
# state.py
def begin_recording(*, predict, note) -> bool:
    with state.lock:
        if state.recording:
            return False
        # ... atomically set all fields ...
        return True
```

### Pattern 4: signal-flag pattern for graceful shutdown

**What:** Signal handler does the minimum (set an event); main loop polls the event.
**When to use:** any long-running daemon with cleanup to do.

[CITED: johal.in signal handling guide; runebook.dev signal.SIGTERM]

### Anti-patterns to avoid

- **Wide module-level side effects.** Current govori.py runs CLI dispatch at import time (`cli_main()` is called at line 858 BEFORE `__main__`). This makes tests impossible. **Fix:** `cli.py` exports `main()`; `__main__.py` does only `from .cli import main; main()`. Side effects move INSIDE `main()`.
- **Mutating multiple globals without atomicity.** Audio callback mutating `audio_chunks` outside `_state_lock` (line 1428) is a documented race. **Fix:** lock the read of `state.recording` along with the append.
- **`os._exit(0)` for shutdown.** Bypasses finally clauses, atexit hooks, daemon-thread joins, log flushes. **Fix:** cooperative shutdown via event flag + main-loop polling.
- **Swallowing config errors with `{}`.** Silent failure → user has no idea why their `language: en` setting was ignored. **Fix:** pydantic validation with `SystemExit` on error.
- **Single HTTP client whose pool we don't trust.** Either configure `http_client` explicitly or document _which_ httpx default version's pool you're relying on. **Fix:** explicit `DefaultHttpxClient` with named limits.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML config validation | Custom schema checker | pydantic v2 `BaseModel` | Free path-aware error messages; already installed |
| Log rotation | Custom file-size-watcher thread | loguru `rotation="10 MB"` | Battle-tested; thread-safe; compression built-in |
| Async-safe logging | Manual queue + worker thread | loguru `enqueue=True` | One parameter; correct out of the box |
| Connection pooling | Custom session manager | `httpx.Client` via `DefaultHttpxClient` | OpenAI SDK is built around it; just configure limits |
| Timing spans | `t0 = time.time(); ... print(time.time()-t0)` everywhere | `@contextmanager span()` + loguru `bind()` | Composable; structured output; works with serialization |
| Signal handler that does cleanup | Calling `audio_stream.stop()` from inside the signal handler | Event flag + main-loop polling | Signal handlers run between bytecodes; doing I/O risks deadlock |
| AppState as 11 globals | Continue with globals + add 4th lock | Single dataclass + `RLock` | Single import path for state; testable |
| Provider fallback | New retry library | Wrap existing `_transcribe_with_auto_retries` | Existing retry logic handles per-provider; only add provider switch |

**Key insight:** Every item in this table has a stable, well-tested library. The temptation to hand-roll comes from "I just need a small one of these" — but small custom solutions accumulate edge cases (rotation across midnight, log queue draining on exit, httpx pool exhaustion). All of these libraries have been hardened by other projects' bug reports.

## Runtime State Inventory

Phase 2 is a rename/refactor — extracting govori.py to a package. Inventory of state that needs migration handling:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — Govori doesn't have a database. Notes are markdown files keyed by filename, not by code path. | No migration needed. |
| Live service config | None — no remote services Govori owns. OpenAI/Anthropic/Groq are stateless clients. | No action. |
| OS-registered state | None found — Govori is not registered with launchd/Task Scheduler (verified by reading repo). User runs `./govori` from terminal manually. | No action — but **document for users**: the `govori` shell script wrapper invokes `.venv/bin/python govori.py`. After Phase 2 this needs updating to `.venv/bin/python -m govori` OR `.venv/bin/govori` (Phase 3 console_scripts). The wrapper script at `/Users/genlorem/Projects/govori/govori` (5 lines) MUST be updated. |
| Secrets/env vars | `~/.config/govori/env` (chmod 600) exports `OPENAI_API_KEY`, `GROQ_API_KEY`, `ANTHROPIC_API_KEY`. These env-var **names** are referenced in code by string at line 877, 898, 3xx (cli_setup). | After phase: `GROQ_API_KEY` is still read via `CONFIG.api_key_env` indirection — no rename. `OPENAI_API_KEY` becomes referenced by the new fallback path. Existing users' `~/.config/govori/env` continues to work unchanged. |
| Build artifacts | `__pycache__/` exists at project root with `.pyc` files for `govori.py`. After package extraction, these become stale. | Delete `__pycache__/` after extraction (one-time). New `govori/__pycache__/` will be created on first run. Add to `.gitignore` (already covered by `.gitignore` line — verified). |
| Singleton enforcement | `_ensure_singleton()` uses `pgrep -f govori.py` (line 3044). After extraction, the daemon process command line will be `python -m govori` instead of `python govori.py`. | **Update `_find_other_govori_pids()` to grep for both patterns** during the transition window: `pgrep -f "govori\.py|-m govori"`. Document for users that they should restart their session once after upgrading. |
| Config file format | `~/.config/govori/config.yaml` schema stays the same. New pydantic model validates same fields. | No migration. Existing configs work; previously-silently-ignored bad values will now show validation errors — desired behavior. |

**Critically important — only one rename hazard:** the singleton-detection pgrep pattern. Everything else is internal code reorganization with stable external interfaces (config paths, env var names, note file format, plugin discovery directory all unchanged).

## Common Pitfalls

### Pitfall 1: Print() lines that conditionally vary tone (Russian vs English)
**What goes wrong:** Some print calls render localized strings (`SETUP_STRINGS["ru"]["done"]` etc., line 357–449). Naive replacement with `logger.info(...)` will lose ANSI escape codes that the strings rely on for terminal formatting.
**Why it happens:** Onboarding strings contain `\033[36m` etc. — loguru's formatter strips these by default in non-colorize mode.
**How to avoid:** Keep onboarding output as direct `print()` for the onboarding wizard — it's a TTY-only one-shot, not a daemon-life log line. Document this as a deliberate exception. The log file shouldn't have ANSI escapes anyway.
**Warning signs:** User reports `\033[36m` literals showing up in their log file.

### Pitfall 2: PortAudio close blocking the shutdown path
**What goes wrong:** `audio_stream.close()` can take up to 500ms while PortAudio joins its real-time thread. If called inside the `state.lock`, other waiters block.
**Why it happens:** sounddevice/PortAudio JIT-spins down its internal worker threads.
**How to avoid:** Snapshot `state.audio_stream` under the lock, then release the lock, then call `stop()/close()` outside.
```python
with state.lock:
    stream = state.audio_stream
    state.audio_stream = None
if stream is not None:
    stream.stop(); stream.close()
```
**Warning signs:** Ctrl+C "hangs" for ~half a second before exit.

### Pitfall 3: httpx pool exhaustion under retry storms
**What goes wrong:** If the user holds fn → release → holds fn rapidly, multiple `_transcribe_with_auto_retries` threads can run in parallel. Each consumes a connection from the httpx pool. If the pool is sized to 1, the second one blocks waiting for a connection. If sized too high, server-side connection limits hit.
**Why it happens:** Govori is theoretically single-user single-recording, but retry threads can outlive the user's next press.
**How to avoid:** Set `max_connections=10, max_keepalive_connections=5` — wide enough that single-user worst case can't exhaust. Use `pool=5.0` timeout so a wait surfaces as `httpx.PoolTimeout` (which the existing exception handler will treat as transient retry).
**Warning signs:** `httpx.PoolTimeout` in logs after rapid back-to-back dictations. [VERIFIED: openai-python issue #2539]

### Pitfall 4: pydantic ValidationError leaking internal types
**What goes wrong:** `print(e)` on a pydantic `ValidationError` produces JSON-ish output with `[{'type': 'string_type', 'loc': ('language',), ...}]`. Ugly.
**Why it happens:** Default `__str__` is informational, not user-facing.
**How to avoid:** Always iterate `e.errors()` and format manually (see Config Validation code above). Don't `raise SystemExit(e)`; do `raise SystemExit(formatted)`.
**Warning signs:** User pastes error message that contains `'type': 'value_error',` — that's the raw dict.

### Pitfall 5: loguru `logger.info` doesn't appear because handler was never added
**What goes wrong:** During `logger.remove()` then `logger.add(...)`, if the call fails (bad path, permission denied on log dir), `logger.add` raises, and you've removed the default handler. Now no logs go anywhere.
**Why it happens:** `~/.config/govori/` may not exist on first run before `cli_setup` creates it.
**How to avoid:** Call `CONFIG_DIR.mkdir(parents=True, exist_ok=True)` before `logger.add(log_file)`. Wrap the add in `try/except` and fall back to stderr-only on failure.
**Warning signs:** Govori starts, prints nothing, hangs. Easy to debug — `logger.add(sys.stderr)` as the first sink, then the file.

### Pitfall 6: Module-level imports running CLI dispatch
**What goes wrong:** Tests that import `govori.cli` would trigger `cli_main()` running at import time (current behavior — line 858 calls `cli_main()` outside any guard). Same for the `print("Govori ready.")` at line 927.
**Why it happens:** Original single-file design assumed no library use.
**How to avoid:** Move everything that has side effects into `def main():` and call it only from `__main__.py`. Module imports must be side-effect-free.
**Warning signs:** Importing any submodule prints "Govori ready." or "Hotkey monitor installed." to stdout.

### Pitfall 7: Daemon threads + SIGINT racing
**What goes wrong:** Signal handler sets shutdown event. Main loop exits. Audio stream closing triggers OpenAI request cancellation. A daemon thread was mid-transcription. Python interpreter starts to exit. Daemon thread tries to use logger.complete()... but logger's worker thread has already been joined.
**Why it happens:** Daemon threads aren't joined on interpreter exit by default — they get killed.
**How to avoid:** Call `logger.complete()` BEFORE setting shutdown flag for daemon threads. Or accept that mid-transcription work on shutdown is dropped (acceptable for user pressing Ctrl+C).
**Warning signs:** Truncated log files; warnings about "still running threads."

### Pitfall 8: prev_fn_down / _shift_held living in hotkey.py but mutated from cg_event_callback
**What goes wrong:** These globals are single-threaded (only the CFRunLoop main thread modifies them), but if they end up as `state.prev_fn_down` etc., a future code path could lock around them — pessimization without benefit.
**Why it happens:** "Move everything to state.py" enthusiasm.
**How to avoid:** Keep `prev_fn_down`, `_shift_held`, `_option_held` as module-level in `hotkey.py`. They are private to the event-callback path and never read elsewhere. Don't put them in AppState.
**Warning signs:** Adding `with state.lock:` around every flag mutation in cg_event_callback — that's an over-correction. The flag MUTATION is single-thread; the EFFECT (calling stop_and_transcribe) crosses threads, and that crossing is what uses the lock.

## Code Examples

### Loguru file + console setup

```python
# govori/logging_setup.py
# Source: Context7 /delgan/loguru — verified rotation/retention/enqueue
import sys
from pathlib import Path
from loguru import logger

def configure_logging(log_dir: Path, bench_mode: bool = False) -> None:
    logger.remove()
    log_dir.mkdir(parents=True, exist_ok=True)
    # Console sink — preserves "looks like print" feel
    logger.add(sys.stdout, level="INFO", format="{message}", colorize=False)
    # File sink — durable, structured, async
    logger.add(
        log_dir / "govori.log",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra} | {message}",
        enqueue=True,
        encoding="utf-8",
    )
    if bench_mode:
        logger.add(
            log_dir / "bench.jsonl",
            rotation="50 MB",
            level="DEBUG",
            serialize=True,
            filter=lambda r: "stage" in r["extra"],
        )
```

### OpenAI client with explicit httpx pool

```python
# govori/transcribe.py
# Source: github.com/openai/openai-python README via Context7
import httpx
from openai import OpenAI, DefaultHttpxClient

def _build_http_client() -> DefaultHttpxClient:
    return DefaultHttpxClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        limits=httpx.Limits(
            max_connections=10,
            max_keepalive_connections=5,
            keepalive_expiry=30.0,
        ),
    )

def _new_client(provider: Provider, api_key: str) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url=provider.base_url,
        timeout=30.0,
        max_retries=0,
        http_client=_build_http_client(),
    )
```

### Pydantic config validation

```python
# govori/config.py
# Source: docs.pydantic.dev v2.13 ValidationError handling
import sys
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

class GovoriConfig(BaseModel):
    language: str = Field(default="ru", pattern=r"^(en|ru)$")
    model: str = Field(default="whisper-large-v3-turbo")
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    whisper_prompt: str = Field(default="")
    base_url: Optional[str] = Field(default=None)
    api_key_env: str = Field(default="GROQ_API_KEY")
    predict_model: str = Field(default="llama-3.3-70b-versatile")

    @field_validator("base_url")
    @classmethod
    def _check_url(cls, v):
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return v

def load_config(path: Path) -> GovoriConfig:
    if not path.exists():
        return GovoriConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        sys.exit(f"\n✗ Invalid YAML in {path}:\n  {e}\n")
    if raw is None:
        return GovoriConfig()
    if not isinstance(raw, dict):
        sys.exit(f"\n✗ Config in {path} must be a mapping\n")
    try:
        return GovoriConfig(**raw)
    except ValidationError as e:
        lines = [f"\n✗ Invalid config in {path}:"]
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            lines.append(f"  {loc}: {err['msg']}")
        sys.exit("\n".join(lines))
```

### Signal-handled graceful shutdown

```python
# govori/__main__.py
# Source: johal.in signal handling; verified pattern
import signal
import threading
import AppKit
from loguru import logger
from .cli import main_setup
from . import state as state_mod

_shutdown = threading.Event()

def _on_signal(signum, frame):
    _shutdown.set()

def main():
    main_setup()
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    run_loop = AppKit.NSRunLoop.mainRunLoop()
    while not _shutdown.is_set():
        run_loop.runMode_beforeDate_(
            AppKit.NSDefaultRunLoopMode,
            AppKit.NSDate.dateWithTimeIntervalSinceNow_(0.5),
        )
    _shutdown_cleanup()
    AppKit.NSApp.terminate_(None)

def _shutdown_cleanup():
    logger.info("Shutdown — cleaning up")
    with state_mod.state.lock:
        stream = state_mod.state.audio_stream
        state_mod.state.audio_stream = None
        state_mod.state.recording = False
    if stream:
        try:
            stream.stop(); stream.close()
        except Exception as e:
            logger.warning(f"Audio close failed: {e}")
    logger.complete()  # flush async queue

if __name__ == "__main__":
    main()
```

### PERF-01 span helper

```python
# govori/instrument.py
# Source: realpython.com/python-timer + bugs.python.org issue 19495
import os
import time
import atexit
from contextlib import contextmanager
from collections import defaultdict
from loguru import logger

BENCH_MODE = os.environ.get("BENCH_MODE") == "1"
_samples: dict[str, list[float]] = defaultdict(list)

@contextmanager
def span(name: str, **extra):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - t0) * 1000
        logger.bind(stage=name, elapsed_ms=round(ms, 2), **extra).debug(f"span {name}")
        if BENCH_MODE:
            _samples[name].append(ms)

def _print_summary():
    if not BENCH_MODE or not _samples:
        return
    print("\n── PERF-01 summary ─────────────")
    print(f"{'stage':<22} {'n':>4} {'p50':>8} {'p95':>8} {'mean':>8}")
    for stage, s in sorted(_samples.items()):
        s_sorted = sorted(s)
        n = len(s_sorted)
        p50 = s_sorted[n // 2]
        p95 = s_sorted[int(n * 0.95)] if n >= 20 else s_sorted[-1]
        mean = sum(s_sorted) / n
        print(f"{stage:<22} {n:>4} {p50:>7.1f}ms {p95:>7.1f}ms {mean:>7.1f}ms")

atexit.register(_print_summary)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pydantic v1 `@validator` decorators | Pydantic v2 `@field_validator` | 2023, mature by 2026 | All examples here use v2 idioms |
| Logging via stdlib `logging` + handlers | loguru with single-call configuration | loguru 0.5+ (2021); standard for new projects 2026 | One-import-line setup vs ~10 lines of stdlib config |
| OpenAI SDK 0.x (`openai.api_key = "..."`) | OpenAI SDK 1.x+ class-based (`OpenAI(api_key=...)`) | November 2023 SDK rewrite | Project already on 2.x — fine. `client.with_options()` is the per-request pattern. |
| httpx 0.27 default `max_keepalive_connections=20` | httpx 0.28 same; OpenAI overrides to 100 | mid-2024 | Use OpenAI's `DefaultHttpxClient` to get sensible defaults |
| Python `dataclasses.dataclass(slots=True)` | Default-recommended for new code | 3.10+ | Optional optimization; add `slots=True` for AppState if memory matters (it doesn't here) |

**Deprecated / outdated:**
- `os._exit(0)` — current line 3139. Replaced by cooperative shutdown.
- `print(..., flush=True)` as logging — replaced by loguru.
- YAML→JSON fallback in `_load_yaml` — replaced by pydantic-validated load + loud error on YAML failure.
- One OpenAI client serving both Groq and OpenAI — replaced by per-provider clients dict.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Holding `state.lock` inside `audio_callback` is acceptable (<1µs per frame) | AppState design | Could cause audio frame drops. Mitigation: measure under load; fall back to thread-safe deque if frames drop. |
| A2 | Mutable dataclass + RLock is the right choice over `frozen=True` | AppState design | If user wants stronger guarantees, frozen would be preferable. The argument is refactor cost — debatable. |
| A3 | macOS daemon accessory mode never receives Cmd+Q, so we don't need `applicationWillTerminate_` | Signal handling | If a future feature adds a menu bar item that exposes Quit, this assumption breaks. |
| A4 | OpenAI fallback latency budget of 1 attempt is enough | REL-05 | If OpenAI is also flaky on that day, the user sees a fatal error. Could be 2 attempts; trade-off is user-perceived "give up" time. |
| A5 | Groq 5% drop rate from Spike 001 generalizes to ongoing usage | REL-05 design | Could be specific to that day's Groq capacity. Fallback is a hedge; doesn't depend on exact rate. |
| A6 | `keepalive_expiry=30.0` is the right tuning for dictation cadence | HTTP pooling | If users typically dictate >30s apart, every request needs a fresh handshake. Could go to 60s. PERF-01 measurements will inform this. |
| A7 | BENCH_MODE env var is preferred over `--bench-mode` CLI flag | PERF-01 | Either works; env var matches the precedent in `bench/latency_bench.py` (BENCH_ITER) but a flag is more discoverable. |
| A8 | Validation Architecture section is correctly omitted because `nyquist_validation: false` | Phase config | Confirmed by reading config.json — explicit. No risk. |
| A9 | Existing `_state_lock` (Lock) → RLock change won't break anything | AppState design | RLock can be acquired re-entrantly by the same thread. If a caller relied on Lock's blocking behavior to detect re-entry as a bug, this hides it. Low probability — the codebase uses `with _state_lock:` exclusively. |
| A10 | `print()` calls in onboarding (SETUP_STRINGS rendering) should stay as `print()`, not go through loguru | Loguru migration | Deliberate exception. Alternative: loguru with `format="{message}"` console handler — but loguru would strip ANSI by default in non-color mode. Easier to just leave onboarding as `print`. |
| A11 | The `delayed_start` stale-closure bug in CONCERNS.md is no longer present | CLAUDE.md adherence | Verified by `grep delayed_start govori.py` returning nothing — function was removed in phase 01.1 work. CONCERNS.md is stale on this point. |
| A12 | Tests are out-of-scope for Phase 2 | Phase scope | Explicit in prompt. Wave 0 / test-seam guidance is "leave the modules mockable" — no pytest dep yet. |
| A13 | The `_tap_health_check` thread reading `_hud_error_mode` without a lock is OK | Module decomposition | UI-thread-only mutation per current code; cross-thread read is best-effort. Same race exists today; not a Phase 2 fix. |
| A14 | Renaming the entrypoint from `govori.py` to `python -m govori` won't break user shortcuts | Module decomposition | The `govori` wrapper script (5 lines at repo root) needs updating. Cron / launchd entries with `python govori.py` hardcoded would break — but project has no recorded launchd entries. |

**If this table is empty:** Not empty — 14 assumptions logged. Several have low risk (A8, A11); two are medium and should be surfaced to the user during planning (A2 mutable-vs-frozen, A4 fallback retry count).

## Open Questions

1. **Should `_apply_self_corrections` (the Haiku cleanup pass) live in `transcribe.py` or `notes.py`?**
   - What we know: It's called only from `audio.py:stop_and_transcribe` (line 1837), after non-predict transcription. It uses Anthropic (notes' provider) but operates on dictation text.
   - What's unclear: Is it conceptually "post-transcription cleanup" (→ transcribe.py) or "note-style processing" (→ notes.py)?
   - Recommendation: `transcribe.py`. The function operates on transcript text and is part of the dictation pipeline, not the note-classification pipeline. Anthropic is a tool, not a domain marker.

2. **Where should `_retry_transcription` (the click-to-retry handler) live?**
   - What we know: It's wired to a HUD click event. It reads `_retry_buffer` from state, calls `_encode_and_transcribe`, then calls `paste_text` / `save_or_merge_note` / `show_predict_menu` based on `_retry_mode_snapshot`.
   - What's unclear: Is its home `hud.py` (UI-event-driven) or `transcribe.py` (transcription operation)?
   - Recommendation: `transcribe.py`. The HUD just dispatches it; the logic is "do the transcription pipeline using stored state." Treating it as `transcribe.retry()` makes the API clean. Phase 4 (parallel encoding) will probably want to revisit this anyway.

3. **AppState immutability — is the mutable-with-lock choice future-proof?**
   - What we know: Existing code uses Lock-protected mutation. Phase 2 extends this with an RLock.
   - What's unclear: If Phase 4 adds asynchronous encoding (background queue producing OGG packets), the state machine grows. At some point frozen+`replace()` may pay off.
   - Recommendation: Keep mutable + RLock for Phase 2. Mark as a v2 candidate for re-evaluation when Phase 4 lands.

4. **Should `bench_mode` be a CLI flag, env var, or both?**
   - What we know: Spike 001's bench script uses `BENCH_ITER` env var as precedent.
   - What's unclear: Is `./govori --bench-mode` more discoverable than `BENCH_MODE=1 ./govori`?
   - Recommendation: env var as primary (matches spike pattern), CLI flag in cli.py that translates to the env var if user prefers. Low cost to support both.

5. **Plugin manifest validation — Phase 2 or later?**
   - What we know: REL-04 says "invalid YAML/values produce user-friendly error messages." Plugins are also YAML.
   - What's unclear: The REQ wording focuses on `config.yaml`. Should plugins get the same pydantic treatment?
   - Recommendation: Yes, extend validation to plugin manifests within Phase 2 — same library, similar code, big UX win. But mark it as a stretch goal; if plan is tight, ship config validation first and add plugin validation later.

6. **What's the minimum acceptable test seam for Phase 2 to leave behind?**
   - What we know: Phase 3 will add pytest. Phase 2 just needs to enable that.
   - What's unclear: Should Phase 2 add a `tests/` directory with one passing import-test, or wait for Phase 3?
   - Recommendation: Add a tests/ directory with one trivial `test_imports.py` that imports each module — catches the "module-level side effects" anti-pattern instantly. Zero pytest dep; can run with `python -c "import govori.config; ..."`. Phase 3 turns this into proper pytest later.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.10+ | All modules | ✓ | 3.14.3 in `.venv/` | None — Phase 2 requires 3.10+ for `__future__ annotations` and modern dataclass features |
| `loguru` package | REL-02 logging | ✗ — not in venv | (latest 0.7.3) | Install via `pip install loguru` |
| `pydantic` v2 | REL-04 config validation | ✓ | 2.13.2 installed | None needed — already present |
| `httpx` | HTTP pooling | ✓ | 0.28.1 installed (transitive via openai) | None needed |
| `openai` package | Transcription | ✓ | 2.32.0 installed (latest 2.36.0) | Consider bumping to 2.36 in Phase 3 |
| PortAudio | Audio capture | ✓ (assumed — already works) | system library | If missing: covered by Phase 1.1 REL-01 |
| macOS Accessibility permission | Hotkey monitor | ✓ (assumed — already granted) | runtime | If revoked: covered by Phase 1.1 SEC-02 |
| Groq API key (`GROQ_API_KEY`) | Primary transcription | likely yes (user has been using Groq) | n/a | Without it, falls back to OpenAI immediately (acceptable) |
| OpenAI API key (`OPENAI_API_KEY`) | Fallback per REL-05 | likely yes (was original setup) | n/a | Without it, no fallback — REL-05 degrades gracefully (log "fallback not configured") |

**Missing dependencies with no fallback:**

- `loguru` — install before Phase 2 implementation starts: `pip install loguru` (will also need to land in requirements.txt; pyproject.toml is Phase 3)

**Missing dependencies with fallback:**

- None blocking. REL-05 is designed so missing OpenAI key just disables fallback rather than failing.

## Sources

### Primary (HIGH confidence)

- Context7 `/delgan/loguru` — rotation, retention, enqueue, file/console sinks (loguru 0.7.3)
- Context7 `/openai/openai-python` — `DefaultHttpxClient`, `http_client` parameter, `with_options`
- [github.com/openai/openai-python README](https://github.com/openai/openai-python) — custom httpx client patterns
- [Groq API errors docs](https://console.groq.com/docs/errors) — verified retryable vs permanent status codes
- [Groq Speech-to-Text docs](https://console.groq.com/docs/speech-to-text) — `whisper-large-v3-turbo` model name, OpenAI-compatible base URL
- [httpx Resource Limits docs](https://www.python-httpx.org/advanced/resource-limits/) — default pool config (100/20)
- [pydantic v2 ValidationError docs](https://docs.pydantic.dev/latest/errors/validation_errors/) — `errors()` API and loc paths
- Local: `govori.py` (3145 lines, read all relevant sections), `.planning/codebase/` (STRUCTURE, CONCERNS, ARCHITECTURE, INTEGRATIONS, TESTING, CONVENTIONS), Spike 001 results
- Local: `pip list` output confirming installed versions (pydantic 2.13.2, openai 2.32.0, httpx 0.28.1)
- Local: `pip index versions` for latest available (loguru 0.7.3, openai 2.36.0, pydantic 2.13.4)

### Secondary (MEDIUM confidence)

- [prodisup.com Swift signal capture](https://prodisup.com/posts/2022/10/signal-capture-and-graceful-shutdown-in-swift/) — signal handler + NSApp.terminate pattern (Swift, applied to PyObjC by analogy)
- [johal.in signal handling guide](https://johal.in/signal-handling-in-python-custom-handlers-for-graceful-shutdowns/) — flag-based pattern
- [pyblog.in 2026 dataclass guide](https://www.pyblog.in/programming/python-dataclasses-the-complete-2026-guide-from-dataclass-to-slots-frozen-and-__post_init__/) — frozen recommended by default
- [github.com/openai/openai-python issue #2539](https://github.com/openai/openai-python/issues/2539) — PoolTimeout under sequential requests; informs pool sizing recommendation
- [github.com/openai/openai-python issue #821](https://github.com/openai/openai-python/issues/821) — PoolTimeout patterns
- [DeepWiki Custom HTTP Clients page](https://deepwiki.com/openai/openai-python/7.4-custom-http-clients-and-proxies) — pooling details

### Tertiary (LOW confidence — needs validation)

- 5% Groq drop rate from Spike 001 — single-run measurement; could be specific to that day's API conditions
- 30-second keepalive_expiry recommendation — based on dictation cadence heuristic; PERF-01 measurements should refine
- Assumed audio callback lock acceptability — needs empirical validation under recording load

## Metadata

**Confidence breakdown:**
- Module decomposition: HIGH — clean ASCII-separated sections map 1:1 to target modules; line-by-line audit confirmed
- AppState design: HIGH — pattern is straightforward extension of existing `_state_lock` approach
- Loguru integration: HIGH — Context7 docs verified; idiomatic patterns well-established
- Signal handling: MEDIUM — pattern is standard but PyObjC + NSRunLoop interaction depends on `runMode_beforeDate_` polling letting Python signal-flag race resolve cleanly; empirical validation recommended during Wave 1
- Config validation: HIGH — pydantic v2 is well-documented and already installed
- PERF-01 instrumentation: HIGH — contextmanager pattern is canonical
- REL-05 fallback: MEDIUM — architecture is sound but specific retry budget (1 OpenAI attempt) is a judgment call
- HTTP pooling: HIGH — OpenAI SDK explicitly exposes `http_client`; behavior verified via Context7

**Research date:** 2026-05-13
**Valid until:** ~2026-08-13 (loguru and pydantic move slowly; OpenAI SDK should be re-checked before Phase 3 packaging — recommend `pip index versions openai` before pinning)

## RESEARCH COMPLETE

**Phase:** 2 - Architecture & Reliability + Latency Foundations
**Confidence:** HIGH

### Key Findings

- **govori.py decomposition is mechanical, not creative.** ASCII-separated sections at lines 46, 51, 283, 630, 861, 905, 934, 1425, 1872, 1902, 2176, 2391, 2497, 2680, 3038, 3107 each map cleanly to one target module. No architectural design needed; mostly cut-and-paste.
- **pydantic is already installed transitively** (2.13.2 in `.venv/`), so REL-04 config validation costs zero new dep weight. Cerberus would have been a downgrade.
- **The OpenAI SDK explicitly supports a custom `DefaultHttpxClient`** with named pool limits — the recommended path is one `OpenAI()` instance per provider, each holding its own httpx client with `max_keepalive_connections=5, keepalive_expiry=30.0`. This is enough to eliminate per-dictation TLS handshakes.
- **Current `os._exit(0)` signal handler is broken-by-design.** REL-03 needs a small refactor: signal handler sets `threading.Event`, main `runMode_beforeDate_` loop polls the event, then cooperative cleanup runs before `NSApp.terminate_(None)`.
- **REL-05 fallback architecture is "wrap, don't interleave":** Groq gets its existing 1+2 retry budget; on terminal failure (not PERMANENT_API_ERROR), one OpenAI attempt. Provider identity flows through structured loguru `bind()` so logs show which provider answered.
- **PERF-01 should measure outer stages with `@contextmanager`-based spans** that emit to loguru `bind(stage=...)`. `BENCH_MODE=1` env var enables an `atexit`-registered p50/p95 summary. Watch out: `_transcribe_with_auto_retries` spawns a worker thread, so `api_call` span must live inside `_encode_and_transcribe` while `transcribe_full` wraps the retry wrapper.

### File Created

`/Users/genlorem/Projects/govori/.planning/phases/02-architecture-reliability-latency-foundations/02-RESEARCH.md`

### Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| Module decomposition | HIGH | Line-by-line audit done; sections map 1:1 |
| AppState design | HIGH | Extends existing pattern; no novel concurrency |
| Loguru integration | HIGH | Verified via Context7; canonical 0.7.3 API |
| Signal handling | MEDIUM | Pattern standard; PyObjC interaction needs Wave 1 empirical check |
| Config validation | HIGH | pydantic already installed; v2 ValidationError formatting documented |
| PERF-01 spans | HIGH | contextmanager + perf_counter is textbook |
| REL-05 fallback | MEDIUM | Architecture clear; retry-budget choice is judgment-based |
| HTTP pooling | HIGH | OpenAI SDK explicitly exposes `http_client` parameter |

### Open Questions

- Mutable AppState dataclass + RLock vs `frozen=True` + `dataclasses.replace()` — recommend mutable (extends existing pattern), flagged as v2 reconsideration after Phase 4 (A2)
- Number of OpenAI fallback attempts (1 vs 2) when Groq fails terminally (A4)
- `_apply_self_corrections` lives in `transcribe.py` or `notes.py` (recommend transcribe.py)
- `_retry_transcription` lives in `hud.py` or `transcribe.py` (recommend transcribe.py)
- Plugin manifest validation as part of Phase 2 stretch goal or defer to v2

### Ready for Planning

Research complete. Planner can create PLAN.md files. **Recommended plan ordering:** architecture extraction first (modules + AppState + loguru + signal handling + config validation) as a self-contained refactor, then transcribe-specific work (per-provider clients + REL-05 fallback + PERF-01 spans + HTTP pooling) as a second plan that depends on the new module structure. This sequencing means the second plan is small and surgical — it operates on `transcribe.py` only.
