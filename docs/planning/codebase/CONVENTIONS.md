# Coding Conventions

**Analysis Date:** 2026-04-15

## Naming Patterns

**Files:**
- Single-file project: `govori.py` is the entire application
- Helper/example configs: lowercase with hyphens (`plugin.yaml`, `contexts.yaml`, `stuck.yaml`)
- Docs: `README.md`

**Functions:**
- Public API functions: `snake_case`, descriptive verbs — `start_recording`, `stop_and_transcribe`, `classify_note`, `save_as_note`
- Private/internal helpers: `_snake_case` with leading underscore — `_load_yaml`, `_encode_and_transcribe`, `_validate_meta`, `_sanitize_slug`, `_resolve_path`, `_get_anthropic_client`
- CLI entry points: `cli_` prefix — `cli_setup`, `cli_plugin`, `cli_main`, `cli_notes`
- Setup/install functions: `setup_` prefix — `setup_hud`, `setup_predict`
- Event callbacks: `_callback` or `_event_callback` suffix — `audio_callback`, `cg_event_callback`

**Variables / Constants:**
- Module-level constants: `ALL_CAPS` — `CONFIG_DIR`, `SAMPLE_RATE`, `MODEL`, `MERGE_WINDOW_HOURS`, `VALID_TYPES`
- Module-level state: `snake_case` globals — `recording`, `transcribing`, `audio_chunks`, `predict_mode`, `note_mode`
- Private globals: `_snake_case` — `_state_lock`, `_api_key`, `_anthropic_client`, `_predict_controller`, `_fn_press_time`
- Local variables: `snake_case`

**Classes:**
- PascalCase: `PredictController`
- Inherits from Objective-C base: `AppKit.NSObject`

## Code Style

**Formatting:**
- No formatter config detected (no `.black`, `.flake8`, `pyproject.toml`, `setup.cfg`)
- Indentation: 4 spaces consistently
- Line length: not enforced by tooling; long lines occur in string literals and complex expressions
- Blank lines: 2 blank lines between top-level definitions; 1 blank line between logical sections inside functions

**Linting:**
- No linting config detected
- Style is manually consistent throughout the single file

**Section Separators:**
- Visual ASCII separators mark logical sections: `# ── Section Name ─────────────────────────`
- Sections in `govori.py`: Paths, Config loading, Onboarding/Setup, CLI subcommands, State, HUD, Audio, Note mode, Merge-check pipeline, Predict mode, Hotkey, Notes CLI, Main

## Import Organization

**Order:**
1. Standard library (`sys`, `os`, `io`, `json`, `time`, `threading`, `datetime`, `re`, `pathlib`)
2. Third-party (`numpy`, `av`, `sounddevice`, `openai`, `anthropic`, `yaml`)
3. macOS/PyObjC (`AppKit`, `Quartz`, `CoreFoundation`)
4. Late/conditional imports inside functions (`curses`, `shutil`, `subprocess`, `difflib`)

**Pattern for optional dependencies:**
```python
try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None
```

**Late imports:** stdlib modules only needed in specific code paths are imported inside the function body (e.g., `import curses` inside `_curses_pick`, `import shutil` inside `cli_plugin`, `import difflib` inside `cli_notes`).

## Error Handling

**Pattern:** All external I/O and API calls wrapped in `try/except Exception as e`:
```python
try:
    resp = anthropic_client.messages.create(...)
    raw = resp.content[0].text.strip()
    data = json.loads(raw)
    return _validate_meta(data)
except Exception as e:
    print(f"Classify error: {e}", flush=True)
    return {"title": "note", "contexts": ["default"], ...}  # safe fallback
```

**Fallback strategy:** Every function that can fail returns a safe default dict/value rather than propagating exceptions. Errors are printed to stdout with `flush=True`.

**Guard clauses:** Functions that depend on optional plugins check `if not NOTES_CFG:` at the top and return early with a message.

**Never raise:** No `raise` statements in user-facing code paths; exceptions are caught and logged.

## Logging

**Framework:** `print()` with `flush=True` — no logging library

**Patterns:**
- Status prints use Unicode symbols: `●` recording, `■` transcribing, `→` result, `✎` note saved, `✓` success, `✗` error, `⇪` merge
- Debug/state prints use bracket prefix: `[mode] shift=...`, `[toggle] note_mode=...`
- Error prints: `print(f"Error description: {e}", flush=True)`
- Parenthetical skips: `print("(empty)", flush=True)`, `print("(cancelled)", flush=True)`, `print("(too short)", flush=True)`

## Comments

**Section headers:** `# ── Section Name ───────────────────────────────────` marks top-level sections

**Inline comments:** Used for non-obvious logic — hardware keycodes (`0x24`, `0x09`), algorithm intent (`# Fall through:`, `# Conservative fallback:`), parameter explanations

**Docstrings:**
- All public-ish functions have single-line or multi-line `"""docstrings"""`
- Private helpers (`_` prefix) sometimes omit docstrings for trivial functions
- Module-level docstring at top of file describes modes and plugin path

**Future hooks:** `# Future: will show HUD panel and wait for user choice.` — in `_confirm_merge`

## Function Design

**Size:** Functions range from 5 to ~90 lines; most are 15–40 lines. Larger functions (`cli_setup`, `stop_and_transcribe`, `cg_event_callback`) contain clearly separated sub-blocks.

**Parameters:** Minimal — typically 1–3 params. Globals used heavily for shared state (`recording`, `audio_chunks`, `note_mode`, etc.) with `global` declarations when mutating.

**Return Values:** 
- Functions that may fail return `None` or a safe fallback dict
- Predicates (`_is_hallucination`, `_is_first_run`) return `bool`
- Pipelines return structured `dict` (e.g., `classify_note`, `_decide_merge`)

## Module Design

**Structure:** Single monolithic module (`govori.py`) — no packages or sub-modules

**Exports:** Not applicable (script, not library)

**Execution pattern:** Module-level code runs at import time: config is loaded, CLI routing runs, state globals are initialized, OpenAI client is constructed. `if __name__ == "__main__":` guard launches the macOS event loop or CLI subcommand.

**Side-effect pattern:** `cli_main()` is called at module scope (before `if __name__ == "__main__"`) so CLI routing happens even during import — this is intentional for the `notes` and `note` subcommands that set globals then fall through.

---

*Convention analysis: 2026-04-15*
