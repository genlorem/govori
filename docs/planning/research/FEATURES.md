# Feature Landscape

**Domain:** macOS voice dictation CLI tool — production hardening for market release
**Researched:** 2026-04-17

## Table Stakes

Features users expect from any production-quality macOS voice dictation tool. Missing any of these = "alpha quality" perception and users leave.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Graceful error on missing microphone | Every competitor handles this; crash = uninstall | Low | Show clear message, not stack trace. Check `sd.query_devices()` at startup. |
| Accessibility permission guidance | macOS blocks CGEventTap without Accessibility grant; users hit this on first launch | Low | Detect denial, show System Settings deeplink. Competitors all do this. |
| Privacy disclosure | Voice goes to OpenAI, notes to Anthropic — users MUST know before first recording | Low | In-app notice at first run + privacy policy page on govori.io. GDPR/CCPA minimum. |
| API key validation at startup | Invalid key = silent failure currently; user thinks app is broken | Low | Hit a cheap endpoint on launch, report clear error if key invalid/missing. |
| API timeout and retry with backoff | Network flakes are normal; hanging forever is not | Low | 10s timeout, 3 retries with exponential backoff. Already in Active requirements. |
| File-based logging with rotation | stdout logging is invisible to users; crash diagnosis requires logs | Med | `logging` module with `RotatingFileHandler` to `~/.config/govori/logs/`. Cap at 5MB x 3 files. |
| Graceful shutdown on SIGINT/SIGTERM | Ctrl+C leaves orphaned threads, corrupted state | Low | Signal handlers to clean up audio stream, restore clipboard, exit cleanly. |
| Config validation with clear errors | Typo in config.yaml = cryptic crash | Med | Validate all fields at startup. "Unknown key 'langauge' — did you mean 'language'?" |
| `pip install` / `pipx install` support | Manual venv + `python govori.py` is developer-only UX | Med | Requires pyproject.toml, proper package structure, entry point. This is THE install story for v1. |
| Dependency version pinning | Unpinned deps = random breakage on install | Low | Lock file or pinned ranges in pyproject.toml. |
| Security: fix shell injection in note editing | Known vulnerability in Active requirements — shipping with it is irresponsible | Low | Use subprocess list args, never `shell=True` with user input. |
| Meaningful error messages (not tracebacks) | Tracebacks scare non-developer users | Med | Top-level exception handler that logs traceback to file, shows human message to terminal. |
| Version check / update notification | Users need to know when updates exist | Low | `govori --version` already exists. Add a check against PyPI/GitHub releases on startup (weekly, non-blocking). |
| Sound/visual feedback for all states | Users need to know: recording, processing, done, error | Low | Already have HUD dot. Ensure error state is distinct (red) and timeout state exists. |
| Clean uninstall path | Users expect reversibility | Low | Document: `pipx uninstall govori` + `rm -rf ~/.config/govori` (with confirmation prompt as a command). |

## Differentiators

Features that set Govori apart from Wispr Flow ($15/mo), Superwhisper ($250), VoiceInk ($40). Not expected but create competitive advantage.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Zero-UI philosophy (no window, no menu bar) | Wispr Flow/VoiceInk/Voibe all have menu bar chrome. Govori's "invisible tool" approach is genuinely different. | Already done | Lean into this. The HUD dot is enough. Don't add a menu bar app. |
| Plugin system (YAML-only, safe) | No competitor has extensibility. VoiceInk is open-source but requires forking. Govori plugins are declarative and safe. | Already done | Document well for v1. This is the moat. |
| Predictive autocomplete mode | Unique — no competitor offers voice-triggered autocomplete with multiple suggestions. | Already done | Polish the UX, ensure suggestion cycling is smooth. |
| Voice notes with AI classification | Competitors do transcription only. Govori classifies into contexts, urgency, type, tags automatically. | Already done | Highlight in marketing. "Dictation + thinking" angle. |
| Bilingual by default (en/ru) | Most competitors are English-first. Native bilingual support is rare. | Already done | Add more languages later, but en/ru is already differentiating. |
| Free and open source | VoiceInk is GPL open-source at $40. Wispr Flow is $15/mo closed. Govori can be free + open, funded differently. | N/A | Decision point: pricing model. Free OSS is a differentiator. |
| Offline/local model option (future) | Currently out of scope, but the privacy trend is strong. VoiceInk and Voibe both run locally. | High | Don't build for v1. But architect so it's possible later (STT backend abstraction). |
| Per-app dictation profiles | VoiceInk's "Power Mode" does this — different settings per active app. Govori's plugin system could enable this. | Med | v2 candidate. Plugin system makes this possible without core changes. |

## Anti-Features

Things to deliberately NOT build for v1. Each one is a trap that wastes time or hurts the product.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| GUI settings panel | Config.yaml IS the interface. A GUI adds massive complexity (PyObjC windows, state sync, testing) for a developer-audience tool. Wispr Flow needs a GUI because it targets non-developers. Govori targets developers. | Validate config.yaml well, provide `govori config --check` command. |
| Menu bar / status bar app | Breaks the "zero chrome" differentiator. Adds rumps/PyObjC complexity. The HUD dot already communicates state. | Keep HUD dot. Add `govori status` CLI command if needed. |
| Real-time streaming transcription | "Hold and release" is the UX model and it's simpler, more reliable, lower latency-perception than streaming with corrections. Wispr Flow does streaming — don't compete on their turf. | Keep hold-to-record. It's a feature, not a limitation. |
| Homebrew formula for v1 | Homebrew tap/formula is ongoing maintenance (CI, bottle builds, version bumps). pipx is simpler and sufficient for developer audience. | Ship on PyPI first. Homebrew formula is a v2 nice-to-have. |
| Windows/Linux support | macOS-native APIs (CGEventTap, Cocoa) are deeply embedded. Cross-platform means rewriting input handling, UI, audio. | Stay macOS-only. The "built for Mac" positioning is fine — competitors do this too. |
| Built-in crash reporting service | Sentry/Raygun integration is overkill for a CLI tool. File-based logs + GitHub Issues is sufficient for v1 scale. | Log to file. `govori --diagnostic` dumps system info + recent logs for bug reports. |
| Custom STT model / local Whisper | Adding whisper.cpp or similar doubles complexity. VoiceInk already does this well. Compete on workflow, not on STT engine. | Keep cloud Whisper. Abstract the STT interface so local can be added later. |
| Team/collaboration features | Wispr Flow has team plans. Govori is a personal tool. Don't chase enterprise. | Individual developer tool. Period. |
| Auto-update mechanism | PyUpdater/tufup add complexity. pipx upgrade is one command. Users who install via pipx already know how to upgrade. | `govori --version` + check-for-update notification is enough. Document `pipx upgrade govori`. |

## Feature Dependencies

```
pyproject.toml packaging  -->  pip/pipx installability  -->  PyPI publishing
                           -->  entry point (`govori` command)
                           -->  dependency pinning

config validation  -->  meaningful error messages (validation errors use same pattern)

file-based logging  -->  diagnostic command (`govori --diagnostic`)

graceful shutdown  -->  clipboard restoration on crash
                   -->  audio stream cleanup

privacy disclosure  -->  govori.io privacy policy page
                    -->  first-run notice in onboarding flow

API key validation  -->  startup health check (key + mic + permissions)
```

## MVP Recommendation

Prioritize for market release (in this order):

1. **Security fix** — shell injection in note editing. Non-negotiable before any public release.
2. **pyproject.toml + package structure** — without this, there's no install story. This is the gateway to everything else.
3. **Startup health checks** — microphone, permissions, API key validation. One function that runs at launch and reports all issues clearly.
4. **Error handling overhaul** — top-level exception handler, API timeouts/retries, meaningful messages instead of tracebacks.
5. **File-based logging** — with rotation. Makes everything else debuggable.
6. **Graceful shutdown** — signal handlers, cleanup.
7. **Privacy disclosure** — first-run notice + govori.io/privacy page.
8. **Config validation** — catch typos, unknown keys, missing required fields.
9. **Version check** — non-blocking weekly check against PyPI for newer version.
10. **Diagnostic command** — `govori --diagnostic` for bug reports.

**Defer to post-launch:**
- Per-app profiles (plugin system already enables this)
- Local STT option (architecture it now, build later)
- Homebrew formula
- Additional languages beyond en/ru

## Sources

- [Wispr Flow features and pricing](https://docs.wisprflow.ai/articles/9559327591-flow-plans-and-what-s-included)
- [VoiceInk review and features](https://www.getvoibe.com/resources/voiceink-review/)
- [Voibe vs VoiceInk comparison](https://www.getvoibe.com/resources/voibe-vs-voiceink/)
- [Whispr Flow vs Superwhisper comparison](https://www.getvoibe.com/resources/wispr-flow-vs-superwhisper/)
- [Best dictation apps for macOS 2026](https://www.macaiapps.com/blog/best-dictation-apps-for-macos/)
- [Python packaging - pyproject.toml guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [Python logging best practices 2026](https://www.carmatec.com/blog/python-logging-best-practices-complete-guide/)
- [pipx for Python CLI tools](https://github.com/pypa/pipx)
- [GDPR compliance for apps 2026](https://secureprivacy.ai/blog/gdpr-compliance-mobile-apps)
- [macOS accessibility - VoiceOver](https://developer.apple.com/documentation/accessibility/voiceover/)
