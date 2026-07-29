# Codebase Concerns

**Analysis Date:** 2026-04-15

## Tech Debt

**Monolithic single-file architecture:**
- Issue: All 1900+ lines of application logic live in one file — `govori.py`. Audio recording, transcription, HUD rendering, hotkey interception, note classification, merge logic, CLI subcommands, and onboarding are all interleaved.
- Files: `govori.py`
- Impact: Any change to one subsystem requires reading and navigating the whole file. High collision risk when working on unrelated features simultaneously.
- Fix approach: Extract into modules — `govori/audio.py`, `govori/hud.py`, `govori/keys.py`, `govori/notes/`, `govori/cli.py`.

**Module-level code runs at import time:**
- Issue: `cli_main()` (line 562), `CONFIG = load_config()` (line 165), `PLUGINS = load_plugins()` (line 166), and OpenAI client initialization (line 583) all execute unconditionally at module load. This means even `govori setup` initializes the OpenAI client and exits if `OPENAI_API_KEY` is missing.
- Files: `govori.py` lines 165–583
- Impact: Any CLI subcommand that does not need the API key (e.g., `govori plugin list`) still triggers `sys.exit(1)` if the env var is absent. Makes unit testing impossible without mocking or env setup.
- Fix approach: Move OpenAI client creation inside a lazy initializer, mirroring the existing `_get_anthropic_client()` pattern.

**Duplicate note-writing logic:**
- Issue: `save_as_note()` (line 1054) and `_save_note_with_meta()` (line 1284) write virtually identical frontmatter and index-append code. They diverged to allow `save_or_merge_note()` to reuse a pre-classified meta dict.
- Files: `govori.py` lines 1054–1120 and 1284–1336
- Impact: Frontmatter fields changed in one function silently diverge from the other. Currently `save_as_note()` is not called in the main recording path — it exists as a dead code island.
- Fix approach: Consolidate to `_save_note_with_meta()`, remove `save_as_note()` or make it a thin wrapper.

**`_confirm_merge()` is a stub:**
- Issue: The function docstring explicitly states "Future: will show HUD panel and wait for user choice" (line 1211). Currently it is a pure threshold check with no user interaction.
- Files: `govori.py` lines 1209–1218
- Impact: Merges happen silently; a false merge with confidence ≥ 0.85 permanently modifies an existing note without the user knowing. No undo path.
- Fix approach: Implement HUD confirmation prompt or at minimum log the merge decision to stdout before applying it.

**`delayed_start()` checks stale closure variable:**
- Issue: In `cg_event_callback()` (line 1481–1483), `delayed_start` sleeps 0.25s then checks `if not prev_fn_down: return`. But `prev_fn_down` is a module-level name captured by reference. By the time the thread wakes, `prev_fn_down` has already been updated to `True` by the same event that launched the thread, so the guard never fires — the check is logically inverted and never prevents a recording from starting.
- Files: `govori.py` lines 1479–1501
- Impact: The intended 250ms debounce to prevent accidental short fn presses does not work. Every fn keydown launches a recording after 250ms regardless.
- Fix approach: Capture the `is_down` value at thread creation time and compare against a fresh read of `Quartz.CGEventGetFlags` or use an event object to cancel.

## Known Bugs

**Clipboard race condition in `paste_text()`:**
- Symptoms: If the user presses fn again within 150ms of a paste (or if a background app modifies the clipboard), the restore thread may paste the wrong content or clear clipboard data the user had copied.
- Files: `govori.py` lines 915–932
- Trigger: Fast successive dictation, or clipboard managers (e.g., Raycast clipboard history) writing to the pasteboard within the 150ms window.
- Workaround: None. The 150ms sleep is a fixed guess, not keyed to paste completion.

**`audio_chunks` race between callback and `stop_and_transcribe()`:**
- Symptoms: `audio_callback` appends to `audio_chunks` (line 726) without holding `_state_lock`. `stop_and_transcribe()` reads `audio_chunks` outside the lock after setting `recording = False` (lines 832–838). A callback invocation that began before `recording` was set False can append after the lock is released.
- Files: `govori.py` lines 724–726 and 828–838
- Trigger: Race window is tiny (one callback frame ≈ a few ms) but non-zero on slow machines or under load.
- Workaround: None in current code.

**`save_as_note()` is unreachable dead code:**
- Symptoms: The function exists and is complete, but `save_or_merge_note()` (the only caller path from recording) calls `_save_note_with_meta()` directly. `save_as_note()` can only be called if someone invokes it directly.
- Files: `govori.py` lines 1054–1126
- Trigger: Any code review or refactor targeting note-saving may modify the wrong function.

**`_fzf_pick()` preview command is broken:**
- Issue: Line 1660 constructs a shell preview command using Python's `os.environ["GOVORI_PATHS"]` with embedded f-string quoting that will break for file paths containing spaces or special characters. The `{}` in the fzf `--preview` argument is also used as both an fzf placeholder and a Python format specifier.
- Files: `govori.py` lines 1656–1672
- Trigger: Any note path containing a space (e.g., `~/govori-notes/2026/04` is fine, but user-defined `output_dir` with spaces would break it).

## Security Considerations

**API keys stored in a plain-text shell script:**
- Risk: `~/.config/govori/env` is a `source`-able shell file with `export KEY=value` lines. If the user's home directory has broad permissions, or a malicious process reads `~/.config/govori/env`, both OpenAI and Anthropic keys are exposed in plaintext.
- Files: `govori` (line 4), `govori.py` (lines 349–366)
- Current mitigation: `env_file.chmod(0o600)` is applied during `cli_setup()`. Only applies when setup writes the file; if the user creates it manually, permissions are not enforced.
- Recommendations: Document the 0o600 requirement explicitly; add a startup check that warns if permissions are too open.

**`os.system(f"{editor} {path}")` allows command injection:**
- Risk: In `cli_notes()` (line 1824), the editor command and note path are passed directly to `os.system`. If a note file path contains shell metacharacters (semicolon, backtick, `$(...)`), a malicious note filename could execute arbitrary shell commands.
- Files: `govori.py` line 1824
- Current mitigation: None. Note paths are constructed with `_sanitize_slug()` which only allows `[a-z0-9-]` in the slug portion, but the base output_dir comes from user config and is not sanitized.
- Recommendations: Replace `os.system()` with `subprocess.run([editor, str(path)])`.

**`GOVORI_PATHS` env var in subprocess is unbounded:**
- Risk: `_fzf_pick()` passes all note paths as a newline-delimited env var `GOVORI_PATHS` (line 1667). If the index grows large, this may hit OS env var size limits (typically 128KB–2MB depending on macOS version).
- Files: `govori.py` lines 1659–1667
- Current mitigation: Index reads are capped at 30 entries via `_read_index_entries(limit=30)`.

## Performance Bottlenecks

**Blocking transcription on the main thread in normal mode:**
- Problem: `_encode_and_transcribe()` is called directly in `stop_and_transcribe()` (line 873) for normal and predict modes. This blocks the thread calling `stop_and_transcribe()`, which is a daemon thread — but the Whisper API call can take 1–5 seconds, during which the HUD shows "transcribing" with no timeout or cancellation.
- Files: `govori.py` lines 868–895
- Cause: No timeout parameter on `client.audio.transcriptions.create()`. No `cancelled` flag check during the API call.
- Improvement path: Run transcription in a thread with a timeout; check `cancelled` before pasting result.

**`_read_index_entries()` reads up to 12 month-files on every note save:**
- Problem: `save_or_merge_note()` → `_find_merge_candidates()` → `_read_index_entries(limit=20)` iterates up to 12 monthly index files (line 1540) on every recording in note mode.
- Files: `govori.py` lines 1533–1565
- Cause: No in-memory cache; reads from disk every time.
- Improvement path: Cache the index in memory with a short TTL (e.g., 60s) or only search the current month's file unless it's the first days of a month.

**Two sequential Anthropic API calls per note save:**
- Problem: `save_or_merge_note()` calls `classify_note()` (one Anthropic call) and then `_decide_merge()` (a second Anthropic call) sequentially. Even for a 3-second dictation, saving takes 2–4 seconds of API latency.
- Files: `govori.py` lines 1266–1281
- Cause: Classification and merge-check are designed as separate steps.
- Improvement path: Combine into a single prompt that returns both classification and merge decision in one JSON object.

## Fragile Areas

**Global mutable state for recording pipeline:**
- Files: `govori.py` lines 602–610
- Why fragile: `recording`, `transcribing`, `audio_chunks`, `audio_stream`, `auto_send`, `cancelled`, `predict_mode`, `note_mode` are all module-level globals protected (inconsistently) by `_state_lock`. `audio_chunks` is mutated from the audio callback thread without the lock.
- Safe modification: Any change to recording state must trace all three code paths: `start_recording()`, `stop_and_transcribe()`, `cancel_recording()`. All three must be updated atomically.
- Test coverage: No tests exist.

**`cg_event_callback` runs on the main run loop thread:**
- Files: `govori.py` lines 1433–1508
- Why fragile: The Quartz event callback fires on the main CFRunLoop. If any code called from it blocks (e.g., `set_hud()` queues on `NSOperationQueue.mainQueue()`), there is potential for deadlock. Currently `set_hud` is safe, but adding synchronous operations here would deadlock.
- Safe modification: Keep the callback non-blocking; dispatch all work to daemon threads.

**YAML fallback silently loses config:**
- Files: `govori.py` lines 50–61
- Why fragile: If `pyyaml` is not installed, `_load_yaml()` falls back to `json.loads()`. A valid YAML config (which is not valid JSON) will silently return `{}`, causing all settings to revert to defaults with no error.
- Safe modification: Always require PyYAML (it is in `requirements.txt`, so only a broken venv would trigger this). Consider raising a clear error instead of silently returning `{}`.

## Scaling Limits

**JSONL index grows unbounded:**
- Current capacity: Index file appended to indefinitely; no pruning.
- Limit: `_read_index_entries()` only reads the last 30 entries, but the file itself grows forever. Each note save appends one or two lines; merge operations also append. After a year of heavy use the file could exceed hundreds of MB.
- Scaling path: Add periodic index compaction (keep last N entries per context); or split by month (partially done via `{year}/{month}` path templates for notes, but index is a single file).

## Dependencies at Risk

**`soundfile` listed in requirements but never imported:**
- Risk: `soundfile` appears in `requirements.txt` but is not imported anywhere in `govori.py`. It is an unnecessary dependency that inflates the install footprint and introduces a potential vulnerability surface.
- Impact: Minor — wasted install time; potential future confusion.
- Migration plan: Remove `soundfile` from `requirements.txt`.

**Hardcoded model names `claude-haiku-4-5-20251001` and `gpt-4o-mini`:**
- Risk: Model identifiers are hardcoded as string literals in three places — `build_notes_config()` default (line 154), `cli_setup()` plugin scaffold (line 388), `cli_plugin()` plugin init (line 472), and `generate_continuations()` (line 1346). When Anthropic or OpenAI deprecates these model versions, every hardcoded occurrence must be found and updated.
- Files: `govori.py` lines 154, 388, 472, 1346
- Migration plan: Centralize model names as module-level constants at the top of the file.

## Missing Critical Features

**No error recovery for microphone permission denial:**
- Problem: If macOS denies microphone access, `sd.InputStream` raises an exception. The exception is caught by the broad `except Exception: pass` in `start_recording()` (line 738), silently swallowing the error. The HUD shows "recording" indefinitely but no audio is captured.
- Blocks: User has no indication that recording failed due to permissions.

**No timeout on API calls:**
- Problem: Neither `client.audio.transcriptions.create()` nor `anthropic_client.messages.create()` have explicit timeouts. A network stall will hang the daemon thread indefinitely with the HUD stuck showing "transcribing" or "predicting".
- Files: `govori.py` lines 782–793, 1029–1044, 1181–1206

**`govori notes` edit confirmation has no diff review for non-TTY invocation:**
- Problem: `cli_notes()` calls `input()` for the "Apply? [y/N]:" prompt (line 1864). In non-TTY contexts (piped stdin), this raises `EOFError` and silently returns without applying or rejecting the edit.

## Test Coverage Gaps

**No tests exist at all:**
- What's not tested: Every function in `govori.py` — audio encoding, hallucination filtering, note classification, merge decision, frontmatter parsing, slug sanitization, YAML loading with fallback, CLI routing.
- Files: `govori.py` (entire file)
- Risk: Any refactor, model prompt change, or edge-case bug is invisible until it fails in production use.
- Priority: High — the note pipeline (`classify_note`, `_validate_meta`, `save_or_merge_note`, `_split_frontmatter`, `_update_frontmatter_amended`) is pure business logic with no UI or OS dependencies and should be unit-tested first.

---

*Concerns audit: 2026-04-15*
