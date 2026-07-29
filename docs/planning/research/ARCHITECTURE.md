# Architecture Patterns

**Domain:** macOS voice dictation tool (Python CLI daemon)
**Researched:** 2026-04-17

## Verdict: Split Into Modules

The 1911-line single file should be split into 6-8 modules. Not because of line count alone, but because the file contains **6 distinct concerns with zero isolation**:

1. Config loading and plugin discovery
2. CLI routing and onboarding
3. Audio capture and encoding
4. API clients (OpenAI transcription, Anthropic classification)
5. macOS integration (CGEventTap, Cocoa HUD, clipboard)
6. Notes pipeline (classify, save, merge, browse)

These concerns share state through 11 mutable globals (`recording`, `audio_chunks`, `audio_stream`, `transcribing`, `note_mode`, `predict_mode`, `auto_send`, `cancelled`, `_state_lock`, `_anthropic_client`, `client`). This makes testing impossible and error handling fragile -- a bug in notes can crash the event loop.

**Confidence: HIGH** -- this is standard Python project architecture, well-documented patterns.

## Current Architecture (As-Is)

```
govori.py (1911 lines, single file)
  |
  |-- Module-level execution: cli_main() runs at import time (line 562)
  |-- Module-level globals: CONFIG, PLUGINS, client initialized at import
  |-- 47 functions + 1 class (PredictController)
  |
  |-- Config layer: _load_yaml, load_config, load_plugins, build_whisper_prompt
  |-- CLI layer: cli_main, cli_setup, cli_plugin, cli_notes
  |-- Audio layer: audio_callback, start_recording, _encode_and_transcribe
  |-- Transcription layer: stop_and_transcribe, _is_hallucination
  |-- Notes layer: classify_note, save_as_note, save_or_merge_note, _decide_merge
  |-- macOS layer: cg_event_callback, install_monitor, setup_hud, set_hud
  |-- Paste layer: paste_text, _press_enter
  |-- Predict layer: PredictController, generate_continuations, show_predict_menu
```

### Critical Problems

1. **Module-level side effects**: `cli_main()` runs at line 562 during import. `OpenAI()` client is constructed at module level (line 583). This means you cannot import any function without triggering API key validation, config loading, and potential `sys.exit(1)`.

2. **Global mutable state**: 11 globals shared across threading boundaries with a single `_state_lock` that only protects some transitions. Race conditions are likely between `cg_event_callback` (main thread) and `stop_and_transcribe` (background thread).

3. **No error boundaries**: An exception in `classify_note` (Anthropic API) propagates up through `save_or_merge_note` -> `_note_pipeline_background` -> background thread. If the thread dies silently, the HUD stays in "processing" state forever.

4. **Untestable**: Cannot test `_encode_and_transcribe` without a live OpenAI API key. Cannot test `classify_note` without Anthropic. Cannot test `start_recording` without a microphone.

## Recommended Architecture (To-Be)

### Package Layout

```
govori/
    __init__.py          # Version, package metadata
    __main__.py          # Entry point: `python -m govori`
    cli.py               # CLI routing, argument parsing, onboarding
    config.py            # Config loading, validation, plugin discovery
    audio.py             # Recording, encoding (sounddevice, PyAV)
    transcribe.py        # OpenAI API client, hallucination filter
    notes.py             # Classification, save, merge, browse, amend
    hud.py               # Hammerspoon HUD communication
    macos.py             # CGEventTap, clipboard, paste, Cocoa app lifecycle
    predict.py           # PredictController, continuation generation
    state.py             # Shared state object (replaces globals)
```

### Component Boundaries

| Component | Responsibility | Depends On | Depended On By |
|-----------|---------------|------------|----------------|
| `config.py` | Load YAML, validate, discover plugins | filesystem only | everything |
| `state.py` | Thread-safe state container | nothing | audio, macos, hud |
| `audio.py` | Capture mic input, encode to OGG/Opus | sounddevice, PyAV, state | transcribe |
| `transcribe.py` | Send audio to OpenAI, filter hallucinations | OpenAI client, config | macos (on fn-release) |
| `notes.py` | Classify via Anthropic, save/merge markdown | Anthropic client, config, filesystem | macos (on note-mode release) |
| `hud.py` | Send state updates to Hammerspoon | subprocess/socket | audio, transcribe, macos |
| `predict.py` | Generate autocomplete options, show menu | OpenAI client, AppKit | macos (on predict-mode release) |
| `macos.py` | CGEventTap, clipboard, NSApplication lifecycle | Quartz, AppKit, state | cli (daemon mode) |
| `cli.py` | Route subcommands, onboarding | config, notes, macos | `__main__` |

### Data Flow

```
User presses fn key
       |
       v
  macos.py: cg_event_callback
       |
       +-- start_recording() --> audio.py: open stream, write to state.audio_chunks
       |
  User releases fn key
       |
       v
  macos.py: dispatch based on mode
       |
       +-- DICTATE MODE ---------> transcribe.py: encode + Whisper API
       |                                  |
       |                                  v
       |                           macos.py: paste_text (clipboard + Cmd+V)
       |
       +-- PREDICT MODE ---------> transcribe.py: encode + Whisper API
       |                                  |
       |                                  v
       |                           predict.py: generate_continuations (OpenAI)
       |                                  |
       |                                  v
       |                           predict.py: show_predict_menu (AppKit NSMenu)
       |
       +-- NOTE MODE ------------> transcribe.py: encode + Whisper API
                                          |
                                          v
                                   notes.py: classify_note (Anthropic)
                                          |
                                          v
                                   notes.py: save_or_merge_note (filesystem)

HUD updates happen at each transition:
  recording -> transcribing -> done/error
  hud.py is called by audio.py and transcribe.py at state transitions
```

### State Object (Replaces Globals)

```python
# state.py
import threading
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np

@dataclass
class AppState:
    """Thread-safe shared state. Single source of truth."""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    recording: bool = False
    transcribing: bool = False
    audio_chunks: List[np.ndarray] = field(default_factory=list)
    audio_stream: Optional[object] = None  # sd.InputStream
    auto_send: bool = False
    cancelled: bool = False
    predict_mode: bool = False
    note_mode: bool = False

    def start_recording(self):
        with self._lock:
            if self.recording:
                return False
            self.recording = True
            self.auto_send = False
            self.cancelled = False
            self.audio_chunks = []
            return True

    def stop_recording(self):
        with self._lock:
            if not self.recording:
                return None
            self.recording = False
            self.transcribing = True
            chunks = self.audio_chunks
            self.audio_chunks = []
            return chunks
```

This replaces the 11 loose globals with a single object that encapsulates state transitions. Lock usage is explicit and co-located with the state it protects.

### Error Handling Strategy

Each component owns its errors. No exception propagates across component boundaries without being caught and converted.

```python
# transcribe.py
class TranscriptionError(Exception):
    """Raised when Whisper API fails after retries."""
    pass

def encode_and_transcribe(audio: np.ndarray, config: dict) -> str:
    """Returns transcribed text. Raises TranscriptionError on failure."""
    encoded = _encode_ogg_opus(audio, config["sample_rate"])
    try:
        result = _client.audio.transcriptions.create(
            model=config["model"],
            file=encoded,
            language=config["language"],
            temperature=0,
            prompt=config["whisper_prompt"],
        )
        text = result.text.strip()
        if _is_hallucination(text):
            return ""
        return text
    except Exception as e:
        raise TranscriptionError(f"Whisper API failed: {e}") from e
```

The caller in `macos.py` catches `TranscriptionError` and updates HUD to error state instead of silently dying:

```python
# In the dispatch thread
try:
    text = transcribe.encode_and_transcribe(audio, config)
    if text:
        paste_text(text)
    hud.set_state("idle")
except TranscriptionError as e:
    logger.error(str(e))
    hud.set_state("error")
```

### Logging Strategy

Replace all `print(..., flush=True)` calls (there are ~40 of them) with stdlib `logging`:

```python
# config.py sets up logging once
import logging

def setup_logging(config: dict):
    log_file = config.get("log_file", "~/.config/govori/govori.log")
    log_file = Path(log_file).expanduser()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),  # Keep stdout for daemon mode
        ],
    )
```

Each module gets its own logger: `logger = logging.getLogger(__name__)`. This gives you `govori.audio`, `govori.transcribe`, `govori.notes` in log output -- instant diagnosis of which component failed.

## Patterns to Follow

### Pattern 1: Dependency Injection for API Clients

**What:** Pass API clients as parameters, don't construct at module level.
**Why:** Testable (mock client), no import side effects, lazy initialization.

```python
# transcribe.py
class Transcriber:
    def __init__(self, client: OpenAI, config: dict):
        self.client = client
        self.config = config

    def transcribe(self, audio: np.ndarray) -> str:
        ...

# In cli.py or __main__.py -- construct once, pass everywhere
client = OpenAI(api_key=config["api_key"])
transcriber = Transcriber(client, config)
```

### Pattern 2: Callback Registration (Not Hardcoded Dispatch)

**What:** The event handler in `macos.py` dispatches to registered callbacks, not hardcoded function calls.
**Why:** Modes (dictate, predict, note) can be added/removed without touching event handling code.

```python
# macos.py
class EventLoop:
    def __init__(self, state: AppState):
        self.state = state
        self._on_recording_complete = None

    def set_recording_handler(self, handler):
        self._on_recording_complete = handler
```

### Pattern 3: CLI as Thin Shell

**What:** `cli.py` only parses args and calls into domain modules. Zero business logic.
**Why:** The same domain code works for CLI and daemon mode.

```python
# cli.py
def main():
    args = parse_args()
    config = config_module.load()

    if args.command == "notes":
        notes.cli_browse(config, args)
    elif args.command == "note":
        notes.cli_add(config, args.text)
    elif args.command == "setup":
        onboarding.run(config, force=True)
    else:
        daemon.run(config)  # macos event loop
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Module-Level Execution

**What:** Running `cli_main()` at line 562 during import, constructing `OpenAI()` at module level.
**Why bad:** Cannot import any function for testing. Cannot use the module as a library. `sys.exit()` in module scope kills the test runner.
**Instead:** All side effects in `if __name__ == "__main__"` or in explicit `main()` called from `__main__.py`.

### Anti-Pattern 2: Globals for State Machine

**What:** 11 mutable globals (`recording`, `transcribing`, `note_mode`, etc.) with a single lock.
**Why bad:** Any function can mutate any state. Race conditions between event callback (main thread) and transcription (background thread). State transitions are implicit.
**Instead:** `AppState` dataclass with explicit transition methods that hold the lock.

### Anti-Pattern 3: Silent Thread Death

**What:** Background threads (`threading.Thread(target=stop_and_transcribe, daemon=True)`) with no error handling.
**Why bad:** If the thread throws, it dies silently. The HUD stays stuck. The user sees nothing.
**Instead:** Wrap thread targets in try/except that logs errors and resets HUD state.

## Suggested Build Order

Refactoring should be done incrementally, one module extraction at a time. Each step should leave the app fully functional.

### Phase 1: Foundation (No Behavior Change)

Extract in this order due to dependency direction:

1. **`config.py`** -- Lowest coupling. Move `_load_yaml`, `load_config`, `load_plugins`, `build_whisper_prompt`, `build_notes_config`. Only touches filesystem. Everything depends on it, it depends on nothing.

2. **`state.py`** -- Replace 11 globals with `AppState`. This is a mechanical replacement: every `global recording` becomes `state.recording`. No behavior change, just consolidation.

3. **`hud.py`** -- Move `setup_hud`, `set_hud`. Self-contained subprocess communication. Only dependency: config (for HUD path).

### Phase 2: Domain Extraction

4. **`audio.py`** -- Move `audio_callback`, `start_recording`, `_encode_and_transcribe`. Depends on: state, sounddevice, PyAV. Does not depend on API clients.

5. **`transcribe.py`** -- Move OpenAI client construction, `_is_hallucination`, the Whisper API call portion. Depends on: config (for model/language/prompt).

6. **`notes.py`** -- Move `classify_note`, `save_as_note`, `save_or_merge_note`, `_find_merge_candidates`, `_decide_merge`, `cli_notes`, `_amend_via_haiku`, all note browsing code. This is the largest extraction (~500 lines). Depends on: config, Anthropic client.

### Phase 3: Integration Layer

7. **`macos.py`** -- Move `cg_event_callback`, `install_monitor`, `paste_text`, `_press_enter`. This is the hardest module to extract because it's the glue. It calls audio, transcribe, notes, hud, and predict. Extract last so all its dependencies are already modules.

8. **`predict.py`** -- Move `PredictController`, `generate_continuations`, `show_predict_menu`, `setup_predict`. Depends on: OpenAI client, AppKit.

9. **`cli.py`** + **`__main__.py`** -- Move CLI routing. This wraps everything.

### Why This Order

- **config first**: zero dependencies, everything imports it
- **state second**: mechanical replacement, no logic change, enables all subsequent extractions to use the new state object
- **hud third**: tiny, self-contained, validates the extraction pattern works
- **domain modules (4-6) before integration (7-9)**: extract the pieces before extracting the glue that connects them
- **macos last among domain**: highest fan-out (calls everything), so extract its dependencies first

### Migration Safety

Each extraction step:
1. Create new module with functions moved verbatim
2. Replace original with `from govori.audio import ...` (re-exports)
3. Run the app manually -- fn key works, notes work, predict works
4. Delete re-exports from `govori.py` once all consumers are updated

The app should work identically after each step. No behavior changes during extraction.

## Testability After Refactoring

With dependency injection and module boundaries:

```python
# test_transcribe.py
from unittest.mock import MagicMock
from govori.transcribe import Transcriber

def test_hallucination_filtered():
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value.text = "продолжение следует"
    t = Transcriber(mock_client, {"model": "whisper-1", "language": "ru", "whisper_prompt": ""})
    assert t.transcribe(fake_audio) == ""

def test_api_error_raises():
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.side_effect = Exception("timeout")
    t = Transcriber(mock_client, config)
    with pytest.raises(TranscriptionError):
        t.transcribe(fake_audio)
```

This is impossible with the current single-file architecture because constructing the OpenAI client is a module-level side effect.

## Scalability Considerations

| Concern | Current (1 user) | At PyPI release | At 1000 users |
|---------|-------------------|-----------------|---------------|
| Error diagnosis | `print` to stdout, scroll back | Log files with module names | Log files + crash reports |
| Plugin system | YAML-only, works | YAML-only, works | May need versioned plugin API |
| Config | Single YAML | Need validation + friendly errors | Need migration on config format changes |
| Distribution | `python govori.py` | `pip install govori` (pyproject.toml) | Homebrew formula, standalone binary (PyInstaller) |
| Testing | None | Unit tests on domain modules | CI with mocked APIs |

## Sources

- Current codebase analysis: `govori.py` (1911 lines, 47 functions, 11 globals)
- [The Hitchhiker's Guide to Python - Project Structure](https://docs.python-guide.org/writing/structure/)
- [Real Python - Application Layouts](https://realpython.com/python-application-layouts/)
- [Python src layout best practices](https://medium.com/@adityaghadge99/python-project-structure-why-the-src-layout-beats-flat-folders-and-how-to-use-my-free-template-808844d16f35)
- [Building CLI Tools with Python](https://dasroot.net/posts/2025/12/building-cli-tools-python-click-typer-argparse/)
- [Building Python Packages: Development to PyPI](https://www.glukhov.org/post/2025/11/building-python-packages-from-development-to-pypi/)
- [PyObjC Documentation](https://pyobjc.readthedocs.io/en/latest/)
