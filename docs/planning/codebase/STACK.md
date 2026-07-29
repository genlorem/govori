# Technology Stack

**Analysis Date:** 2026-04-15

## Languages

**Primary:**
- Python 3 (3.14.x in dev environment) - entire application

## Runtime

**Environment:**
- macOS only (uses native Cocoa/Quartz APIs — not portable to Linux/Windows)
- Python virtualenv at `.venv/` (activated by the `govori` launcher script)

**Package Manager:**
- pip
- Lockfile: absent (only `requirements.txt` with unpinned package names)

## Frameworks

**Core:**
- No web framework — single-file application (`govori.py`)
- AppKit (via `pyobjc-framework-Cocoa`) — macOS HUD window, clipboard, NSMenu
- Quartz (via `pyobjc-framework-Quartz`) — key event injection, Core Animation

**Testing:**
- Not detected — no test files, no pytest/unittest configuration

**Build/Dev:**
- None — no build step; run directly as `./govori` or `python govori.py`

## Key Dependencies

**Critical:**
- `openai` (unpinned) — Whisper speech-to-text (`whisper-1` or `gpt-4o-transcribe`) and GPT-4o-mini predict mode
- `anthropic` (unpinned) — Claude Haiku note classification (optional; lazy-imported)
- `sounddevice` (unpinned) — microphone capture via PortAudio
- `soundfile` (unpinned) — audio file utilities (imported alongside sounddevice)
- `numpy` (unpinned) — audio array normalization and RMS silence detection
- `av` (unpinned) — PyAV; encodes raw float32 PCM → OGG/Opus before sending to Whisper
- `pyyaml` (unpinned) — config/plugin YAML parsing (gracefully falls back to JSON if absent)
- `pyobjc-framework-Cocoa` (unpinned) — AppKit bindings
- `pyobjc-framework-Quartz` (unpinned) — Quartz/CG bindings

**Infrastructure:**
- No database, no web server, no task queue

## Configuration

**Environment:**
- API keys loaded from `~/.config/govori/env` (shell export file sourced by the `govori` launcher)
- Required: `OPENAI_API_KEY`
- Optional: `ANTHROPIC_API_KEY` (needed for notes plugin)
- Configurable env var name via `api_key_env` in config.yaml (allows pointing at any env var for the OpenAI key)

**Application config:**
- `~/.config/govori/config.yaml` — language, model, sample_rate, whisper_prompt, base_url, api_key_env
- `~/.config/govori/plugins/<name>/plugin.yaml` — per-plugin settings
- `~/.config/govori/plugins/<name>/contexts.yaml` — note classification contexts
- `~/.config/govori/plugins/<name>/stuck.yaml` — ongoing tasks for note linking
- `~/.config/govori/.setup_done` — sentinel file marking first-run setup complete

**Build:**
- No build config files

## Platform Requirements

**Development:**
- macOS (Cocoa/Quartz APIs are macOS-only)
- Python 3.x with virtualenv
- Accessibility permission in System Settings → Privacy → Accessibility
- PortAudio (installed as a dependency of sounddevice, typically via Homebrew)

**Production:**
- macOS only; runs as a foreground daemon process
- No packaging/distribution mechanism detected (no setup.py, pyproject.toml, or installer)
- Optional: Hammerspoon for the status HUD overlay (`extras/hud/status_hud.lua`)

---

*Stack analysis: 2026-04-15*
