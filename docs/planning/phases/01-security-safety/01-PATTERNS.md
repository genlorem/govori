# Phase 1: Security & Safety - Pattern Map

**Mapped:** 2026-04-17
**Files analyzed:** 1 (govori.py -- single-file application, 6 modification zones)
**Analogs found:** 6 / 6 (all modifications are to existing code; analogs are adjacent code in the same file)

## File Classification

This phase modifies a single file (`govori.py`) in 6 distinct zones. No new files are created.

| Modification Zone | Role | Data Flow | Closest Analog (same file) | Match Quality |
|-------------------|------|-----------|---------------------------|---------------|
| `set_hud()` + new tooltip panel | component (HUD) | event-driven | `setup_hud()` lines 627-680 | exact |
| `cli_setup()` privacy notice step | CLI (onboarding) | request-response | `SETUP_STRINGS` dict lines 163-310 | exact |
| `_encode_and_transcribe()` timeout + error handling | service (API) | request-response | existing try/except lines 781-792 | exact |
| `start_recording()` mic error handling | service (audio) | event-driven | `start_recording()` lines 728-758 | exact |
| `install_monitor()` + health check thread | middleware (system) | event-driven | `_note_pipeline_background()` daemon thread pattern | role-match |
| `os.system()` shell injection fix | utility (CLI) | request-response | line 1823 (self-replacement) | exact |
| HUD click handler for retry | component (HUD) | event-driven | `PredictController` lines 1373-1386 | exact |

## Pattern Assignments

### Zone 1: HUD Error States + Tooltip Panel (component, event-driven)

**Analog:** `setup_hud()` at `govori.py` lines 627-680

**NSPanel creation pattern** (lines 634-647):
```python
style = AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel
win = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
    AppKit.NSMakeRect(x, y, _HUD_S, _HUD_S), style,
    AppKit.NSBackingStoreBuffered, False,
)
win.setLevel_(AppKit.NSFloatingWindowLevel + 1)
win.setOpaque_(False)
win.setBackgroundColor_(AppKit.NSColor.clearColor())
win.setIgnoresMouseEvents_(True)
win.setCollectionBehavior_(
    AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
    | AppKit.NSWindowCollectionBehaviorStationary
    | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
)
```

**set_hud() mode dispatch pattern** (lines 683-720):
```python
def set_hud(visible, mode="recording"):
    def _update():
        if mode == "recording":
            hud_label.setStringValue_("...")
            hud_label.setTextColor_(
                AppKit.NSColor.colorWithRed_green_blue_alpha_(1.0, 0.3, 0.3, 1.0)
            )
        # ... more elif branches ...
        if visible:
            hud_window.setFrameOrigin_(AppKit.NSMakePoint(6, 0))
            hud_window.orderFrontRegardless()
        else:
            hud_window.orderOut_(None)
    AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(_update)
```

**Key rules:**
- New modes `"error_retryable"` and `"error_fatal"` extend the existing `if/elif` chain
- Tooltip panel is a companion NSPanel created in a `_setup_tooltip()` function called from `setup_hud()`
- Tooltip show/hide happens inside `_update()` closure, dispatched to main queue -- same pattern as line 720
- Tooltip panel must have identical `setCollectionBehavior_` as the HUD (lines 643-647)

---

### Zone 2: HUD Click Handler for Retry (component, event-driven)

**Analog:** `PredictController` at `govori.py` lines 1373-1386

**NSObject subclass with ObjC selector pattern** (lines 1373-1381):
```python
class PredictController(AppKit.NSObject):
    _continuations = []

    def pickContinuation_(self, sender):
        idx = sender.tag()
        if 0 <= idx < len(self._continuations):
            text = self._continuations[idx]
            print(f"... {text}", flush=True)
            threading.Thread(target=lambda t=text: paste_text(t), daemon=True).start()
```

**Setup/init pattern** (lines 1384-1386):
```python
def setup_predict():
    global _predict_controller
    _predict_controller = PredictController.alloc().init()
```

**Key rules:**
- New `HUDClickHandler(AppKit.NSObject)` follows exact same pattern
- Single ObjC-compatible method (e.g., `handleClick_`) that checks current HUD mode
- If mode is `error_retryable`, triggers retry with `_retry_buffer` in a daemon thread
- Instantiated via `.alloc().init()` and stored in a module-level global
- Gesture recognizer attached to HUD content view: `hud_window.contentView().addGestureRecognizer_(recognizer)`

---

### Zone 3: Privacy Notice in Onboarding (CLI, request-response)

**Analog:** `SETUP_STRINGS` dict at `govori.py` lines 163-310, `cli_setup()` at lines 323-390

**Bilingual string dict pattern** (lines 196-204, English step):
```python
"step_access": """
\033[33m  -- Step 2/3 - Accessibility Permission --------------------\033[0m

  Govori needs Accessibility access to listen for the \033[1mfn\033[0m key.

  \033[36mSystem Settings -> Privacy & Security -> Accessibility\033[0m
  \033[36m-> Add your terminal app (Terminal / iTerm / Ghostty)\033[0m

""",
```

**Step flow in cli_setup()** (lines 343-372):
```python
# Step 1: API keys
print(s["step_keys"])
openai_key = _ask(s["ask_openai"])
anthropic_key = _ask(s["ask_anthropic"])
# ... save keys ...
print(s["keys_saved"])

# Step 2: Accessibility
print(s["step_access"])
_ask(s["ask_access_done"])

# Step 3: Hotkeys tutorial
print(s["step_hotkeys"])
```

**Key rules:**
- Add `"step_privacy"` to both `SETUP_STRINGS["en"]` and `SETUP_STRINGS["ru"]` dicts
- Insert `print(s["step_privacy"])` between API key saving (line 368) and Accessibility step (line 371)
- Update ALL step header strings from `X/3` to `X/4` (6 strings total: `step_keys`, `step_access`, `step_hotkeys` x 2 languages)
- Privacy notice is informational -- no `_ask()` call, just `print()`

---

### Zone 4: API Timeout + Error Handling in `_encode_and_transcribe()` (service, request-response)

**Analog:** OpenAI client init at `govori.py` line 583, existing error handling at lines 781-792

**Client initialization pattern** (line 583):
```python
client = OpenAI(api_key=_api_key, base_url=_base_url) if _base_url else OpenAI(api_key=_api_key)
```

**Existing API error handling** (lines 780-792):
```python
try:
    result = client.audio.transcriptions.create(
        model=MODEL,
        file=buf,
        language=LANGUAGE,
        temperature=0,
        prompt=WHISPER_PROMPT,
    )
    return result.text.strip()
except Exception as e:
    print(f"API error: {e}", flush=True)
    return None
```

**Key rules:**
- Add `timeout=30.0, max_retries=0` to `OpenAI()` constructor (line 583, both branches)
- Replace broad `except Exception` with specific `openai.APITimeoutError`, `openai.APIConnectionError`, `openai.APIStatusError` catches
- Return `None` on all API errors (caller `stop_and_transcribe` handles HUD transition)
- Import `openai` module for exception types (already partially imported at line 27: `from openai import OpenAI`)

---

### Zone 5: Microphone Error Handling in `start_recording()` (service, event-driven)

**Analog:** `start_recording()` at `govori.py` lines 728-758

**Current recording start pattern** (lines 728-747):
```python
def start_recording():
    global recording, audio_chunks, audio_stream, auto_send, cancelled
    with _state_lock:
        if recording:
            return
        if audio_stream is not None:
            try:
                audio_stream.stop()
                audio_stream.close()
            except Exception:
                pass
            audio_stream = None
        recording    = True
        auto_send    = False
        cancelled    = False
        audio_chunks = []
        audio_stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=audio_callback,
        )
        audio_stream.start()
```

**Key rules:**
- Wrap `sd.InputStream()` creation and `.start()` (lines 744-747) in `try/except sd.PortAudioError`
- On failure: reset `recording = False`, `audio_stream = None`, call `set_hud(True, mode="error_fatal", tooltip=...)`, print with `!` prefix
- Add startup check in `__main__` block (after `install_monitor()`, line 1903): `sd.query_devices(kind='input')` wrapped in try/except, non-blocking warning only

---

### Zone 6: CGEventTap Health Check Thread (middleware, event-driven)

**Analog:** Daemon thread pattern used throughout codebase

**Daemon thread launch pattern** (line 1504):
```python
threading.Thread(target=stop_and_transcribe, daemon=True).start()
```

**Delayed action in daemon thread** (lines 856-859):
```python
def _hide_check():
    time.sleep(1.2)
    set_hud(False)
threading.Thread(target=_hide_check, daemon=True).start()
```

**install_monitor() tap creation** (lines 1510-1529):
```python
def install_monitor():
    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly,
        Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        | Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
        cg_event_callback,
        None,
    )
    if tap is None:
        print("ERROR: CGEventTap failed. Check Accessibility permission.", flush=True)
        sys.exit(1)

    src = CoreFoundation.CFMachPortCreateRunLoopSource(None, tap, 0)
    CoreFoundation.CFRunLoopAddSource(
        CoreFoundation.CFRunLoopGetMain(), src, CoreFoundation.kCFRunLoopCommonModes,
    )
    Quartz.CGEventTapEnable(tap, True)
    print("Hotkey monitor installed.", flush=True)
```

**Key rules:**
- `install_monitor()` must return the `tap` reference (currently discarded)
- New `_tap_health_check(tap)` function follows daemon thread + sleep loop pattern
- Health check calls `Quartz.CGEventTapIsEnabled(tap)` and `Quartz.CGEventTapEnable(tap, True)`
- HUD updates from health thread MUST go through `NSOperationQueue.mainQueue().addOperationWithBlock_()` (line 720 pattern)
- Launch thread after `install_monitor()` in `__main__` block

---

### Zone 7: Shell Injection Fix (utility, one-liner)

**Analog:** `govori.py` line 1822-1823

**Current pattern:**
```python
editor = os.environ.get("EDITOR", "nano")
os.system(f"{editor} {path}")
```

**Key rules:**
- Replace with `subprocess.run([editor, str(path)])`
- `subprocess` is already importable from stdlib; add `import subprocess` to import block (lines 14-22)

---

## Shared Patterns

### Main Queue Dispatch (applies to ALL HUD-modifying zones)
**Source:** `govori.py` line 720
**Apply to:** Zone 1 (tooltip show/hide), Zone 2 (click handler HUD update), Zone 5 (mic error HUD), Zone 6 (health check HUD)
```python
AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(_update)
```

### State Lock (applies to zones with shared mutable state)
**Source:** `govori.py` lines 603-604
**Apply to:** Zone 4 (retry buffer), Zone 5 (recording flags), Zone 6 (tap health state)
```python
_state_lock = threading.Lock()
# Usage:
with _state_lock:
    # mutate shared state
```

### Error Print Convention (applies to all error paths)
**Source:** Throughout `govori.py`
**Apply to:** All zones
```python
# Fatal/system errors use "!" prefix:
print("! No microphone detected.", flush=True)
# API errors:
print(f"API error: {e}", flush=True)
# Status symbols:
#   ! = warning/error
#   ... = unicode status symbol (see set_hud modes)
```

### Daemon Thread Pattern (applies to background work)
**Source:** `govori.py` lines 1500, 856-859
**Apply to:** Zone 2 (retry execution), Zone 6 (health check loop)
```python
threading.Thread(target=function_name, daemon=True).start()
```

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | -- | -- | All modifications are to existing code with clear in-file analogs |

## Metadata

**Analog search scope:** `/Users/genlorem/Projects/wisp/govori.py` (single-file application)
**Files scanned:** 1
**Pattern extraction date:** 2026-04-17
