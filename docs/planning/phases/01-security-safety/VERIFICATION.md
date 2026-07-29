---
phase: 01-security-safety
verified: 2026-04-18T00:00:00Z
status: human_needed
score: 5/5 must-haves verified (static) -- live behavior awaits human checkpoint
overrides_applied: 0
re_verification:
  previous_status: null
  previous_score: null
  gaps_closed: []
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Run ./govori setup with ~/.config/govori/.setup_done removed"
    expected: "Step headers show X/4, privacy notice appears between API keys and Accessibility mentioning OpenAI Whisper + Anthropic Claude, no confirmation prompt -- flow auto-continues to Accessibility"
    why_human: "Onboarding is an interactive terminal flow; visual/step rendering and flow continuity can only be confirmed by executing it live"
  - test: "Run govori with base_url set to https://192.0.2.1 in config.yaml, hold fn and speak, release"
    expected: "Within ~30s HUD transitions to yellow recycling arrow with 'Transcription timed out. Click to retry.' tooltip. Clicking triggers transcribing state then returns to retry. After 3 failed clicks HUD goes red with 'Transcription failed' tooltip"
    why_human: "Tests live OpenAI timeout behavior, NSPanel rendering, NSClickGestureRecognizer hit testing, CABasicAnimation pulse visibility -- cannot be verified by static code inspection"
  - test: "While govori is running, revoke Accessibility for the launching terminal in System Settings, wait ~10s, then re-grant"
    expected: "HUD turns red with 'Accessibility revoked' tooltip within ~7s, terminal prints warning. On re-grant, HUD clears and terminal prints 'Accessibility restored.'"
    why_human: "Only macOS System Settings can flip the permission bit; 7s polling cadence and re-enable attempt must be observed in real time"
  - test: "Start govori with no input device available (disable/unplug mic before launch)"
    expected: "Terminal prints '! No microphone detected. Plug one in before recording.' and govori continues running (no exit). Holding fn should produce red HUD + tooltip (no_mic or mic_denied)"
    why_human: "Requires physically toggling mic availability; verifies non-exit behavior plus PortAudioError handling branch in start_recording()"
  - test: "Run ./govori setup and at privacy notice step confirm Russian translation renders correctly when lang=ru selected"
    expected: "Step 2/4 header in Russian, all Russian text strings render with correct Cyrillic characters, no mojibake"
    why_human: "Terminal-dependent Unicode rendering can vary; manual inspection confirms user sees correct copy"
---

# Phase 1: Security & Safety — Verification Report

**Phase Goal:** Users can run Govori without risk of shell injection, system input freeze, or silent failures
**Verified:** 2026-04-18T00:00:00Z (static analysis); live behavior awaiting human checkpoint (Plan 03 Task 3)
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth (ROADMAP SC) | Status | Evidence |
|---|-------|--------|----------|
| 1 | Note editing uses subprocess.run — no shell injection vector exists in the codebase | VERIFIED (static) | `govori.py:2160` `subprocess.run([editor, str(path)])`; `govori.py:22` `import subprocess`; grep confirms zero `os.system` matches; commit `14dce2b` |
| 2 | If Accessibility permission is revoked while running, Govori detects it and warns the user instead of freezing system input | VERIFIED (static) — runtime needs human | `govori.py:1836-1865` `_tap_health_check(tap)` daemon thread polls every 7s, calls `CGEventTapIsEnabled`, attempts `CGEventTapEnable(tap, True)`, shows `error_fatal` HUD + `accessibility_revoked` tooltip, clears on recovery; wired in `__main__` at 2309-2310; commit `e3512a8` |
| 3 | If OpenAI API hangs, transcription times out after 30s with visible feedback to the user | VERIFIED (static) — runtime needs human | `govori.py:655-659` OpenAI client constructed with `timeout=30.0, max_retries=0` in both branches; `govori.py:1053-1064` catches `APITimeoutError`, `APIConnectionError`, `APIStatusError`; `govori.py:1152-1158` writes `_retry_buffer` and shows `error_retryable` HUD; commits `ced0833`, `26bfc3d` |
| 4 | During onboarding, user sees a clear privacy notice stating voice goes to OpenAI and notes go to Anthropic | VERIFIED (static) | `govori.py:199-210` (en) and `276-287` (ru) `step_privacy` strings mention "OpenAI Whisper API (speech-to-text)" and "Anthropic Claude API (classification)"; `govori.py:432` `print(s["step_privacy"])` placed between `keys_saved` (429) and `step_access` (443); step headers renumbered to X/4 across both languages (189, 200, 212, 222, 266, 277, 289, 299); commit `403159c` |
| 5 | If no microphone is available or permission is denied, user sees an error message instead of a crash | VERIFIED (static) — runtime needs human | `govori.py:2312-2316` startup check `sd.query_devices(kind='input')` wrapped in `except sd.PortAudioError` prints warning without exit; `govori.py:991-1006` `start_recording()` catches `sd.PortAudioError`, resets `recording=False`, shows `error_fatal` HUD with `mic_denied` or `no_mic` tooltip; commit `a6f7941` |

**Score:** 5/5 truths verified by static analysis. Runtime behavior for truths 2, 3, 5 requires the human verification checkpoint defined in Plan 03 Task 3 (status: checkpoint-pending in 01-03-SUMMARY.md).

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `govori.py` (SEC-01 shell injection fix) | `subprocess.run([editor, str(path)])` replaces `os.system` | VERIFIED | Line 2160; zero `os.system` matches; `import subprocess` at line 22 |
| `govori.py` (SEC-04 privacy strings) | `step_privacy` keys in both `en` and `ru` SETUP_STRINGS | VERIFIED | Lines 199-210 (en), 276-287 (ru); mentions OpenAI Whisper and Anthropic Claude |
| `govori.py` (SEC-04 step renumber) | Zero `Step X/3` / `Шаг X/3`, 8+ `X/4` | VERIFIED | 8 `X/4` headers (4 en + 4 ru); 0 `X/3` residue |
| `govori.py` (SEC-04 wiring) | `print(s["step_privacy"])` between keys_saved and step_access | VERIFIED | Line 432, between line 429 (keys_saved) and 443 (step_access) |
| `govori.py` (SEC-03 timeout) | `OpenAI(..., timeout=30.0, max_retries=0)` | VERIFIED | Lines 656 and 658 (both branches) |
| `govori.py` (SEC-03 exceptions) | `openai.APITimeoutError`, `APIConnectionError`, `APIStatusError` catches | VERIFIED | Lines 1053, 1056, 1059 inside `_encode_and_transcribe` |
| `govori.py` (SEC-03 HUD infra) | `TOOLTIP_STRINGS`, `error_retryable`, `error_fatal`, `HUDClickHandler`, `_setup_tooltip`, `_show_tooltip`, `_hide_tooltip`, `_retry_buffer`, `_retry_count`, `_retry_transcription` | VERIFIED | All present: 339, 909/929, 822, 771, 804, 815, 688/689, 838 |
| `govori.py` (SEC-03 click wiring) | `NSClickGestureRecognizer` on `hud_window.contentView()` targeting `handleClick:` | VERIFIED | Lines 862-869 `_setup_hud_click()`, called from `setup_hud()` at line 763 |
| `govori.py` (SEC-02 health check) | `_tap_health_check(tap)` with `CGEventTapIsEnabled`/`CGEventTapEnable(tap, True)` loop, sleeps 7s | VERIFIED | Lines 1836-1865 |
| `govori.py` (SEC-02 wiring) | `tap = install_monitor()` + `threading.Thread(target=_tap_health_check, args=(tap,), daemon=True).start()` | VERIFIED | Lines 2309-2310; `install_monitor()` ends with `return tap` at 1833 |
| `govori.py` (REL-01 startup) | `sd.query_devices(kind='input')` wrapped in `except sd.PortAudioError` | VERIFIED | Lines 2312-2316, non-blocking warning only (no `sys.exit`, no `set_hud`) |
| `govori.py` (REL-01 recording) | `sd.PortAudioError` catch in `start_recording()` showing `error_fatal` HUD | VERIFIED | Lines 996-1006; resets `recording=False`, `audio_stream=None`; differentiates `mic_denied` vs `no_mic` via error string |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `govori.py cli_setup()` | `SETUP_STRINGS[lang]['step_privacy']` | `print(s["step_privacy"])` between keys saved and Accessibility | WIRED | Line 432, placement matches plan |
| `govori.py _encode_and_transcribe()` | `set_hud()` error_retryable | Returns `None` on API error; `stop_and_transcribe()` (1152) and `_note_pipeline_background()` (1079) transition HUD | WIRED | Caller writes `_retry_buffer`, calls `set_hud(..., mode="error_retryable", tooltip=_tooltip("api_timeout"))` |
| `HUDClickHandler.handleClick_()` | `_encode_and_transcribe()` | Daemon thread calls `_retry_transcription()` which concatenates `_retry_buffer` and calls transcribe | WIRED | Lines 823-835 → 838-859; `_retry_count > 3` gating shows `retry_exhausted` fatal |
| `OpenAI()` constructor | `timeout=30.0, max_retries=0` | Client initialization | WIRED | Both branches at 656/658 |
| `_tap_health_check()` | `set_hud()` error_fatal | Calls `set_hud(True, mode="error_fatal", tooltip=_tooltip("accessibility_revoked"))` when tap disabled; `set_hud(False)` on recovery | WIRED | Lines 1852, 1863 |
| `install_monitor()` | `_tap_health_check()` | `install_monitor()` returns tap; `__main__` captures and launches daemon thread | WIRED | Lines 1833, 2309-2310 |
| `start_recording()` | `set_hud()` error_fatal | Catches `sd.PortAudioError`, routes to `no_mic`/`mic_denied` tooltip | WIRED | Lines 996-1005 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| Privacy notice print | `s["step_privacy"]` | `SETUP_STRINGS[lang]` literal strings (en lines 199-210, ru 276-287) | Yes — real text mentioning both services | FLOWING |
| HUD error tooltip text | `_tooltip(key)` | `TOOLTIP_STRINGS[lang][key]` | Yes — bilingual strings at lines 340-359 | FLOWING |
| Retry transcription | `_retry_buffer` | Written in `stop_and_transcribe` (1156) and `_note_pipeline_background` (1081); cleared only in `_retry_transcription` on success (856) | Yes — real `audio_chunks`/concatenated array | FLOWING |
| Health check enabled state | `Quartz.CGEventTapIsEnabled(tap)` | Direct OS API query on tap returned by `install_monitor()` | Yes — real macOS permission state | FLOWING |
| Mic startup warning | `sd.query_devices(kind='input')` | PortAudio query — raises `PortAudioError` when no default input exists | Yes — real hardware state | FLOWING |

No hollow props, no hardcoded empty values in the error pipelines.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| No `os.system` remains | `grep -c "os\.system" govori.py` | 0 | PASS |
| `subprocess.run` editor call present | `grep "subprocess.run(\[editor" govori.py` | 1 match (line 2160) | PASS |
| Privacy key defined twice | `grep -c '"step_privacy"' govori.py` | 2 (en + ru dict entries) + 1 print call | PASS |
| No legacy X/3 step headers | `grep -E "Step \d/3\|Шаг \d/3" govori.py` | 0 matches | PASS |
| 8+ X/4 headers across languages | `grep -c "Step \|Шаг " + "/4"` | 8 | PASS |
| `timeout=30.0` in OpenAI init | `grep -c "timeout=30.0" govori.py` | 2 (both branches) | PASS |
| `max_retries=0` in OpenAI init | `grep -c "max_retries=0" govori.py` | 2 | PASS |
| Specific openai exception catches | `grep -cE "openai\.(APITimeoutError\|APIConnectionError\|APIStatusError)" govori.py` | 3 | PASS |
| `HUDClickHandler` class defined | `grep -c "class HUDClickHandler" govori.py` | 1 (line 822) | PASS |
| `_tap_health_check` thread wired in `__main__` | `grep "threading.Thread(target=_tap_health_check"` | 1 match (line 2310) | PASS |
| `install_monitor()` returns tap | `grep -n "return tap" govori.py` | 1 (line 1833) | PASS |
| Startup mic check present | `grep "query_devices(kind=" govori.py` | 1 (line 2314) | PASS |
| `PortAudioError` caught in `start_recording()` | regex scope check inside function | present (line 996) | PASS |
| Python syntax valid | `python3 -c "import ast; ast.parse(open('govori.py').read())"` | OK | PASS |
| All 6 referenced commits exist | `git log --oneline 14dce2b 403159c 26bfc3d ced0833 e3512a8 a6f7941` | All six resolve | PASS |

Cannot run live server-style spot-checks (no mic toggle, no OpenAI timeout simulation, no Accessibility revoke) — these are captured in Human Verification section.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SEC-01 | 01-01-PLAN | Shell injection eliminated | SATISFIED | `subprocess.run([editor, str(path)])` at `govori.py:2160`; zero `os.system` residue; commit `14dce2b` |
| SEC-02 | 01-03-PLAN | CGEventTap health monitor | SATISFIED (static) | `_tap_health_check` daemon thread at `govori.py:1836-1865`, wired in `__main__` at 2310; runtime recovery behavior awaits human test |
| SEC-03 | 01-02-PLAN | API timeout + user-visible feedback on hang | SATISFIED (static) | `timeout=30.0, max_retries=0` at `govori.py:655-659`; specific exception catches at 1053-1064; retry HUD wired at 1152-1158 and 1079-1084 |
| SEC-04 | 01-01-PLAN | Privacy notice during onboarding | SATISFIED | Bilingual privacy notice at `govori.py:199-210, 276-287`; printed between keys and access at line 432; step renumbering complete |
| REL-01 | 01-03-PLAN | Microphone error handling | SATISFIED (static) | Startup check at `govori.py:2312-2316`; recording-time catch at 991-1006; fatal HUD with bilingual tooltip |

No orphaned requirements — all 5 Phase 1 requirements from REQUIREMENTS.md map to plans and all plans claim and deliver them.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `govori.py` | 2318 | `signal.signal(signal.SIGINT, lambda *_: os._exit(0))` | Info | Pre-existing (not Phase 1 scope); tracked for Phase 2 REL-03 "Graceful shutdown" |
| `govori.py` | 1823-1825 | Hard `sys.exit(1)` when initial CGEventTap creation fails | Info | Reasonable for startup (no tap ever created); runtime revocation is handled by health check. Not a Phase 1 gap. |
| `govori.py` | 983 | Broad `except Exception: pass` around audio_stream cleanup at start_recording | Info | Acceptable per plan (cleanup of previous stream, not the new one). Matches plan guidance in 01-03-PLAN Task 2 step 3. |
| `govori.py` | 1836-1865 | `_tap_health_check` clears HUD immediately on first re-enabled cycle rather than requiring two consecutive stable checks (Pitfall 2 in RESEARCH.md) | Warning | ROADMAP SC does not require multi-cycle stability check — just detection + warning. Behavior still satisfies SC. Note for future hardening. |

No blockers found.

### Human Verification Required

The following items cannot be verified by static analysis — they require running govori live. This matches Plan 03 Task 3 (`checkpoint:human-verify`), which is still outstanding (01-03-SUMMARY.md status: `checkpoint-pending`).

1. **Onboarding privacy flow**
   - **Test:** `rm ~/.config/govori/.setup_done && ./govori setup`
   - **Expected:** Step headers show X/4, privacy notice appears between API keys and Accessibility mentioning OpenAI Whisper + Anthropic Claude, no confirmation prompt — flow auto-continues to Accessibility step.
   - **Why human:** Interactive terminal flow; visual step rendering and flow continuity.

2. **API timeout + retry HUD**
   - **Test:** Set `base_url: "https://192.0.2.1"` in `~/.config/govori/config.yaml`; start govori; hold fn, speak, release.
   - **Expected:** Within ~30s HUD shows yellow ↻ with "Transcription timed out. Click to retry." tooltip. Clicking triggers transcribe state, then returns to retryable. After 3 failed clicks HUD turns red with "Transcription failed" message.
   - **Why human:** Live OpenAI timeout, NSPanel rendering, click gesture recognizer, CABasicAnimation — all runtime-only behaviors.

3. **Accessibility revoke & recover**
   - **Test:** With govori running, revoke Accessibility for the launching terminal in System Settings → Privacy & Security → Accessibility; wait ~10s; re-grant.
   - **Expected:** HUD turns red with "Accessibility revoked — hotkeys disabled." tooltip within ~7s, terminal prints warning. On re-grant, HUD clears, terminal prints "Accessibility restored."
   - **Why human:** macOS permission toggling requires manual System Settings interaction; 7s polling cadence must be observed.

4. **No-mic startup & recording-time error**
   - **Test:** Unplug/disable input device; start govori; hold fn.
   - **Expected:** Terminal prints "! No microphone detected. Plug one in before recording." and govori stays running. Holding fn produces red ✗ HUD with `no_mic` or `mic_denied` tooltip; govori does not crash.
   - **Why human:** Requires physical mic toggle; verifies non-exit behavior and PortAudioError branch.

5. **Russian locale rendering**
   - **Test:** Run setup with `ru` selected at language prompt.
   - **Expected:** Cyrillic text in privacy notice renders correctly without mojibake; tooltip strings render in Russian during error states.
   - **Why human:** Terminal Unicode rendering varies by environment.

### Gaps Summary

No static gaps. Every ROADMAP success criterion has corresponding code that matches plan specifications, every referenced commit exists, and the Python syntax is valid.

The phase status is `human_needed` because:
- Plan 03 Task 3 is an explicit `checkpoint:human-verify` gate (blocking) that has not been performed (`01-03-SUMMARY.md` marks status `checkpoint-pending` and `completed: pending checkpoint`).
- Truths 2, 3, and 5 involve runtime hardware/permission/network behavior that cannot be confirmed by code inspection alone.

Once the human checkpoint passes, this phase can flip to `passed`.

---

*Verified: 2026-04-18*
*Verifier: Claude (gsd-verifier)*
