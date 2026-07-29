# Architecture

**Analysis Date:** 2026-04-15

## Pattern Overview

**Overall:** Single-file monolith with plugin extension points

**Key Characteristics:**
- All application logic lives in one file: `govori.py` (1912 lines)
- macOS-native daemon: runs a `NSRunLoop`, registers a global `CGEventTap`
- Three operating modes gated by modifier keys at recording time
- Plugins are pure data (YAML files); the host app drives all behavior
- Lazy-init Anthropic client — only allocated when note mode is first used

## Layers

**CLI / Entry Routing:**
- Purpose: Parse CLI args, route to subcommands or daemon startup
- Location: `govori.py`, functions `cli_main()`, `cli_setup()`, `cli_plugin()`, `cli_notes()`
- Contains: Setup wizard, plugin management CLI, notes picker CLI
- Depends on: Config layer, plugin layer
- Used by: `__main__` block at bottom of file

**Configuration & Plugin Discovery:**
- Purpose: Load `~/.config/govori/config.yaml` and discover plugins from `~/.config/govori/plugins/`
- Location: `govori.py`, functions `load_config()`, `load_plugins()`, `build_whisper_prompt()`, `build_notes_config()`
- Contains: YAML loading with JSON fallback, plugin metadata merging
- Depends on: Filesystem (`~/.config/govori/`)
- Used by: All other layers at module load time via globals `CONFIG`, `PLUGINS`, `NOTES_CFG`

**Audio Capture:**
- Purpose: Stream microphone input via sounddevice while fn is held
- Location: `govori.py`, functions `start_recording()`, `stop_and_transcribe()`, `cancel_recording()`, `audio_callback()`
- Contains: sounddevice stream management, state flags (`recording`, `audio_chunks`, `cancelled`)
- Depends on: State globals, HUD layer
- Used by: Hotkey event callback

**Transcription:**
- Purpose: Encode raw float32 audio → OGG/Opus → POST to OpenAI Whisper
- Location: `govori.py`, function `_encode_and_transcribe()`
- Contains: PyAV OGG encoding, OpenAI audio API call, hallucination filtering
- Depends on: `openai.OpenAI` client, `av`, `numpy`
- Used by: `stop_and_transcribe()`, `_note_pipeline_background()`, `cli_notes()`

**Mode Dispatch:**
- Purpose: Route transcribed text to the correct post-processing path
- Location: `govori.py`, `stop_and_transcribe()` branching on `note_mode` / `predict_mode`
- Three paths:
  1. **Dictate** → `paste_text()` + optional `_press_enter()`
  2. **Predict** → `paste_text()` + `show_predict_menu()`
  3. **Note** → `_note_pipeline_background()` (fire-and-forget thread)

**Note Pipeline:**
- Purpose: Classify → merge-check → write markdown file + append to JSONL index
- Location: `govori.py`, functions `classify_note()`, `save_or_merge_note()`, `save_as_note()`, `_save_note_with_meta()`, `_decide_merge()`, `_confirm_merge()`, `_apply_merge_append()`
- Contains: Anthropic Haiku calls, file I/O, frontmatter generation, index management
- Depends on: `anthropic.Anthropic` client (lazy), `NOTES_CFG` global
- Used by: `_note_pipeline_background()`, `cli_notes()`, `__main__` note-text path

**Predict / Autocomplete:**
- Purpose: Generate 3 GPT-4o-mini continuations and show NSMenu picker
- Location: `govori.py`, functions `generate_continuations()`, `show_predict_menu()`, class `PredictController`
- Contains: OpenAI chat completion call, AppKit NSMenu rendering
- Depends on: `openai.OpenAI` client, AppKit
- Used by: `stop_and_transcribe()` after paste

**HUD (Heads-Up Display):**
- Purpose: Tiny 32px floating NSPanel showing current state with animated icon
- Location: `govori.py`, functions `setup_hud()`, `set_hud()`
- Contains: NSPanel, NSTextField, CABasicAnimation pulse
- Depends on: AppKit, Quartz
- Used by: All layers that change operational state

**Hotkey Monitor:**
- Purpose: Global CGEventTap listening for fn, Shift, Option, Esc, Enter key events
- Location: `govori.py`, functions `install_monitor()`, `cg_event_callback()`
- Contains: Quartz event tap, modifier flag detection, delayed-start logic (250ms debounce)
- Depends on: Quartz, CoreFoundation
- Used by: Main run loop

**Clipboard / Keyboard Injection:**
- Purpose: Write text to NSPasteboard and synthesize Cmd+V, optionally Enter
- Location: `govori.py`, functions `paste_text()`, `_press_enter()`
- Contains: NSPasteboard read/write, CGEvent keyboard synthesis, async clipboard restore
- Depends on: AppKit, Quartz
- Used by: Mode dispatch (dictate, predict)

## Data Flow

**Dictate mode (fn hold → release):**

1. `cg_event_callback` detects fn key down (flags changed event), starts 250ms debounce thread
2. `start_recording()` opens `sd.InputStream`, sets `recording=True`, HUD shows red dot
3. User speaks; `audio_callback` appends chunks to `audio_chunks`
4. fn released → `stop_and_transcribe()` in background thread
5. `_encode_and_transcribe()`: numpy concat → normalize → PyAV OGG encode → `client.audio.transcriptions.create()`
6. `_is_hallucination()` filter applied
7. `paste_text(text)` → NSPasteboard write → CGEvent Cmd+V → async clipboard restore

**Note mode (Shift+fn):**

1-5 same as dictate, but `note_mode=True`
6. `stop_and_transcribe()` fires `_note_pipeline_background()` in daemon thread, immediately hides HUD
7. `classify_note()` → Anthropic Haiku returns JSON `{title, contexts, type, urgency, tags, related_stuck}`
8. `_validate_meta()` coerces values against `NOTES_CFG` valid sets
9. `_find_merge_candidates()` reads recent JSONL index entries matching context within 6-hour window
10. `_decide_merge()` → Anthropic Haiku decides new vs. merge
11. `_confirm_merge()` applies 0.85 confidence threshold
12. Write markdown file with YAML frontmatter OR append to existing file; append index entry to `recent.jsonl`

**Predict mode (Option+fn):**

1-6 same as dictate (text pasted first)
7. `show_predict_menu()` → `generate_continuations()` → GPT-4o-mini chat completion
8. NSMenu shown at mouse cursor; user selects → `paste_text(continuation)`

**State Management:**
- Global mutable state protected by `threading.Lock()` (`_state_lock`): `recording`, `transcribing`, `audio_chunks`, `audio_stream`, `auto_send`, `cancelled`, `predict_mode`, `note_mode`
- All state changes happen in background threads; UI updates dispatched to main queue via `NSOperationQueue.mainQueue().addOperationWithBlock_`

## Key Abstractions

**Plugin:**
- Purpose: Extend post-transcription behavior via declarative YAML
- Examples: `~/.config/govori/plugins/notes/plugin.yaml`, `examples/notes/plugin.yaml`
- Pattern: Directory under `~/.config/govori/plugins/<name>/` with `plugin.yaml` (required), `contexts.yaml` (optional), `stuck.yaml` (optional). Host reads and merges at startup — no executable code in plugins.

**NOTES_CFG dict:**
- Purpose: Flattened notes plugin config available to all note functions
- Built by: `build_notes_config()` from loaded plugin YAML
- Shape: `{classifier_model, output_dir, index_file, valid_contexts (set), valid_stuck (set), contexts_desc, stuck_desc}`

**Note index (JSONL):**
- Purpose: Lightweight searchable record of all saved notes for merge-check and `govori notes` picker
- Location: `~/govori-notes/index/recent.jsonl` (configurable via `NOTES_CFG["index_file"]`)
- Format: One JSON object per line — `{id, created, path, contexts, type, urgency, related_stuck, summary}`

**Note file (Markdown):**
- Purpose: Persistent note with YAML frontmatter
- Location: `~/govori-notes/{year}/{month}/{date}_{time}_{slug}.md`
- Schema: frontmatter fields `id, created, source, duration_sec, contexts, type, urgency, tags, related_stuck, [review], [amended]`; body is raw transcription text

## Entry Points

**Daemon startup:**
- Location: `govori.py`, `__main__` block (line 1882)
- Triggers: `python3 govori.py` (or `./govori` shell script)
- Responsibilities: Create NSApplication accessory, setup HUD, setup predict controller, install event tap, run NSRunLoop forever

**CLI subcommand routing:**
- Location: `govori.py`, `cli_main()` (line 519) — runs at module load before `__main__`
- Routes: `setup`, `plugin list|init|remove`, `notes`, `note <text>`

**Note text CLI:**
- Location: `govori.py`, `__main__` block, `_NOTE_CLI_TEXT` branch (line 1886)
- Triggers: `govori note <text>` or `echo text | govori note`
- Responsibilities: Call `save_or_merge_note()` and exit

## Error Handling

**Strategy:** Best-effort with silent degradation — errors are printed to stdout, never propagate to crash the daemon

**Patterns:**
- All API calls (`transcription`, `classify_note`, `_decide_merge`, `generate_continuations`) wrapped in `try/except Exception as e: print(f"...: {e}")`
- On Anthropic failure in notes pipeline, falls back to `{"title": "note", "contexts": ["default"], ..., "review": True}`
- On merge decision failure, defaults to `action: "new"`
- Hallucination filter: known Whisper hallucination phrases silently dropped (see `WHISPER_HALLUCINATIONS` set)
- Clipboard restore: async thread restores original clipboard 150ms after paste

## Cross-Cutting Concerns

**Logging:** `print(..., flush=True)` throughout — no structured logging framework. All output goes to stdout of the terminal running govori.

**Validation:** `_validate_meta()` coerces Anthropic classifier output against known-valid sets (`valid_contexts`, `valid_stuck`, `VALID_TYPES`, `VALID_URGENCY`). Strip/default on invalid values.

**Authentication:** API keys loaded from environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). Keys sourced from `~/.config/govori/env` (shell export file, not dotenv). Setup wizard writes this file at `chmod 600`.

**Threading:** Background threads for audio stop+transcribe, note pipeline, clipboard restore, HUD hide timers. All are daemon threads. Main thread is macOS NSRunLoop. State mutation guarded by `_state_lock`.

---

*Architecture analysis: 2026-04-15*
