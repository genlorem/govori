# Phase 1: Security & Safety - Research

**Researched:** 2026-04-17
**Domain:** Python security hardening, macOS native API safety, OpenAI SDK timeout configuration
**Confidence:** HIGH

## Summary

Phase 1 is a hardening-only phase for an existing single-file macOS Python application (govori.py, ~1912 lines). All five requirements address concrete, well-understood problems: shell injection via `os.system()`, CGEventTap health monitoring, OpenAI API timeout, privacy notice in CLI onboarding, and microphone error handling. No new features, no new dependencies, no architectural changes.

The codebase is well-mapped: exact line numbers for each change are documented in CONTEXT.md and CONCERNS.md. The implementation surface is narrow -- roughly 6 functions need modification, 1 new daemon thread, 1 new NSPanel (tooltip), and new entries in the existing `SETUP_STRINGS` dict. The UI-SPEC is already approved with pixel-exact specifications for HUD error states and tooltip behavior.

**Primary recommendation:** Implement changes in dependency order: SEC-01 (trivial one-liner) first, then SEC-04 (isolated onboarding change), then SEC-02 + SEC-03 + REL-01 together (they share the HUD error infrastructure).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Privacy notice is a step in onboarding (`cli_setup()`), shown once at first run, after API key entry
- **D-02:** No explicit confirmation required -- displaying API keys is implicit consent. Text is informational, not blocking
- **D-03:** Content is minimal: 2-3 lines stating "Voice audio -> OpenAI Whisper API, Notes -> Anthropic Claude API". No opt-out instructions (that's Phase 3 docs)
- **D-04:** Text language follows the user's language choice in `cli_setup()` (en/ru), consistent with rest of onboarding. Add to `SETUP_STRINGS` dict
- **D-05:** Primary error channel is the HUD dot -- changes to red on error. Tooltip with error description appears on hover
- **D-06:** For API errors (timeout, network, 5xx): HUD shows retry icon (upward-curling arrow). Click triggers re-transcription of the last recorded audio. Audio buffer is kept in memory until successful retry or next recording
- **D-07:** For non-retryable errors (no mic, Accessibility revoked): red HUD + tooltip with description. Click does nothing. No retry icon
- **D-08:** API timeout is 30s (per success criteria). On timeout, HUD transitions from "transcribing" to retry state
- **D-09:** Daemon thread runs periodic health check (every 5-10 seconds) via `CGEventTapIsEnabled(tap)`
- **D-10:** If tap is disabled: set red HUD + tooltip "Accessibility revoked -- hotkeys disabled". Attempt `CGEventTapEnable(tap, True)` to re-enable
- **D-11:** Govori continues running with tap disabled -- does not exit. User can restore permission and tap auto-recovers on next health check
- **D-12:** Two-stage check: warning at daemon startup (non-blocking, does not exit) + red HUD when recording attempt fails
- **D-13:** Startup check: `sd.query_devices()` -- if no input device, print warning to terminal but continue running. User can plug in mic later
- **D-14:** Recording check: if `sd.InputStream` fails in `start_recording()`, show red HUD + tooltip instead of silently swallowing the exception

### Claude's Discretion
- Tooltip implementation approach (NSPanel expansion, NSToolTip, or custom view) -- choose whatever integrates best with existing HUD NSPanel
- Retry icon visual design (upward-curling arrow symbol, animation, or static)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEC-01 | Shell injection fix -- os.system replaced with subprocess.run | Trivial stdlib change, line 1823 identified, `subprocess.run([editor, str(path)])` is the standard fix |
| SEC-02 | CGEventTap health monitoring -- detect revoked Accessibility | `Quartz.CGEventTapIsEnabled(tap)` and `Quartz.CGEventTapEnable(tap, True)` verified available in pyobjc-framework-Quartz 12.1 |
| SEC-03 | API timeout 30s with visible feedback | OpenAI Python SDK `timeout=30.0` constructor param verified via Context7; raises `APITimeoutError` |
| SEC-04 | Privacy notice during onboarding | Pure string addition to existing `SETUP_STRINGS` dict, exact copy provided in UI-SPEC |
| REL-01 | Microphone error handling | `sounddevice.PortAudioError` is the exception class; `sd.query_devices(kind='input')` for startup check |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Shell injection fix (SEC-01) | Application (Python stdlib) | -- | Replace `os.system` with `subprocess.run` -- pure Python change |
| CGEventTap health (SEC-02) | macOS native (Quartz) | Application (daemon thread) | Quartz API owns the tap state; Python thread polls it |
| API timeout (SEC-03) | API client (OpenAI SDK) | HUD (AppKit) | SDK handles timeout; HUD shows error/retry state |
| Privacy notice (SEC-04) | CLI (terminal) | -- | Pure print output in `cli_setup()` |
| Mic error handling (REL-01) | Audio (sounddevice) | HUD (AppKit) | sounddevice raises the error; HUD shows feedback |
| HUD error modes (shared) | macOS native (AppKit/Quartz) | -- | New NSPanel tooltip + modified `set_hud()` |

## Standard Stack

### Core (already installed -- no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| openai | 2.30.0 (installed) | Whisper transcription with timeout | Already in use; `timeout` param is built-in [VERIFIED: Context7 /openai/openai-python] |
| pyobjc-framework-Quartz | 12.1 (installed) | CGEventTap health check APIs | Already in use; `CGEventTapIsEnabled` confirmed available [VERIFIED: runtime import check] |
| pyobjc-framework-Cocoa | 12.1 (installed) | NSPanel tooltip, mouse events | Already in use for HUD [VERIFIED: runtime import check] |
| sounddevice | 0.5.5 (installed) | Mic detection and error classes | Already in use; `PortAudioError` and `query_devices(kind='input')` verified [VERIFIED: runtime import check] |
| subprocess (stdlib) | Python 3.14 | Safe process execution | stdlib, replaces `os.system` [VERIFIED: Python stdlib] |

### New Dependencies
None. This phase adds zero new packages.

## Architecture Patterns

### System Architecture: Error Flow

```
fn press -> start_recording()
              |
              +-- sd.InputStream fails? --> set_hud("error_fatal") + tooltip
              |                             (PortAudioError: no mic / permission denied)
              |
              v
         audio_callback -> audio_chunks (buffer retained for retry)
              |
fn release -> stop_and_transcribe()
              |
              +-- _encode_and_transcribe() with timeout=30s
              |       |
              |       +-- APITimeoutError --> set_hud("error_retryable") + tooltip
              |       +-- APIConnectionError --> set_hud("error_retryable") + tooltip
              |       +-- InternalServerError --> set_hud("error_retryable") + tooltip
              |       +-- Success --> paste_text() / note pipeline
              |
              +-- Retry click on HUD --> re-call _encode_and_transcribe() with same buffer

Parallel:
  health_check_thread (daemon, every 5-10s)
    +-- CGEventTapIsEnabled(tap)?
    |     No --> set_hud("error_fatal") + tooltip + CGEventTapEnable(tap, True)
    |     Yes --> clear error if previously set
```

### Pattern 1: OpenAI Client Timeout

**What:** Set 30s timeout on OpenAI client constructor so all API calls (transcription) respect the limit.
**When to use:** Client initialization in govori.py line 583.

```python
# Source: Context7 /openai/openai-python, timeout configuration
# Current:
client = OpenAI(api_key=_api_key, base_url=_base_url) if _base_url else OpenAI(api_key=_api_key)

# New:
client = OpenAI(api_key=_api_key, base_url=_base_url, timeout=30.0) if _base_url else OpenAI(api_key=_api_key, timeout=30.0)
```

The SDK raises `openai.APITimeoutError` (subclass of `openai.APIConnectionError`) when the timeout is exceeded. Default retry count is 2 -- since we have our own retry mechanism via HUD click, set `max_retries=0` on the client to avoid hidden double-retries. [VERIFIED: Context7 /openai/openai-python]

### Pattern 2: CGEventTap Health Check Thread

**What:** Daemon thread polling `CGEventTapIsEnabled(tap)` every N seconds.
**When to use:** After `install_monitor()` creates the tap.

```python
# [ASSUMED] -- pattern follows existing daemon thread convention in codebase
def _tap_health_check(tap):
    """Poll CGEventTap health. Daemon thread -- exits with main."""
    tap_was_disabled = False
    while True:
        time.sleep(7)  # D-09: every 5-10 seconds
        enabled = Quartz.CGEventTapIsEnabled(tap)
        if not enabled and not tap_was_disabled:
            tap_was_disabled = True
            Quartz.CGEventTapEnable(tap, True)  # D-10: attempt re-enable
            set_hud(True, mode="error_fatal", tooltip=TOOLTIP_STRINGS[lang]["accessibility_revoked"])
            print("! Accessibility revoked -- attempting re-enable", flush=True)
        elif enabled and tap_was_disabled:
            tap_was_disabled = False
            set_hud(False)  # Clear error
            print("Accessibility restored.", flush=True)
```

Key insight: `CGEventTapEnable(tap, True)` may silently fail if the permission is truly revoked (macOS will re-disable it). The health check loop handles this by checking again on the next cycle. [ASSUMED]

### Pattern 3: HUD Tooltip as Companion NSPanel

**What:** A second borderless NSPanel positioned to the right of the HUD circle.
**Rationale:** NSToolTip is not suitable because the HUD has `setIgnoresMouseEvents_(True)` in most modes, and NSToolTip requires the system tooltip mechanism which does not work with non-activating panels. A companion NSPanel gives full control over show/hide timing, positioning, and styling.

```python
# [ASSUMED] -- based on existing NSPanel pattern in setup_hud()
tooltip_panel = None

def _setup_tooltip():
    global tooltip_panel
    style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
    panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        AppKit.NSMakeRect(42, 0, 240, 24), style,  # 42 = 6 (hud_x) + 32 (hud_size) + 4 (gap)
        AppKit.NSBackingStoreBuffered, False,
    )
    panel.setLevel_(AppKit.NSFloatingWindowLevel + 1)
    panel.setOpaque_(False)
    panel.setBackgroundColor_(
        AppKit.NSColor.colorWithRed_green_blue_alpha_(0.15, 0.15, 0.15, 0.92)
    )
    panel.contentView().setWantsLayer_(True)
    panel.contentView().layer().setCornerRadius_(6)
    panel.setIgnoresMouseEvents_(True)
    panel.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorStationary
    )
    # Text label
    label = AppKit.NSTextField.labelWithString_("")
    label.setFont_(AppKit.NSFont.systemFontOfSize_(11))
    label.setTextColor_(AppKit.NSColor.colorWithRed_green_blue_alpha_(0.95, 0.95, 0.95, 1.0))
    label.setPreferredMaxLayoutWidth_(224)  # 240 - 2*8 padding
    label.setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
    panel.contentView().addSubview_(label)
    tooltip_panel = panel
```

### Pattern 4: Mouse Event Handling for Retry Click

**What:** Toggle `setIgnoresMouseEvents_` on the HUD based on mode. Add click handler.
**Implementation approach:** The HUD window is an NSPanel, which inherits from NSWindow. To receive `mouseDown:`, we need a custom NSView subclass for the content view, or use an NSClickGestureRecognizer. The gesture recognizer is simpler and does not require subclassing.

```python
# [ASSUMED] -- AppKit gesture recognizer pattern
def _setup_hud_click():
    recognizer = AppKit.NSClickGestureRecognizer.alloc().initWithTarget_action_(
        _hud_click_handler, "handleClick:"
    )
    hud_window.contentView().addGestureRecognizer_(recognizer)
```

**Note:** The click handler target needs to be an NSObject subclass (similar to the existing `PredictController` pattern). The handler checks current HUD mode -- if `error_retryable`, triggers retry with the buffered audio. [ASSUMED]

### Pattern 5: subprocess.run for Safe Editor Launch

**What:** Replace `os.system(f"{editor} {path}")` with `subprocess.run([editor, str(path)])`.

```python
# Source: Python stdlib docs
# Line 1823, current:
os.system(f"{editor} {path}")

# New:
subprocess.run([editor, str(path)])
```

This eliminates shell interpretation entirely. The editor and path are passed as separate argv elements. [VERIFIED: Python stdlib]

### Anti-Patterns to Avoid

- **Catching broad Exception in start_recording():** The current `except Exception: pass` on line 737-738 silently swallows mic errors. Must catch `sd.PortAudioError` specifically and show HUD feedback.
- **Setting timeout per-request instead of on client:** Per-request timeout via `with_options(timeout=30)` would require touching every API call site. Setting it on the client constructor covers all calls uniformly.
- **Using NSToolTip for HUD tooltip:** NSToolTip does not work with `setIgnoresMouseEvents_(True)` windows and cannot be styled. Use a companion NSPanel.
- **Exiting on CGEventTap failure at runtime:** Per D-11, the app must continue running. Only the initial tap creation in `install_monitor()` should exit on failure (as it does now).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| API timeout | Manual threading.Timer wrapper | `OpenAI(timeout=30.0)` | SDK handles timeout natively via httpx; raises typed exception [VERIFIED: Context7] |
| Shell-safe subprocess | Manual string escaping/quoting | `subprocess.run([editor, path])` | List-form subprocess bypasses shell entirely [VERIFIED: Python stdlib] |
| Mic availability check | Raw PortAudio C API | `sd.query_devices(kind='input')` | sounddevice wraps PortAudio device enumeration [VERIFIED: runtime check] |
| Event tap health | Custom Mach port monitoring | `Quartz.CGEventTapIsEnabled(tap)` | Direct Quartz API, returns bool [VERIFIED: runtime import] |

## Common Pitfalls

### Pitfall 1: OpenAI SDK Default Retries Conflict with HUD Retry

**What goes wrong:** OpenAI Python SDK defaults to `max_retries=2` with exponential backoff. If we also implement HUD click-to-retry, the user sees a 30s timeout but the SDK actually waits up to 3x30s = 90s internally before surfacing the error.
**Why it happens:** The SDK's retry mechanism is invisible to the caller.
**How to avoid:** Set `max_retries=0` on the client constructor so errors surface immediately. The HUD retry mechanism is user-initiated and provides visible feedback. [VERIFIED: Context7 /openai/openai-python -- max_retries param documented]
**Warning signs:** Transcription appearing to hang for >30s despite the timeout setting.

### Pitfall 2: CGEventTapEnable Succeeds But macOS Re-Disables

**What goes wrong:** Calling `CGEventTapEnable(tap, True)` may temporarily succeed but macOS re-disables the tap within milliseconds if the Accessibility permission is still revoked.
**Why it happens:** macOS checks Accessibility permission asynchronously and kills unauthorized taps.
**How to avoid:** The health check loop already handles this -- it checks again on the next cycle. Don't assume a single `CGEventTapEnable` call permanently fixes the issue. Track `tap_was_disabled` state and only clear the error HUD when the tap stays enabled across a full check cycle. [ASSUMED]
**Warning signs:** HUD flickers between error and normal states rapidly.

### Pitfall 3: set_hud() Called from Non-Main Thread

**What goes wrong:** AppKit UI updates from background threads cause crashes or visual corruption.
**Why it happens:** The health check thread, retry thread, and transcription thread all need to update the HUD.
**How to avoid:** All HUD updates must go through `NSOperationQueue.mainQueue().addOperationWithBlock_()` -- this is already the pattern in the existing `set_hud()` function. The new tooltip show/hide must follow the same pattern. [VERIFIED: existing codebase pattern at line 720]
**Warning signs:** Random crashes with `NSInternalInconsistencyException`.

### Pitfall 4: Audio Buffer Cleared Before Retry Completes

**What goes wrong:** User clicks retry on HUD, but a new fn press arrives and `start_recording()` clears `audio_chunks` before the retry thread reads them.
**Why it happens:** `audio_chunks = []` in `start_recording()` (line 743) is unconditional.
**How to avoid:** Copy `audio_chunks` to a separate `_retry_buffer` when error occurs. The retry mechanism uses `_retry_buffer`, not `audio_chunks`. New recording clears `audio_chunks` but not `_retry_buffer`. [ASSUMED]
**Warning signs:** Retry produces empty transcription or crashes with empty buffer.

### Pitfall 5: Tooltip Panel Not Visible on All Spaces

**What goes wrong:** Tooltip appears on one Space but not when user switches to another.
**Why it happens:** Missing `NSWindowCollectionBehaviorCanJoinAllSpaces` on the tooltip panel.
**How to avoid:** Set same collection behavior as the main HUD panel. [VERIFIED: existing pattern in setup_hud() line 643-646]

### Pitfall 6: Privacy Notice Step Breaks Step Numbering

**What goes wrong:** Existing onboarding has hardcoded "Step 1/3", "Step 2/3", "Step 3/3" in both en and ru strings. Adding a step requires updating ALL existing step headers.
**Why it happens:** Step numbers are embedded in string literals, not computed.
**How to avoid:** Update all 6 step header strings (3 steps x 2 languages) to reflect the new 4-step flow. UI-SPEC already specifies the new numbering: 1/4, 2/4, 3/4, 4/4. [VERIFIED: govori.py lines 196-286, SETUP_STRINGS dict]

## Code Examples

### SEC-01: Shell Injection Fix

```python
# Source: Python stdlib subprocess documentation
# govori.py line 1822-1823
# BEFORE:
editor = os.environ.get("EDITOR", "nano")
os.system(f"{editor} {path}")

# AFTER:
editor = os.environ.get("EDITOR", "nano")
subprocess.run([editor, str(path)])
```

### SEC-03: OpenAI Client with Timeout and No Auto-Retry

```python
# Source: Context7 /openai/openai-python
# govori.py line 583
import openai  # for exception types

# Client init:
client = OpenAI(api_key=_api_key, timeout=30.0, max_retries=0)
# or with base_url:
client = OpenAI(api_key=_api_key, base_url=_base_url, timeout=30.0, max_retries=0)

# Exception handling in _encode_and_transcribe():
try:
    result = client.audio.transcriptions.create(
        model=MODEL, file=buf, language=LANGUAGE,
        temperature=0, prompt=WHISPER_PROMPT,
    )
    return result.text.strip()
except openai.APITimeoutError:
    print("! Transcription timed out", flush=True)
    return None  # caller handles HUD transition to error_retryable
except openai.APIConnectionError as e:
    print(f"! Connection error: {e}", flush=True)
    return None
except openai.APIStatusError as e:
    if e.status_code >= 500:
        print(f"! Server error ({e.status_code})", flush=True)
        return None  # retryable
    print(f"API error ({e.status_code}): {e}", flush=True)
    return None  # non-retryable, but caller may still show retry
```

### SEC-04: Privacy Notice Strings

```python
# Source: UI-SPEC.md, exact copy
# Add to SETUP_STRINGS["en"]:
"step_privacy": """
\033[33m  -- Step 2/4 -- Privacy Notice --------------------------------\033[0m

  Govori sends data to cloud APIs for processing:

    \033[1mVoice audio\033[0m  -->  OpenAI Whisper API (speech-to-text)
    \033[1mNote text\033[0m    -->  Anthropic Claude API (classification)

  \033[2mAudio is not stored after transcription. Notes are processed
  but not retained by Anthropic. Keys stay local on your machine.\033[0m

""",

# Add to SETUP_STRINGS["ru"]:
"step_privacy": """
\033[33m  -- Step 2/4 -- Confidentiality ----------------------------\033[0m

  Govori sends data to cloud APIs for processing:

    \033[1mVoice audio\033[0m  -->  OpenAI Whisper API (speech recognition)
    \033[1mNote text\033[0m    -->  Anthropic Claude API (classification)

  \033[2mAudio is not stored after transcription. Notes are processed
  but not retained by Anthropic. Keys stay on your device.\033[0m

""",
```

### REL-01: Microphone Startup Check

```python
# Source: sounddevice docs, verified via runtime
# After install_monitor() in __main__ block:
try:
    sd.query_devices(kind='input')
except sd.PortAudioError:
    print("! No microphone detected. Plug one in before recording.", flush=True)

# In start_recording(), replace broad except:
try:
    audio_stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=audio_callback,
    )
    audio_stream.start()
except sd.PortAudioError as e:
    recording = False
    audio_stream = None
    set_hud(True, mode="error_fatal", tooltip=_mic_error_text(e))
    print(f"! Mic error: {e}", flush=True)
    return
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `os.system(cmd)` | `subprocess.run([...])` | Python 3.5 (2015) | Eliminates shell injection entirely |
| No timeout on OpenAI client | `OpenAI(timeout=30.0)` | openai-python 1.x (2023) | Built-in httpx timeout, typed exceptions |
| Manual PortAudio device check | `sd.query_devices(kind='input')` | sounddevice 0.4+ | Returns device dict or raises PortAudioError |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | CGEventTapEnable(tap, True) may be re-disabled by macOS if permission is revoked | Pitfall 2 | Health check could show false "recovered" state -- mitigated by re-checking on next cycle |
| A2 | NSClickGestureRecognizer works on NSPanel content view for HUD click | Pattern 4 | Would need NSView subclass with mouseDown: instead -- slightly more code but same result |
| A3 | Companion NSPanel is the best tooltip approach | Pattern 3 | Could use NSPopover, but NSPanel gives more control and matches existing pattern |
| A4 | Retry buffer should be separate from audio_chunks | Pitfall 4 | If same list is used, race condition between new recording and retry |

## Open Questions

1. **OpenAI exception type hierarchy**
   - What we know: `APITimeoutError` is a subclass of `APIConnectionError`. `APIStatusError` covers HTTP errors with status codes. [VERIFIED: Context7]
   - What's unclear: Whether the `_encode_and_transcribe()` caller (`stop_and_transcribe()`) needs to distinguish retryable from fatal errors, or if all failures should show retry.
   - Recommendation: Per D-06, all API errors are retryable (timeout, network, 5xx). Only mic/accessibility errors are fatal (D-07). Treat all exceptions from `_encode_and_transcribe()` as retryable in `stop_and_transcribe()`.

2. **Tooltip text localization mechanism**
   - What we know: Existing `SETUP_STRINGS` is keyed by language. HUD tooltip messages need the same en/ru support (per UI-SPEC).
   - What's unclear: How to access the current language at runtime -- `cli_setup()` asks for language but doesn't persist it to a global. `config.yaml` has a `language` field.
   - Recommendation: Read `CONFIG.get("language", "en")` for tooltip strings. Create a `TOOLTIP_STRINGS` dict parallel to `SETUP_STRINGS`.

3. **HUD click handler architecture**
   - What we know: Need an NSObject subclass to be the gesture recognizer target (PyObjC requires ObjC-compatible selector). Existing `PredictController` is a precedent.
   - What's unclear: Whether to extend PredictController or create a separate handler class.
   - Recommendation: Create a minimal `HUDClickHandler(AppKit.NSObject)` class with a single `handleClick_` method. Keep it separate from PredictController -- different concerns.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3 | All | Yes | 3.14.0a6 | -- |
| openai SDK | SEC-03 | Yes | 2.30.0 | -- |
| pyobjc-framework-Quartz | SEC-02 | Yes | 12.1 | -- |
| pyobjc-framework-Cocoa | HUD tooltip | Yes | 12.1 | -- |
| sounddevice | REL-01 | Yes | 0.5.5 | -- |
| subprocess (stdlib) | SEC-01 | Yes | stdlib | -- |

**Missing dependencies:** None. All packages are already installed in the project virtualenv.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A -- no user auth in app |
| V3 Session Management | No | N/A -- no sessions |
| V4 Access Control | No | N/A -- single-user desktop app |
| V5 Input Validation | Yes | `subprocess.run([...])` for command execution (SEC-01); `_sanitize_slug()` for note paths |
| V6 Cryptography | No | N/A -- no crypto operations |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Shell injection via os.system | Elevation of privilege | subprocess.run with list args (no shell) |
| API key exposure in env file | Information disclosure | File permissions 0o600 (already implemented) |
| System input freeze from dead event tap | Denial of service | Health check thread with auto-recovery (SEC-02) |

## Sources

### Primary (HIGH confidence)
- Context7 /openai/openai-python -- timeout configuration, max_retries, exception types
- Runtime verification -- pyobjc-framework-Quartz `CGEventTapIsEnabled` availability confirmed
- Runtime verification -- sounddevice `PortAudioError`, `query_devices(kind='input')` confirmed
- Python stdlib documentation -- subprocess.run list form

### Secondary (MEDIUM confidence)
- Existing codebase analysis -- govori.py line references verified by direct file reads
- UI-SPEC.md -- approved design contract with exact specifications

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all packages already installed, versions verified, APIs confirmed
- Architecture: HIGH -- changes are localized, patterns verified against existing codebase
- Pitfalls: MEDIUM -- CGEventTap re-disable behavior (A1) and NSClickGestureRecognizer on NSPanel (A2) are assumed based on macOS documentation knowledge

**Research date:** 2026-04-17
**Valid until:** 2026-05-17 (stable -- no fast-moving dependencies)
