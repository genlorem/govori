# Requirements: Govori

**Defined:** 2026-04-17
**Core Value:** Frictionless voice-to-text on macOS — press a key, speak, text appears where you need it.

## v1 Requirements

Requirements for market-ready release (v1.0). Each maps to roadmap phases.

### Security

- [ ] **SEC-01**: Shell injection vulnerability fixed — os.system replaced with subprocess.run for note editing (line 1823)
- [ ] **SEC-02**: CGEventTap health monitoring — detect revoked Accessibility permission, prevent system input freeze, warn user
- [ ] **SEC-03**: API timeout set on OpenAI client (30s) with user-visible feedback when transcription hangs
- [ ] **SEC-04**: Privacy notice displayed during onboarding — user informed that voice audio is sent to OpenAI and notes to Anthropic

### Reliability

- [ ] **REL-01**: Microphone error handling — graceful message when no mic available or permissions denied, no crash
- [ ] **REL-02**: File-based logging via loguru — all print() replaced, log rotation, ~/.config/govori/govori.log
- [ ] **REL-03**: Graceful shutdown — proper signal handling, audio stream cleanup, no os._exit(0)
- [ ] **REL-04**: Config validation — invalid YAML/values produce user-friendly error messages, not silent {}
- [ ] **REL-05**: Transcribe layer resilience — exponential backoff retry on 5xx/timeout (2–3 attempts), AND automatic provider fallback (Groq → OpenAI) when `OPENAI_API_KEY` is configured. Reason: spike 001 showed Groq drops ~5% of requests transiently. Log line discloses which provider answered.

### Architecture

- [ ] **ARCH-01**: Module extraction — govori.py split into package: config, state, hud, audio, transcribe, notes, macos, predict, cli, __main__
- [ ] **ARCH-02**: State management — replace 11 mutable globals with AppState dataclass and explicit transitions
- [ ] **ARCH-03**: Entry point — govori.cli:main() callable from pyproject.toml scripts

### Performance

- [ ] **PERF-01**: Latency instrumentation — `stop_and_transcribe → encode → API → paste` chain wraps each stage with `time.perf_counter()` and emits structured timing events to log; `BENCH_MODE=1` env var prints per-stage summary on exit. Reason: spike 001 measured API alone (~440ms Groq); other ~1.5s of perceived pause live elsewhere and need ground truth before Phase 4.
- [ ] **PERF-02**: Post-release latency ≤ 1000ms p50 / ≤ 1500ms p95 for 4–25s dictations. Achieved by Phase 4 (parallel encoding). Verified by PERF-01 instrumentation.

### Distribution

- [ ] **DIST-01**: pyproject.toml with hatchling backend, Python >=3.10, all dependencies with compatible ranges
- [ ] **DIST-02**: Dependency pinning via uv.lock for reproducible installs
- [ ] **DIST-03**: PyPI publication — `pipx install govori` works, GitHub Actions with trusted publishers
- [ ] **DIST-04**: Smoke test suite (pytest) — config loading, API error handling, note merge logic, path sanitization

### Documentation

- [ ] **DOC-01**: README updated — real GitHub URL, system requirements (macOS >=13, Python >=3.10), privacy section
- [ ] **DOC-02**: Privacy policy page for govori.io — what data is sent where, retention, opt-out (notes plugin)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Distribution

- **DIST-05**: Homebrew tap formula for `brew install govori`
- **DIST-06**: Auto-update notification (check PyPI for newer version)

### Reliability

- **REL-06**: Clipboard race condition fix (sync mechanism instead of 0.15s sleep)

### Architecture

- **ARCH-04**: STT abstraction layer — interface for swappable backends (local Whisper, cloud Whisper)
- **ARCH-05**: Native HUD overlay — replace Hammerspoon dependency with PyObjC NSWindow

### Features

- **FEAT-01**: Configurable hallucination filter (user can add/remove patterns)
- **FEAT-02**: Configurable note merge threshold
- **FEAT-03**: `govori doctor` diagnostic command (check permissions, mic, API keys, config)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Windows/Linux support | macOS-native APIs (CGEventTap, Cocoa) |
| Mobile app | Desktop-first |
| GUI settings panel | config.yaml is the interface for now |
| Sentry crash reporting | Overkill for v1, loguru + GitHub Issues sufficient |
| Menu bar icon / tray | Zero-UI philosophy is a differentiator |
| Local Whisper model | Adds complexity, cloud accuracy is better |
| Real-time streaming STT | Hold-and-release is the UX model |
| .dmg/.pkg installer | PyInstaller + PyObjC is fragile, PyPI is cleaner |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SEC-01 | Phase 1 | ✓ Done |
| SEC-02 | Phase 1, 1.1 | ✓ Done |
| SEC-03 | Phase 1, 1.1 | ✓ Done |
| SEC-04 | Phase 1, 1.1 | ✓ Done |
| REL-01 | Phase 1, 1.1 | ✓ Done |
| REL-02 | Phase 2 | Pending |
| REL-03 | Phase 2 | Pending |
| REL-04 | Phase 2 | Pending |
| REL-05 | Phase 2 | Pending |
| ARCH-01 | Phase 2 | Pending |
| ARCH-02 | Phase 2 | Pending |
| ARCH-03 | Phase 2 | Pending |
| PERF-01 | Phase 2 | Pending |
| PERF-02 | Phase 4 | Pending |
| DIST-01 | Phase 3 | Pending |
| DIST-02 | Phase 3 | Pending |
| DIST-03 | Phase 3 | Pending |
| DIST-04 | Phase 3 | Pending |
| DOC-01 | Phase 3 | Pending |
| DOC-02 | Phase 3 | Pending |

**Coverage:**
- v1 requirements: 20 total
- Mapped to phases: 20
- Unmapped: 0

---
*Requirements defined: 2026-04-17*
*Last updated: 2026-05-13 — added PERF-01, PERF-02, REL-05 (latency work); promoted REL-05 from v2 backlog*
