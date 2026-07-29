# External Integrations

**Analysis Date:** 2026-04-15

## APIs & External Services

**Speech-to-Text:**
- OpenAI Whisper — transcribes recorded audio after `fn` key release
  - SDK/Client: `openai` Python package; client instantiated at module load in `govori.py` (line ~583)
  - Models: `whisper-1` (default) or `gpt-4o-transcribe` (via `--gpt` flag)
  - Auth: `OPENAI_API_KEY` env var (configurable via `api_key_env` in config.yaml)
  - Optional: `base_url` config key allows pointing at a custom OpenAI-compatible endpoint

**Text Autocomplete:**
- OpenAI GPT-4o-mini — generates 3 text continuations in predict mode (`Option+fn`)
  - SDK/Client: same `openai` client instance as Whisper
  - Called via `client.chat.completions.create()` in `generate_continuations()` (`govori.py` ~line 1346)
  - Auth: same `OPENAI_API_KEY`

**Note Classification:**
- Anthropic Claude Haiku — classifies transcribed voice notes into user-defined contexts
  - SDK/Client: `anthropic` Python package; lazy-initialized via `_get_anthropic_client()` (`govori.py` ~line 588)
  - Default model: `claude-haiku-4-5-20251001` (overridable via `classifier_model` in `plugin.yaml`)
  - Auth: `ANTHROPIC_API_KEY` env var
  - Usage: two separate calls — `classify_note()` (note classification) and `_decide_merge()` (merge decision)
  - Optional: if Anthropic key is absent, notes fall back to unclassified defaults with `review: true`

## Data Storage

**Databases:**
- None — no database engine used

**File Storage:**
- Local filesystem only
  - Notes saved as markdown files: `~/govori-notes/{year}/{month}/{date}_{time}_{slug}.md`
  - Note index (append-only JSONL): `~/govori-notes/index/recent.jsonl`
  - Output paths are templated and configurable via `output_dir` / `index_file` in `plugin.yaml`

**Caching:**
- None

## Authentication & Identity

**Auth Provider:**
- None — no user authentication
- API keys stored in `~/.config/govori/env` as shell export statements, sourced by the `govori` launcher script
- File permissions on `~/.config/govori/env` set to `0o600` (owner-read-only) during setup

## Monitoring & Observability

**Error Tracking:**
- None — errors printed to stdout/stderr with `flush=True`

**Logs:**
- stdout only; structured as human-readable status lines (e.g., `→ transcribed text`, `✎ saved: filename`)

## CI/CD & Deployment

**Hosting:**
- Local machine only — no remote deployment

**CI Pipeline:**
- None detected

## Environment Configuration

**Required env vars:**
- `OPENAI_API_KEY` — required at startup; missing key causes immediate `sys.exit(1)`

**Optional env vars:**
- `ANTHROPIC_API_KEY` — required only when notes plugin is active; missing key disables classification silently

**Secrets location:**
- `~/.config/govori/env` (local, not committed; created during `govori setup`)

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None — all API calls are synchronous request/response with no webhooks

## macOS System Integrations

**Accessibility API (Quartz CGEvent):**
- Used to inject keyboard events (Cmd+V paste, Enter key) into the active application
- Requires Accessibility permission in System Settings → Privacy → Accessibility

**NSPasteboard (Cocoa):**
- Writes transcribed text to clipboard before simulating paste
- Restores previous clipboard contents after 150ms

**fn / modifier key detection (Quartz CGEventTap):**
- Monitors `fn`, `Option+fn`, `Shift+fn` global hotkeys system-wide via event tap

**NSPanel HUD (Cocoa + Core Animation):**
- Borderless floating panel rendered above all windows; animates via `CABasicAnimation`

**Hammerspoon (optional, `extras/hud/status_hud.lua`):**
- Separate optional integration; polls for the `govori` process and shows a status dot
- Activated by adding a `dofile` line to `~/.hammerspoon/init.lua`

---

*Integration audit: 2026-04-15*
