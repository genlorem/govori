# Research Summary: Govori Market Readiness

**Synthesized:** 2026-04-17
**Sources:** STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md

## Executive Summary

- **Govori's feature set is competitive** — zero-UI philosophy, plugin system, predictive autocomplete, and voice notes with AI classification are genuinely unique among macOS dictation tools. The gap is production hygiene, not features.
- **CGEventTap is a ticking bomb** — if Accessibility permission is revoked while running, the tap can swallow all system input, requiring hard reboot. This is the #1 ship-blocker.
- **Single-file architecture must be split** — not for aesthetics, but because 6 distinct concerns share 11 mutable globals with no isolation, making testing impossible and error handling fragile.
- **Privacy disclosure is non-negotiable** — competitors advertise local-first processing; shipping cloud-only without prominent disclosure looks deceptive and creates legal liability.
- **uv + hatchling + pyproject.toml** is the standard 2026 Python packaging stack. PyPI-first distribution via `pipx install govori`.

## Consensus Across All Dimensions

All four research dimensions agree on these priorities:

1. **Security first** — shell injection fix (trivial) + CGEventTap health monitoring (critical)
2. **Privacy disclosure** — must happen before any public link is shared
3. **Packaging before distribution** — pyproject.toml with pinned deps before PyPI publish
4. **Module extraction enables everything** — testing, logging, error handling all blocked by single-file architecture
5. **Don't add features** — the existing feature set is competitive; ship reliability, not novelty

## Key Tensions

| Tension | Stack says | Architecture says | Resolution |
|---------|-----------|-------------------|------------|
| Module split timing | pyproject.toml works with single file | Split first, it enables testing | **Split first** — packaging is trivial after |
| Logging library | loguru (zero-config) | Standard logging module | **loguru** — simpler migration from print() |
| Distribution channel | PyPI + Homebrew tap | Depends on package structure | **PyPI first**, Homebrew deferred |
| Python version floor | >=3.10 (PyObjC 12) | Not specified | **>=3.10** — macOS ships 3.x via Xcode |

## Recommended Phase Structure

### Phase 1: Security & Safety (blocks everything)
- Fix shell injection (line 1823: os.system → subprocess.run)
- CGEventTap health monitoring (detect revoked permission, prevent input freeze)
- Microphone error handling (try/except on sd.InputStream)
- API timeouts on OpenAI client (timeout=30)
- Privacy notice in onboarding + README

### Phase 2: Architecture & Packaging
- Extract single file into 10 modules (config → state → hud → audio → transcribe → notes → macos → predict → cli → __main__)
- Create pyproject.toml with hatchling backend
- Pin dependencies with uv.lock
- Add ruff config for linting
- Replace print() with loguru
- Graceful shutdown (signal handling)

### Phase 3: Testing & Distribution
- Smoke test suite (pytest) — config loading, API error handling, note merge logic
- Publish to PyPI (trusted publishers via GitHub Actions)
- Update README with real GitHub URL, system requirements, privacy policy
- Config validation with user-friendly errors

## Critical Path

```
CGEventTap fix ──┐
Shell injection ─┤
Privacy notice ──┤── Phase 1 (safety) ── Module extraction ── Phase 2 (architecture) ── Tests + PyPI ── Phase 3 (distribution)
Mic error ───────┤
API timeout ─────┘
```

Phase 1 items are independent (can parallelize). Phase 2 depends on Phase 1 completion. Phase 3 depends on Phase 2 (tests need modules, PyPI needs pyproject.toml).

## Open Questions Requiring User Input

1. **macOS version support** — Ventura (13), Sonoma (14), Sequoia (15)? CGEventTap behavior varies. Recommend >=13.
2. **Pricing model** — Free OSS vs freemium vs one-time purchase. Doesn't affect hardening work but affects positioning.
3. **STT abstraction** — Invest in making Whisper backend swappable for future local model support? Recommend minimal interface abstraction (one afternoon).
4. **Hammerspoon HUD dependency** — Acceptable for market release or needs native fallback? Competitors ship their own overlay.
5. **listenOnly vs defaultTap** — Using listenOnly mode for CGEventTap avoids input-freeze failure mode but may limit fn key detection.

---
*Synthesized from 4 parallel research agents (Opus, 2026-04-17)*
