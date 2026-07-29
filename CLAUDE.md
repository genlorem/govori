## Project

**Govori**

Voice dictation tool for macOS. Hold fn to record, release to transcribe and paste at cursor. Supports three modes: dictation, predictive autocomplete, and voice notes with AI classification. Plugin system for extensibility.

**Core Value:** Frictionless voice-to-text on macOS — press a key, speak, text appears where you need it. Zero UI chrome, zero context switching.

### Constraints

- **Platform**: macOS only — Cocoa APIs, Accessibility permission, CGEventTap
- **Privacy**: Voice audio goes to OpenAI cloud, notes to Anthropic — must disclose
- **Dependencies**: Python 3.8+, requires .venv with sounddevice, pyobjc, av, openai, anthropic
- **Architecture**: Single-file Python — works for now, but reaching maintainability ceiling (~1900 lines)

## Technology Stack

## Languages
- Python 3 (3.14.x in dev environment) - entire application
## Runtime
- macOS only (uses native Cocoa/Quartz APIs — not portable to Linux/Windows)
- Python virtualenv at `.venv/` (activated by the `govori` launcher script)
- pip
- Lockfile: absent (only `requirements.txt` with unpinned package names)
## Frameworks
- No web framework — single-file application (`govori.py`)
- AppKit (via `pyobjc-framework-Cocoa`) — macOS HUD window, clipboard, NSMenu
- Quartz (via `pyobjc-framework-Quartz`) — key event injection, Core Animation
- Not detected — no test files, no pytest/unittest configuration
- None — no build step; run directly as `./govori` or `python govori.py`
## Key Dependencies
- `openai` (unpinned) — Whisper speech-to-text (`whisper-1` or `gpt-4o-transcribe`) and GPT-4o-mini predict mode
- `anthropic` (unpinned) — Claude Haiku note classification (optional; lazy-imported)
- `sounddevice` (unpinned) — microphone capture via PortAudio
- `soundfile` (unpinned) — audio file utilities (imported alongside sounddevice)
- `numpy` (unpinned) — audio array normalization and RMS silence detection
- `av` (unpinned) — PyAV; encodes raw float32 PCM → OGG/Opus before sending to Whisper
- `pyyaml` (unpinned) — config/plugin YAML parsing (gracefully falls back to JSON if absent)
- `pyobjc-framework-Cocoa` (unpinned) — AppKit bindings
- `pyobjc-framework-Quartz` (unpinned) — Quartz/CG bindings
- No database, no web server, no task queue
## Configuration
- API keys loaded from `~/.config/govori/env` (shell export file sourced by the `govori` launcher)
- Required: `OPENAI_API_KEY`
- Optional: `ANTHROPIC_API_KEY` (needed for notes plugin)
- Configurable env var name via `api_key_env` in config.yaml (allows pointing at any env var for the OpenAI key)
- `~/.config/govori/config.yaml` — language, model, sample_rate, whisper_prompt, base_url, api_key_env
- `~/.config/govori/plugins/<name>/plugin.yaml` — per-plugin settings
- `~/.config/govori/plugins/<name>/contexts.yaml` — note classification contexts
- `~/.config/govori/plugins/<name>/stuck.yaml` — ongoing tasks for note linking
- `~/.config/govori/.setup_done` — sentinel file marking first-run setup complete
- No build config files
## Platform Requirements
- macOS (Cocoa/Quartz APIs are macOS-only)
- Python 3.x with virtualenv
- Accessibility permission in System Settings → Privacy → Accessibility
- PortAudio (installed as a dependency of sounddevice, typically via Homebrew)
- macOS only; runs as a foreground daemon process
- No packaging/distribution mechanism detected (no setup.py, pyproject.toml, or installer)
- Optional: Hammerspoon for the status HUD overlay (`extras/hud/status_hud.lua`)

## Conventions

## Naming Patterns
- Single-file project: `govori.py` is the entire application
- Helper/example configs: lowercase with hyphens (`plugin.yaml`, `contexts.yaml`, `stuck.yaml`)
- Docs: `README.md`
- Public API functions: `snake_case`, descriptive verbs — `start_recording`, `stop_and_transcribe`, `classify_note`, `save_as_note`
- Private/internal helpers: `_snake_case` with leading underscore — `_load_yaml`, `_encode_and_transcribe`, `_validate_meta`, `_sanitize_slug`, `_resolve_path`, `_get_anthropic_client`
- CLI entry points: `cli_` prefix — `cli_setup`, `cli_plugin`, `cli_main`, `cli_notes`
- Setup/install functions: `setup_` prefix — `setup_hud`, `setup_predict`
- Event callbacks: `_callback` or `_event_callback` suffix — `audio_callback`, `cg_event_callback`
- Module-level constants: `ALL_CAPS` — `CONFIG_DIR`, `SAMPLE_RATE`, `MODEL`, `MERGE_WINDOW_HOURS`, `VALID_TYPES`
- Module-level state: `snake_case` globals — `recording`, `transcribing`, `audio_chunks`, `predict_mode`, `note_mode`
- Private globals: `_snake_case` — `_state_lock`, `_api_key`, `_anthropic_client`, `_predict_controller`, `_fn_press_time`
- Local variables: `snake_case`
- PascalCase: `PredictController`
- Inherits from Objective-C base: `AppKit.NSObject`
## Code Style
- No formatter config detected (no `.black`, `.flake8`, `pyproject.toml`, `setup.cfg`)
- Indentation: 4 spaces consistently
- Line length: not enforced by tooling; long lines occur in string literals and complex expressions
- Blank lines: 2 blank lines between top-level definitions; 1 blank line between logical sections inside functions
- No linting config detected
- Style is manually consistent throughout the single file
- Visual ASCII separators mark logical sections: `# ── Section Name ─────────────────────────`
- Sections in `govori.py`: Paths, Config loading, Onboarding/Setup, CLI subcommands, State, HUD, Audio, Note mode, Merge-check pipeline, Predict mode, Hotkey, Notes CLI, Main
## Import Organization
## Error Handling
## Logging
- Status prints use Unicode symbols: `●` recording, `■` transcribing, `→` result, `✎` note saved, `✓` success, `✗` error, `⇪` merge
- Debug/state prints use bracket prefix: `[mode] shift=...`, `[toggle] note_mode=...`
- Error prints: `print(f"Error description: {e}", flush=True)`
- Parenthetical skips: `print("(empty)", flush=True)`, `print("(cancelled)", flush=True)`, `print("(too short)", flush=True)`
## Comments
- All public-ish functions have single-line or multi-line `"""docstrings"""`
- Private helpers (`_` prefix) sometimes omit docstrings for trivial functions
- Module-level docstring at top of file describes modes and plugin path
## Function Design
- Functions that may fail return `None` or a safe fallback dict
- Predicates (`_is_hallucination`, `_is_first_run`) return `bool`
- Pipelines return structured `dict` (e.g., `classify_note`, `_decide_merge`)
## Module Design

## Architecture

## Pattern Overview
- All application logic lives in one file: `govori.py` (1912 lines)
- macOS-native daemon: runs a `NSRunLoop`, registers a global `CGEventTap`
- Three operating modes gated by modifier keys at recording time
- Plugins are pure data (YAML files); the host app drives all behavior
- Lazy-init Anthropic client — only allocated when note mode is first used
## Layers
- Purpose: Parse CLI args, route to subcommands or daemon startup
- Location: `govori.py`, functions `cli_main()`, `cli_setup()`, `cli_plugin()`, `cli_notes()`
- Contains: Setup wizard, plugin management CLI, notes picker CLI
- Depends on: Config layer, plugin layer
- Used by: `__main__` block at bottom of file
- Purpose: Load `~/.config/govori/config.yaml` and discover plugins from `~/.config/govori/plugins/`
- Location: `govori.py`, functions `load_config()`, `load_plugins()`, `build_whisper_prompt()`, `build_notes_config()`
- Contains: YAML loading with JSON fallback, plugin metadata merging
- Depends on: Filesystem (`~/.config/govori/`)
- Used by: All other layers at module load time via globals `CONFIG`, `PLUGINS`, `NOTES_CFG`
- Purpose: Stream microphone input via sounddevice while fn is held
- Location: `govori.py`, functions `start_recording()`, `stop_and_transcribe()`, `cancel_recording()`, `audio_callback()`
- Contains: sounddevice stream management, state flags (`recording`, `audio_chunks`, `cancelled`)
- Depends on: State globals, HUD layer
- Used by: Hotkey event callback
- Purpose: Encode raw float32 audio → OGG/Opus → POST to OpenAI Whisper
- Location: `govori.py`, function `_encode_and_transcribe()`
- Contains: PyAV OGG encoding, OpenAI audio API call, hallucination filtering
- Depends on: `openai.OpenAI` client, `av`, `numpy`
- Used by: `stop_and_transcribe()`, `_note_pipeline_background()`, `cli_notes()`
- Purpose: Route transcribed text to the correct post-processing path
- Location: `govori.py`, `stop_and_transcribe()` branching on `note_mode` / `predict_mode`
- Three paths:
- Purpose: Classify → merge-check → write markdown file + append to JSONL index
- Location: `govori.py`, functions `classify_note()`, `save_or_merge_note()`, `save_as_note()`, `_save_note_with_meta()`, `_decide_merge()`, `_confirm_merge()`, `_apply_merge_append()`
- Contains: Anthropic Haiku calls, file I/O, frontmatter generation, index management
- Depends on: `anthropic.Anthropic` client (lazy), `NOTES_CFG` global
- Used by: `_note_pipeline_background()`, `cli_notes()`, `__main__` note-text path
- Purpose: Generate 3 GPT-4o-mini continuations and show NSMenu picker
- Location: `govori.py`, functions `generate_continuations()`, `show_predict_menu()`, class `PredictController`
- Contains: OpenAI chat completion call, AppKit NSMenu rendering
- Depends on: `openai.OpenAI` client, AppKit
- Used by: `stop_and_transcribe()` after paste
- Purpose: Tiny 32px floating NSPanel showing current state with animated icon
- Location: `govori.py`, functions `setup_hud()`, `set_hud()`
- Contains: NSPanel, NSTextField, CABasicAnimation pulse
- Depends on: AppKit, Quartz
- Used by: All layers that change operational state
- Purpose: Global CGEventTap listening for fn, Shift, Option, Esc, Enter key events
- Location: `govori.py`, functions `install_monitor()`, `cg_event_callback()`
- Contains: Quartz event tap, modifier flag detection, delayed-start logic (250ms debounce)
- Depends on: Quartz, CoreFoundation
- Used by: Main run loop
- Purpose: Write text to NSPasteboard and synthesize Cmd+V, optionally Enter
- Location: `govori.py`, functions `paste_text()`, `_press_enter()`
- Contains: NSPasteboard read/write, CGEvent keyboard synthesis, async clipboard restore
- Depends on: AppKit, Quartz
- Used by: Mode dispatch (dictate, predict)
## Data Flow
- Global mutable state protected by `threading.Lock()` (`_state_lock`): `recording`, `transcribing`, `audio_chunks`, `audio_stream`, `auto_send`, `cancelled`, `predict_mode`, `note_mode`
- All state changes happen in background threads; UI updates dispatched to main queue via `NSOperationQueue.mainQueue().addOperationWithBlock_`
## Key Abstractions
- Purpose: Extend post-transcription behavior via declarative YAML
- Examples: `~/.config/govori/plugins/notes/plugin.yaml`, `examples/notes/plugin.yaml`
- Pattern: Directory under `~/.config/govori/plugins/<name>/` with `plugin.yaml` (required), `contexts.yaml` (optional), `stuck.yaml` (optional). Host reads and merges at startup — no executable code in plugins.
- Purpose: Flattened notes plugin config available to all note functions
- Built by: `build_notes_config()` from loaded plugin YAML
- Shape: `{classifier_model, output_dir, index_file, valid_contexts (set), valid_stuck (set), contexts_desc, stuck_desc}`
- Purpose: Lightweight searchable record of all saved notes for merge-check and `govori notes` picker
- Location: `~/govori-notes/index/recent.jsonl` (configurable via `NOTES_CFG["index_file"]`)
- Format: One JSON object per line — `{id, created, path, contexts, type, urgency, related_stuck, summary}`
- Purpose: Persistent note with YAML frontmatter
- Location: `~/govori-notes/{year}/{month}/{date}_{time}_{slug}.md`
- Schema: frontmatter fields `id, created, source, duration_sec, contexts, type, urgency, tags, related_stuck, [review], [amended]`; body is raw transcription text
## Entry Points
- Location: `govori.py`, `__main__` block (line 1882)
- Triggers: `python3 govori.py` (or `./govori` shell script)
- Responsibilities: Create NSApplication accessory, setup HUD, setup predict controller, install event tap, run NSRunLoop forever
- Location: `govori.py`, `cli_main()` (line 519) — runs at module load before `__main__`
- Routes: `setup`, `plugin list|init|remove`, `notes`, `note <text>`
- Location: `govori.py`, `__main__` block, `_NOTE_CLI_TEXT` branch (line 1886)
- Triggers: `govori note <text>` or `echo text | govori note`
- Responsibilities: Call `save_or_merge_note()` and exit
## Error Handling
- All API calls (`transcription`, `classify_note`, `_decide_merge`, `generate_continuations`) wrapped in `try/except Exception as e: print(f"...: {e}")`
- On Anthropic failure in notes pipeline, falls back to `{"title": "note", "contexts": ["default"], ..., "review": True}`
- On merge decision failure, defaults to `action: "new"`
- Hallucination filter: known Whisper hallucination phrases silently dropped (see `WHISPER_HALLUCINATIONS` set)
- Clipboard restore: async thread restores original clipboard 150ms after paste
## Cross-Cutting Concerns

## Project Skills

| Skill | Description | Path |
|-------|-------------|------|
| debug-prod |  | `.claude/skills/debug-prod/SKILL.md` |
