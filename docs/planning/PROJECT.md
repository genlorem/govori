# Govori

## What This Is

Voice dictation tool for macOS. Hold fn to record, release to transcribe and paste at cursor. Supports three modes: dictation, predictive autocomplete, and voice notes with AI classification. Plugin system for extensibility.

## Core Value

Frictionless voice-to-text on macOS — press a key, speak, text appears where you need it. Zero UI chrome, zero context switching.

## Requirements

### Validated

- ✓ Voice recording via fn key with CGEventTap — existing
- ✓ Whisper API transcription (whisper-1 and gpt-4o-transcribe) — existing
- ✓ Paste at cursor via Cmd+V with clipboard restoration — existing
- ✓ Floating 32px HUD dot with color-coded states — existing
- ✓ Predictive mode with 3 autocomplete suggestions — existing
- ✓ Note mode with Claude classification (contexts, urgency, type, tags) — existing
- ✓ Plugin system (declarative YAML, init/list/remove) — existing
- ✓ Bilingual onboarding (en/ru) with step-by-step setup — existing
- ✓ Config via ~/.config/govori/ (YAML, env secrets) — existing
- ✓ Hallucination filter for Whisper artifacts — existing
- ✓ Silence and short audio detection — existing
- ✓ Note merging with Claude confidence scoring — existing
- ✓ Notes browser with fzf preview — existing

### Active

- [ ] Fix security vulnerabilities (shell injection in note editing)
- [ ] Error handling for missing microphone / permissions denied
- [ ] Privacy notice (voice sent to OpenAI, notes to Anthropic)
- [ ] API timeout and retry logic
- [ ] Proper distribution (pip install / pyproject.toml)
- [ ] Logging system (file-based, not stdout)
- [ ] Graceful shutdown (signal handling)
- [ ] Dependency version pinning
- [ ] Config validation with user-friendly errors
- [ ] Smoke test suite

### Out of Scope

- Mobile app — desktop-first, maybe later
- Windows/Linux support — macOS-native APIs (CGEventTap, Cocoa)
- Custom STT model — Whisper API is good enough, local models add complexity
- Real-time streaming transcription — hold-and-release is the UX model
- GUI settings panel — config.yaml is the interface for now

## Context

- Python single-file architecture (~1900 lines in govori.py)
- macOS-only: uses PyObjC for Cocoa, CGEventTap for hotkeys
- Audio: sounddevice → PyAV (OGG/Opus encoding) → OpenAI Whisper API
- Notes: Anthropic Claude Haiku for classification, markdown output with JSONL index
- HUD: Hammerspoon Lua script (extras/hud/status_hud.lua)
- Domain registered: govori.io (Porkbun, 2026-04-17)
- GitHub: gennadiy403/govori
- Version: 0.1.0 (pre-release)
- Renamed from Wisp → Govori (2026-04-17) to exit whisper-brand cluster

## Constraints

- **Platform**: macOS only — Cocoa APIs, Accessibility permission, CGEventTap
- **Privacy**: Voice audio goes to OpenAI cloud, notes to Anthropic — must disclose
- **Dependencies**: Python 3.8+, requires .venv with sounddevice, pyobjc, av, openai, anthropic
- **Architecture**: Single-file Python — works for now, but reaching maintainability ceiling (~1900 lines)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Rename Wisp → Govori | Exit crowded whisper-brand cluster (MacWhisper, Wispr Flow, etc.) | ✓ Good |
| Domain govori.io | Clean namespace, .io standard for dev tools, $28/yr | — Pending |
| Single-file architecture | Simplicity for v0.1, ship fast | ⚠️ Revisit at ~2500 lines |
| YAML-only plugins | Safety (no code execution), simplicity | ✓ Good |
| Cloud-only STT | Lower complexity, better accuracy than local Whisper | — Pending |

## Related Documents

- [PRODUCT-STRATEGY.md](./PRODUCT-STRATEGY.md) — модульная монетизация (core FREE + платные модули), 12-недельный план, pricing, license-инфра, market research. Стратегический слой: «что продаём и как». PROJECT.md — технический слой: «что уже есть в коде».

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-17 after initialization*
