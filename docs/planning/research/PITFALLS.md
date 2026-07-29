# Domain Pitfalls

**Domain:** macOS Python voice dictation tool (Govori) -- alpha to market release
**Researched:** 2026-04-17

## Critical Pitfalls

Mistakes that cause system-level breakage, security incidents, or user data loss.

### Pitfall 1: CGEventTap Input Freeze on Permission Revocation

**What goes wrong:** When a user revokes Accessibility permission while Govori is running, CGEventTap does not safely release the input hook. All subsequent global input events (keyboard and mouse) are permanently swallowed. The user's entire Mac becomes unresponsive -- only a hard power-off reboot recovers it.

**Why it happens:** CGEventTap in `defaultTap` mode intercepts events before they reach the system. macOS does not gracefully notify the tap when permission is revoked -- it just stops delivering callbacks. The tap remains registered but inert, holding the event pipeline hostage.

**Consequences:** User loses all input to their Mac. This is a one-star-review, uninstall-immediately, warn-others-on-Reddit event. Deskflow (formerly Synergy) had this exact bug filed as a critical issue (deskflow/deskflow#9562).

**Prevention:**
- Implement continuous tap health monitoring: poll `tapIsEnabled()` every 5 seconds, not just at startup
- When `tapIsEnabled()` returns false, immediately remove and attempt to re-register the tap
- Before tap installation, verify `CGPreflightListenEventAccess()` returns true
- Consider using `listenOnly` mode for the fn key listener (triggers Input Monitoring permission instead of Accessibility, and avoids the input-freeze failure mode)
- Add a watchdog thread that detects tap death and exits cleanly with a user notification

**Detection:** Test by granting Accessibility, starting Govori, then revoking Accessibility in System Settings while recording. If keyboard/mouse stops working system-wide, you have this bug.

**Phase:** Security/Reliability hardening (Phase 1). This is a ship-blocker.

**Sources:**
- [Deskflow input freeze issue](https://github.com/deskflow/deskflow/issues/9562)
- [CGEventTap silent disable race](https://danielraffel.me/til/2026/02/19/cgevent-taps-and-code-signing-the-silent-disable-race/)
- [Apple Developer Forums: Accessibility permission](https://developer.apple.com/forums/thread/744440)

---

### Pitfall 2: Shell Injection via os.system in Note Editing

**What goes wrong:** Line 1823 (`os.system(f"{editor} {path}")`) passes user-controlled path content through shell expansion. A note with a crafted filename (or a `$EDITOR` env var containing injection) executes arbitrary commands.

**Why it happens:** `os.system()` invokes a shell. The `path` variable is interpolated directly into the command string with no escaping. This is a textbook shell injection.

**Consequences:** Arbitrary code execution with user privileges. If exploited through a crafted note filename (e.g., via plugin), an attacker could exfiltrate API keys from `~/.config/govori/env`.

**Prevention:**
- Replace `os.system(f"{editor} {path}")` with `subprocess.run([editor, str(path)])` -- list form bypasses shell entirely
- Never use `os.system()` anywhere in the codebase; add a linter rule to catch it
- Validate/sanitize all file paths before use

**Detection:** Grep for `os.system` -- currently only one instance at line 1823, but audit any future additions.

**Phase:** Security hardening (Phase 1). Fix before any public release.

---

### Pitfall 3: No Privacy Disclosure for Cloud Audio Transmission

**What goes wrong:** Govori sends raw voice audio to OpenAI servers (and note text to Anthropic) with no user-visible disclosure. Voice recordings contain biometric voiceprints that, unlike passwords, cannot be changed after a breach.

**Why it happens:** Developer familiarity blindness -- the dev knows audio goes to OpenAI, but users expect local processing, especially on Apple Silicon Macs where Apple's own dictation is on-device.

**Consequences:** Trust destruction when users discover undisclosed cloud transmission. Potential legal exposure under GDPR/CCPA (voice data is biometric). Competitor tools like MacWhisper and Superwhisper prominently advertise "local mode" as a selling point -- Govori will look deceptive by comparison.

**Prevention:**
- Display a clear, one-time privacy notice during onboarding (Step 1, alongside API key setup) stating: "Your voice audio is sent to OpenAI for transcription. Notes are processed by Anthropic Claude."
- Add a `--privacy` flag that prints the full data flow
- Include a PRIVACY.md in the repo and link from govori.io
- Consider adding a local Whisper mode as a future differentiator (out of scope for hardening, but worth noting on the roadmap)

**Detection:** Run onboarding flow as a new user. If you can start dictating without ever seeing the word "cloud" or "OpenAI," this pitfall is active.

**Phase:** Onboarding/UX hardening (Phase 1). Non-negotiable for public release.

**Sources:**
- [Voibe: Offline Dictation Privacy](https://www.getvoibe.com/resources/offline-dictation-privacy-mac/)
- [Apple Community: Privacy Concerns with Dictation](https://discussions.apple.com/thread/4419293)

---

### Pitfall 4: Silent CGEventTap Death After Code Re-signing

**What goes wrong:** After updating the app (which re-signs the binary), CGEventTap appears functional -- returns non-nil, `tapIsEnabled()` reports true -- but callbacks never fire. The hotkey silently stops working with no error message.

**Why it happens:** macOS TCC (Transparency, Consent, and Control) ties permission decisions to code identity. Re-signing creates a "new" identity that requires re-evaluation. Launch Services triggers stricter identity checks than direct binary execution.

**Consequences:** After every update, some percentage of users report "it just stopped working." Support burden is enormous because the failure is invisible -- no crash, no error, no log entry.

**Prevention:**
- Implement startup self-test: after tap installation, inject a synthetic event and verify the callback fires within 500ms
- If self-test fails, show a clear message: "Govori needs Accessibility permission re-granted after update. Open System Settings?"
- Log tap health status on every recording attempt
- Document in release notes that updates may require re-granting Accessibility

**Detection:** Update the binary, re-sign it, launch via Finder. Try recording. If fn key does nothing with no error, you have this bug.

**Phase:** Distribution/update mechanism (Phase 2-3). Becomes critical once you have an update pipeline.

**Sources:**
- [CGEventTap and Code Signing: The Silent Disable Race](https://danielraffel.me/til/2026/02/19/cgevent-taps-and-code-signing-the-silent-disable-race/)

---

## Moderate Pitfalls

### Pitfall 5: Clipboard Race Condition on Fast Paste

**What goes wrong:** `paste_text()` saves clipboard, writes new text, simulates Cmd+V, waits 150ms, then restores. If the user pastes (Cmd+V) within that 150ms window, or if the target app is slow to process the paste event, either the wrong text is pasted or the clipboard restoration clobbers the intended paste.

**Why it happens:** The clipboard is a shared global resource. 150ms is an arbitrary delay that works on fast apps but fails on Electron apps (Slack, VS Code, Discord) which have higher input latency.

**Prevention:**
- Increase restore delay to 300-500ms (pragmatic)
- Use a clipboard change listener (NSPasteboard changeCount) to detect when the paste has been consumed before restoring
- Add a user-configurable `paste_delay` in config.yaml for users with slow target apps
- Consider using `NSPasteboard` private pasteboard as intermediary instead of clobbering generalPasteboard

**Detection:** Rapidly dictate and paste into an Electron app. If clipboard content is wrong or previous clipboard is lost, the race exists.

**Phase:** Reliability hardening (Phase 1).

---

### Pitfall 6: Microphone Unavailable Crash

**What goes wrong:** `sounddevice.InputStream` throws an uncaught exception if no microphone is available, the default device changes mid-recording, or the microphone is in use by another app with exclusive access.

**Why it happens:** No try/except around audio device initialization. No pre-check for available input devices. No handling of device-disconnected mid-stream.

**Consequences:** Unhandled exception crashes the entire app. User sees a Python traceback -- looks like broken software.

**Prevention:**
- Wrap `sd.InputStream()` creation and `stream.start()` in try/except with user-friendly error messages via HUD
- Before recording, check `sd.query_devices(kind='input')` returns a valid device
- Handle `sd.PortAudioError` specifically (the actual exception type from sounddevice)
- Register a device-change callback to gracefully handle mid-session audio routing changes

**Detection:** Disconnect all microphones, try to record. If you see a traceback instead of a HUD error indicator, this is active.

**Phase:** Reliability hardening (Phase 1).

---

### Pitfall 7: API Timeout Hangs the App

**What goes wrong:** OpenAI Whisper API calls have no timeout set. If OpenAI is slow or down, the recording thread blocks indefinitely. The user sees the HUD stuck on "transcribing" with no way to cancel or recover.

**Why it happens:** The `openai` Python client defaults to no timeout (or very long timeout). No retry logic means transient failures are permanent until restart.

**Consequences:** App appears frozen. User force-quits. If this happens on first use, user never comes back.

**Prevention:**
- Set explicit `timeout=30` on the OpenAI client: `OpenAI(timeout=30)`
- Implement retry with exponential backoff (max 2 retries) for 5xx and timeout errors
- Show HUD error state (red X) after timeout, not infinite spinner
- Same treatment for Anthropic API calls in note classification

**Detection:** Simulate slow API with a proxy or by temporarily pointing to a non-routable IP. If HUD stays yellow forever, this is active.

**Phase:** Reliability hardening (Phase 1).

---

### Pitfall 8: Unpinned Dependencies Break on Fresh Install

**What goes wrong:** `requirements.txt` has no version pins (`openai`, `anthropic`, `av`, etc.). A breaking change in any dependency causes installation failures or runtime errors for new users.

**Why it happens:** During development, the dev's virtualenv has working versions locked by accident. But a fresh `pip install -r requirements.txt` pulls latest, which may be incompatible.

**Consequences:** New user runs install, gets import errors or behavioral changes. PyObjC is especially dangerous here -- major version bumps can break Cocoa bridge APIs. PyAV has historically had installation issues across Python versions (PyAV-Org/PyAV#820).

**Prevention:**
- Pin all dependencies with exact versions in `requirements.txt` (or migrate to `pyproject.toml` with version ranges)
- Use `pip freeze > requirements-lock.txt` from the working venv as a lockfile
- Test installation in a clean venv on every release
- Consider using `uv` for reproducible installs (recommended for Python on macOS in 2026)

**Detection:** Create a fresh venv, install from requirements.txt, run the app. If it fails, pins are needed.

**Phase:** Distribution hardening (Phase 1).

**Sources:**
- [PyAV installation issues](https://github.com/PyAV-Org/PyAV/issues/820)
- [PyObjC installation docs](https://pyobjc.readthedocs.io/en/latest/install.html)

---

### Pitfall 9: Hardcoded Model IDs Deprecate Without Warning

**What goes wrong:** `whisper-1` and `claude-haiku-4-5-20251001` are hardcoded as defaults. When OpenAI or Anthropic deprecate these model IDs, the app breaks for all users simultaneously.

**Why it happens:** Model IDs feel permanent but are not. OpenAI has deprecated and removed model snapshots on fixed timelines (e.g., Realtime API Beta sunset May 7, 2026). While `whisper-1` has no announced deprecation as of April 2026, `gpt-4o-transcribe` is the newer recommended model.

**Consequences:** All users hit API errors at the same time. Requires emergency release.

**Prevention:**
- Make model IDs configurable via `config.yaml` (already partially done, but defaults need to be updateable)
- Detect `model_not_found` API errors and fall back gracefully with a user message: "Model X was retired. Update your config to use Y."
- Log the model ID used on every transcription so users can diagnose issues
- Track OpenAI's deprecation page: https://developers.openai.com/api/docs/deprecations

**Detection:** Change the model ID to a known-invalid value. If the error message is a raw API exception instead of a helpful message, this needs fixing.

**Phase:** Reliability hardening (Phase 1-2).

**Sources:**
- [OpenAI Deprecations](https://developers.openai.com/api/docs/deprecations)

---

### Pitfall 10: No Logging Makes Support Impossible

**What goes wrong:** All output goes to stdout via `print()`. When a user reports "it doesn't work," there is no way to diagnose the problem. No log file, no structured output, no error context.

**Why it happens:** `print()` debugging during development that never got replaced with proper logging.

**Consequences:** Every support interaction becomes "can you run it in terminal and paste the output?" Most non-technical users cannot do this. Impossible to diagnose intermittent issues.

**Prevention:**
- Replace all `print()` calls with Python `logging` module
- Log to `~/.config/govori/logs/govori.log` with rotation (max 5MB, 3 files)
- Include timestamps, log levels, and context (which mode, which model, duration)
- Add a `--debug` flag that sets log level to DEBUG and also prints to stdout
- Log every API call duration and response status

**Detection:** Search codebase for `print(` -- if it returns more than 0 results outside of onboarding prompts, logging is incomplete.

**Phase:** Reliability hardening (Phase 1).

---

## Minor Pitfalls

### Pitfall 11: Python Version Fragmentation on macOS

**What goes wrong:** Users have system Python 2.7 (legacy), Homebrew Python 3.x, pyenv Python, conda Python, and now the Apple Developer Command Line Tools Python. Running `pip install` or `python3 govori.py` may use the wrong interpreter, especially if user has multiple Python installations.

**Prevention:**
- Require Python 3.10+ explicitly (PyObjC wheels are available for 3.10+)
- Add a version check at the top of `govori.py` that exits with a clear message
- Distribute with `pyproject.toml` and recommend `pipx install govori` or `uv tool install govori` for isolation
- In 2026, `uv` is the recommended Python environment manager on macOS -- document it as the install path

**Phase:** Distribution (Phase 2).

**Sources:**
- [Using Python on Apple Silicon Macs in 2026](https://www.invisiblefriends.net/using-python-on-apple-silicon-macs-in-2026/)

---

### Pitfall 12: Single-File Architecture Blocks Testability

**What goes wrong:** At 1900 lines in a single file, testing individual components (audio capture, API calls, clipboard management, HUD communication) requires importing the entire app, which triggers global side effects (config loading, CGEventTap registration).

**Prevention:**
- Extract core logic into importable modules before writing tests: `audio.py`, `transcribe.py`, `clipboard.py`, `config.py`, `hud.py`
- Guard global side effects behind `if __name__ == "__main__":`
- Do NOT attempt a full refactor before hardening -- just extract the pieces you need to test

**Phase:** Testing foundation (Phase 1, minimal extraction only).

---

### Pitfall 13: Graceful Shutdown Missing

**What goes wrong:** Current signal handler is `signal.signal(signal.SIGINT, lambda *_: os._exit(0))`. `os._exit()` skips all cleanup -- open audio streams, registered event taps, temporary files. If the audio stream is mid-recording, PortAudio may leave the device in a bad state.

**Prevention:**
- Replace `os._exit(0)` with a proper shutdown sequence: stop audio stream, remove event tap, clean temp files, then `sys.exit(0)`
- Handle both SIGINT and SIGTERM
- Add an `atexit` handler as a safety net

**Phase:** Reliability hardening (Phase 1).

---

### Pitfall 14: Hammerspoon HUD Dependency

**What goes wrong:** The HUD relies on Hammerspoon (extras/hud/status_hud.lua). Users must install and configure Hammerspoon separately. If Hammerspoon is not running, HUD commands fail silently -- user gets no visual feedback during recording.

**Prevention:**
- Detect Hammerspoon availability at startup; warn if missing
- Consider a fallback HUD using native macOS notification center or a minimal PyObjC NSStatusItem
- Document Hammerspoon setup clearly in onboarding (currently not part of the 3-step setup)

**Phase:** UX polish (Phase 2-3).

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Security hardening | Shell injection feels minor but is a CVE-level issue | Fix os.system before any public link is shared |
| Permission handling | CGEventTap freeze can brick user's input | Test permission revocation scenario on every macOS version you support |
| API reliability | Silent failures (no timeout, no retry) are the #1 cause of "app is broken" reports | Set timeouts on every external call, show errors via HUD |
| Distribution | PyObjC + PyAV installation matrix is complex | Test clean install on Intel and Apple Silicon, Python 3.10/3.11/3.12/3.13/3.14 |
| Privacy compliance | Competitors advertise local-first; cloud-only without disclosure looks deceptive | Privacy notice in onboarding is a hard requirement |
| Updates | Code re-signing invalidates CGEventTap permissions | Build self-test into startup, guide user through re-grant |
| Single-file arch | Cannot test individual components, cannot onboard contributors | Extract minimally for testability, do not over-architect |

## Sources

- [Deskflow input freeze (CGEventTap)](https://github.com/deskflow/deskflow/issues/9562)
- [CGEventTap code signing race](https://danielraffel.me/til/2026/02/19/cgevent-taps-and-code-signing-the-silent-disable-race/)
- [Apple Developer Forums: Accessibility permission detection](https://developer.apple.com/forums/thread/744440)
- [macOS Sequoia CGEventTap permission issues](https://developer.apple.com/forums/thread/758554)
- [OpenAI API Deprecations](https://developers.openai.com/api/docs/deprecations)
- [PyAV installation issues](https://github.com/PyAV-Org/PyAV/issues/820)
- [PyObjC installation docs](https://pyobjc.readthedocs.io/en/latest/install.html)
- [Voibe: Offline Dictation Privacy on Mac](https://www.getvoibe.com/resources/offline-dictation-privacy-mac/)
- [Python on Apple Silicon Macs 2026](https://www.invisiblefriends.net/using-python-on-apple-silicon-macs-in-2026/)
- [macOS TCC system overview](https://jetforme.org/2023/12/transparency-consent-control/)
