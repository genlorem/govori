# Roadmap: Govori

## Overview

Govori's feature set is complete and competitive. This milestone hardens the existing codebase for public release: fix security vulnerabilities, extract modules from the 1900-line monolith, then package and distribute via PyPI. No new features -- ship reliability.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Security & Safety** - Fix ship-blocking vulnerabilities and add safety guards for system-level APIs
- [x] **Phase 1.1: Security Hardening (Codex Review)** *(INSERTED 2026-05-05)* - Fix 9 issues found by cross-AI review of phase 01 implementation
- [ ] **Phase 2: Architecture & Reliability + Latency Foundations** - Extract modules from monolith, replace globals with explicit state, add logging and graceful shutdown. Plus: instrumentation, Groq/OpenAI fallback, connection pooling — natural fit since transcribe module is being extracted.
- [ ] **Phase 4: Parallel Encoding** *(INSERTED 2026-05-13)* - Stream OGG/Opus encoding into a background queue during recording so post-release latency drops from ~2s to ~600ms
- [ ] **Phase 3: Packaging & Distribution** - Package for PyPI, add smoke tests, publish with documentation

## Phase Details

### Phase 1: Security & Safety
**Goal**: Users can run Govori without risk of shell injection, system input freeze, or silent failures
**Depends on**: Nothing (first phase)
**Requirements**: SEC-01, SEC-02, SEC-03, SEC-04, REL-01
**Success Criteria** (what must be TRUE):
  1. Note editing uses subprocess.run -- no shell injection vector exists in the codebase
  2. If Accessibility permission is revoked while running, Govori detects it and warns the user instead of freezing system input
  3. If OpenAI API hangs, transcription times out after 30s with visible feedback to the user
  4. During onboarding, user sees a clear privacy notice stating voice goes to OpenAI and notes go to Anthropic
  5. If no microphone is available or permission is denied, user sees an error message instead of a crash
**Plans:** 3 plans
Plans:
- [x] 01-01-PLAN.md -- Shell injection fix + privacy notice in onboarding
- [x] 01-02-PLAN.md -- HUD error infrastructure + API timeout with retry
- [x] 01-03-PLAN.md -- CGEventTap health monitoring + microphone error handling

### Phase 1.1: Security Hardening (Codex Review) *(INSERTED 2026-05-05)*
**Goal**: Закрыть 9 issue, найденных независимым cross-AI ревью (Codex gpt-5.5/high) реализации фазы 01-security-safety. SEC-01 признан clean; SEC-02..04 + REL-01 имели gaps между заявленными мерами и фактической реализацией.
**Depends on**: Phase 1
**Requirements**: SEC-02, SEC-03, SEC-04, REL-01 (re-verification)
**Source**: `.planning/phases/01-security-safety/01-CODEX-REVIEW.md`
**Success Criteria** (what must be TRUE):
  1. OpenAI client timeout = 30s (не хардкод 5s) и permanent API errors не идут в retry
  2. HUD click retry single-flight через lock; retry success диспатчится через оригинальный mode (note/predict/auto-send), не всегда paste
  3. Health-monitor при revoked Accessibility отменяет recording + закрывает audio_stream до показа HUD; recovery проверяет ownership перед скрытием HUD
  4. Privacy notice (en+ru) честно описывает note-mode persistence + predict/rephrase API path
  5. stop_and_transcribe не падает на race-empty audio_chunks; CLI voice amend ловит PortAudioError
  6. Повторный Codex security-review с теми же критериями: 0 находок остаются open
**Plans:** 5 plans
Plans:
- [x] 01.1-01-PLAN.md -- API timeout 30s + permanent error classification (Claude)
- [x] 01.1-02-PLAN.md -- Retry single-flight + mode-aware dispatch (Codex via codex exec)
- [x] 01.1-03-PLAN.md -- Health-monitor cancel recording + ownership tracking (Codex via codex exec)
- [x] 01.1-04-PLAN.md -- Privacy notice corrections en+ru (Claude)
- [x] 01.1-05-PLAN.md -- Empty audio_chunks guard + CLI mic error handling (Claude)

### Phase 2: Architecture & Reliability + Latency Foundations
**Goal**: Govori runs as a proper Python package with isolated modules, explicit state, structured logging, clean shutdown — and the transcribe module gains observable latency timing, an OpenAI fallback path, and a pooled HTTP client.
**Depends on**: Phase 1
**Requirements**: ARCH-01, ARCH-02, ARCH-03, REL-02, REL-03, REL-04, PERF-01, REL-05
**Background**: Spike 001 (`.planning/spikes/001-latency-benchmark/`) showed Groq p50=386ms / p95=705ms vs OpenAI p50=1476ms / p95=3416ms. Groq is already configured, so latency-from-API-swap is solved — but Groq drops ~5% requests, so a fallback is a reliability feature. The other ~1.5s of perceived pause is somewhere else (encoding / connection setup / paste) and needs measurement before Phase 4.
**Success Criteria** (what must be TRUE):
  1. govori.py is replaced by a govori/ package with separate modules (config, state, hud, audio, transcribe, notes, macos, predict, cli)
  2. No mutable module-level globals -- application state lives in an AppState dataclass with explicit transitions
  3. All output goes to ~/.config/govori/govori.log via loguru with rotation -- no print() calls remain
  4. Ctrl+C or SIGTERM triggers clean shutdown: audio stream closed, no os._exit(0)
  5. Invalid config YAML produces a human-readable error message, not a silent empty dict
  6. **PERF-01**: `stop_and_transcribe → encode → API → paste` chain is instrumented with `time.perf_counter()` and emits structured latency events to the log; running `./govori --bench-mode` (or similar) prints a final summary of per-stage timing
  7. **REL-05**: When Groq returns 5xx / timeout / connection error, transcribe module automatically retries on OpenAI (whisper-1) if `OPENAI_API_KEY` is present; user-visible log shows which provider answered
  8. Transcribe module reuses a single HTTP client per provider (keep-alive, connection pool) — no new TLS handshake per dictation
**Plans:** 2 plans
Plans:
- [ ] 02-01-PLAN.md -- Architecture extraction: govori/ package + AppState + loguru + signal handling + pydantic config validation (ARCH-01, ARCH-02, ARCH-03, REL-02, REL-03, REL-04)
- [ ] 02-02-PLAN.md -- Transcribe layer: per-provider httpx pool + Groq→OpenAI fallback + PERF-01 spans (REL-05, PERF-01)

### Phase 4: Parallel Encoding *(INSERTED 2026-05-13)*
**Goal**: Cut perceived post-release latency by ~600–1000ms by encoding audio chunks into OGG/Opus while the user is still speaking, so the moment fn is released the encoder only needs to flush the tail before the API call.
**Depends on**: Phase 2 (needs the extracted transcribe module + AppState + logging to land cleanly)
**Requirements**: PERF-02
**Source**: `.planning/spikes/001-latency-benchmark/README.md` — bench measured API latency only; perceived 2s includes encoding + connection + paste, and parallel encoding is the highest-ROI target identified.
**Success Criteria** (what must be TRUE):
  1. **PERF-02**: After fn release, end-to-end latency (release → text pasted at cursor) drops below 1000ms on p50 and below 1500ms on p95 for dictations 4–25s long, measured by the PERF-01 instrumentation from Phase 2
  2. PyAV OGG/Opus encoder runs in a background thread fed by an in-memory queue from `audio_callback`; `stop_and_transcribe` only flushes the tail and submits
  3. Cancellation, retry, and note-mode paths still work: encoder is drained or discarded correctly on cancel; retry buffer holds raw audio (not the partial encode), so retries can re-encode from scratch
  4. No regression in transcript text: same input → same text (within Groq's normal jitter) as before Phase 4 — verified by replaying the 8 bench .opus files
  5. Memory bounded: encoder queue has a sensible upper bound (e.g., 60s of audio) and degrades gracefully if exceeded
**Plans**: TBD

### Phase 3: Packaging & Distribution
**Goal**: Users can install Govori via `pipx install govori` from PyPI with confidence it works
**Depends on**: Phase 2, Phase 4
**Requirements**: DIST-01, DIST-02, DIST-03, DIST-04, DOC-01, DOC-02
**Success Criteria** (what must be TRUE):
  1. `pipx install govori` installs the tool with all dependencies and `govori` command works
  2. Smoke tests pass in CI: config loading, API error paths, note merge logic, path sanitization
  3. GitHub Actions publishes to PyPI via trusted publishers on tagged release
  4. README shows real GitHub URL, system requirements (macOS >=13, Python >=3.10), and privacy section
  5. govori.io has a privacy policy page documenting what data is sent where
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order, with decimal insertions appearing between
their surrounding integers: 1 → 1.1 → 2 → 4 → 3

(Phase 4 inserted before Phase 3 because the latency win is more impactful
than PyPI packaging, and Phase 3 doesn't depend on Phase 4 either way.)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Security & Safety | 3/3 | ✓ Done | 2026-04-22 |
| 1.1. Security Hardening (Codex Review) | 5/5 | ✓ Done | 2026-04-29 |
| 2. Architecture & Reliability + Latency Foundations | 0/2 | Next up | - |
| 4. Parallel Encoding | 0/TBD | Blocked on Phase 2 | - |
| 3. Packaging & Distribution | 0/TBD | Blocked on Phase 2, 4 | - |
