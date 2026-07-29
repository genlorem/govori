# Phase 1: Security & Safety - Context

**Gathered:** 2026-04-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix ship-blocking vulnerabilities and add safety guards for system-level APIs. Users can run Govori without risk of shell injection, system input freeze, or silent failures. No new features — hardening only.

</domain>

<decisions>
## Implementation Decisions

### Privacy Notice (SEC-04)
- **D-01:** Privacy notice is a step in onboarding (`cli_setup()`), shown once at first run, after API key entry
- **D-02:** No explicit confirmation required — displaying API keys is implicit consent. Text is informational, not blocking
- **D-03:** Content is minimal: 2-3 lines stating "Voice audio → OpenAI Whisper API, Notes → Anthropic Claude API". No opt-out instructions (that's Phase 3 docs)
- **D-04:** Text language follows the user's language choice in `cli_setup()` (en/ru), consistent with rest of onboarding. Add to `SETUP_STRINGS` dict

### Error Feedback (SEC-03, REL-01)
- **D-05:** Primary error channel is the HUD dot — changes to red on error. Tooltip with error description appears on hover
- **D-06:** For API errors (timeout, network, 5xx): HUD shows retry icon (↻). Click triggers re-transcription of the last recorded audio. Audio buffer is kept in memory until successful retry or next recording
- **D-07:** For non-retryable errors (no mic, Accessibility revoked): red HUD + tooltip with description. Click does nothing. No retry icon
- **D-08:** API timeout is 30s (per success criteria). On timeout, HUD transitions from "transcribing" to retry state

### Claude's Discretion
- Tooltip implementation approach (NSPanel expansion, NSToolTip, or custom view) — choose whatever integrates best with existing HUD NSPanel
- Retry icon visual design (↻ symbol, animation, or static)

### CGEventTap Health Monitoring (SEC-02)
- **D-09:** Daemon thread runs periodic health check (every 5-10 seconds) via `CGEventTapIsEnabled(tap)`
- **D-10:** If tap is disabled: set red HUD + tooltip "Accessibility revoked — hotkeys disabled". Attempt `CGEventTapEnable(tap, True)` to re-enable
- **D-11:** Govori continues running with tap disabled — does not exit. User can restore permission and tap auto-recovers on next health check

### Microphone Check (REL-01)
- **D-12:** Two-stage check: warning at daemon startup (non-blocking, does not exit) + red HUD when recording attempt fails
- **D-13:** Startup check: `sd.query_devices()` — if no input device, print warning to terminal but continue running. User can plug in mic later
- **D-14:** Recording check: if `sd.InputStream` fails in `start_recording()`, show red HUD + tooltip instead of silently swallowing the exception

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

No external specs — requirements fully captured in decisions above and in:

### Project Requirements
- `.planning/REQUIREMENTS.md` — SEC-01 through SEC-04, REL-01 definitions
- `.planning/ROADMAP.md` §Phase 1 — success criteria (5 items)

### Codebase Analysis
- `.planning/codebase/CONCERNS.md` §Security Considerations — shell injection detail, API key permissions
- `.planning/codebase/CONCERNS.md` §Missing Critical Features — mic permission and API timeout gaps
- `.planning/codebase/STRUCTURE.md` — file layout and where to add new code

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `set_hud(mode, icon)` (govori.py ~line 681): existing HUD state setter — extend with "error" mode and tooltip text parameter
- `SETUP_STRINGS` dict (govori.py): bilingual onboarding strings — add privacy notice entries here
- `_get_anthropic_client()` lazy init pattern: model for lazy mic check
- `audio_callback` / `audio_chunks`: already captures raw audio — buffer for retry is the existing `audio_chunks` list

### Established Patterns
- State flags as module-level globals protected by `_state_lock`
- Background work via `threading.Thread(daemon=True).start()`
- HUD updates dispatched to main queue via `NSOperationQueue.mainQueue().addOperationWithBlock_`
- Error prints use `✗` prefix: `print("✗ Error: ...", flush=True)`

### Integration Points
- `cli_setup()` line ~323: insert privacy notice step after API key entry (Step 1) and before Accessibility step (Step 2)
- `start_recording()` line ~728: replace `except Exception: pass` with specific error handling and HUD feedback
- `install_monitor()` line ~1510: after tap creation, start health-check daemon thread
- `_encode_and_transcribe()`: add `timeout=30` to OpenAI client call, wrap with retry buffer logic
- `os.system()` line 1823: replace with `subprocess.run([editor, str(path)])`

</code_context>

<specifics>
## Specific Ideas

- Retry UX: HUD icon should visually transform into a repeat/retry icon when API error occurs, making it clear the action is clickable
- Audio buffer for retry: keep last recorded audio chunks in memory, discard only when new recording starts or retry succeeds
- Health check thread: lightweight polling, same pattern as existing daemon threads in the codebase

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-security-safety*
*Context gathered: 2026-04-17*
