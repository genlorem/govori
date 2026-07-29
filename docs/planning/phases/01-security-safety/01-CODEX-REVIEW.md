## Findings

### [HIGH] Accessibility revoke can leave microphone recording indefinitely
- **File:line:** govori.py:2513
- **Mера:** SEC-02
- **Что не так:** health-monitor shows fatal HUD but does not stop an active recording/audio stream.
- **Почему:** if CGEventTap is disabled/revoked while `recording=True`, fn-up may never arrive; `_tap_health_check()` never calls `cancel_recording()` or closes `audio_stream`.
- **Fix:** on tap disabled/revoked, atomically cancel recording, close stream, clear mode flags, then show fatal HUD.

### [MEDIUM] Health-monitor recovery can hide unrelated active HUD state
- **File:line:** govori.py:2524
- **Mера:** SEC-02
- **Что не так:** recovered tap blindly calls `set_hud(False)`.
- **Почему:** daemon thread can race with recording/transcribing/note-save UI and hide the HUD while sensitive work continues.
- **Fix:** track ownership of the accessibility error state; clear HUD only if the current HUD state is still that error.

### [MEDIUM] Claimed 30s OpenAI timeout is not implemented
- **File:line:** govori.py:870
- **Mера:** SEC-03
- **Что не так:** OpenAI client uses `timeout=5.0`, and per-request timeout scales only to 5-8s.
- **Почему:** this contradicts the stated 30s safety measure and turns normal slow transcriptions into retry storms.
- **Fix:** enforce the specified 30s timeout, or document and test a bounded duration-based timeout policy.

### [HIGH] Manual retry is not single-flight and can duplicate paste/send audio
- **File:line:** govori.py:1152
- **Mера:** SEC-03
- **Что не так:** repeated clicks can start multiple `_retry_transcription` daemon threads for the same `_retry_buffer`.
- **Почему:** `_retry_count` is not protected by a lock and there is no `_retry_in_progress`; `_hud_error_mode` changes asynchronously via `set_hud()`.
- **Fix:** guard retry with a locked in-flight flag and clear/disable retry before starting the worker.

### [MEDIUM] Retry path loses original mode semantics
- **File:line:** govori.py:1259
- **Mера:** SEC-03
- **Что не так:** retry success always calls `paste_text(text + " ")`.
- **Почему:** failed note-mode retry should classify/save a note; failed predict/auto-send retry should preserve predict/auto-send behavior, not paste raw text into the current cursor.
- **Fix:** store retry context with the buffer and dispatch success through the original mode pipeline.

### [MEDIUM] Permanent API errors are retried as if transient
- **File:line:** govori.py:1468
- **Mера:** SEC-03
- **Что не так:** all `APIStatusError` values return `None`, and callers treat `None` as retryable.
- **Почему:** 400/401/403 and many 4xx errors are non-retryable; current code wastes attempts and keeps sensitive audio buffered.
- **Fix:** return typed error classes/statuses and retry only timeout/connection/5xx/eligible 429 with bounded backoff.

### [MEDIUM] Privacy notice falsely says audio is not stored
- **File:line:** govori.py:1589
- **Mера:** SEC-04
- **Что не так:** note-mode starts `_save_note_audio_background()` and persists audio locally.
- **Почему:** onboarding says “Audio is not stored after transcription,” but code writes Opus files under `~/life/state/govori-audio/...`.
- **Fix:** update notice to disclose local audio retention, path, and retention policy, or disable persistence by default.

### [LOW] Privacy notice misses prediction text disclosure
- **File:line:** govori.py:2252
- **Mера:** SEC-04
- **Что не так:** predict mode sends transcribed text to chat completions, but onboarding only mentions Whisper and Claude classification.
- **Почему:** this is another cloud text-processing path, potentially to a configured `base_url`, and should be disclosed.
- **Fix:** include predict/rephrase API data flow and provider/base_url caveat in onboarding.

### [MEDIUM] CLI voice amend path bypasses microphone error handling
- **File:line:** govori.py:2700
- **Mера:** REL-01
- **Что не так:** `_record_until_enter()` creates and starts `sd.InputStream` without catching `PortAudioError`.
- **Почему:** mic missing/denied in `govori notes` can crash instead of producing the REL-01 failure path.
- **Fix:** wrap stream creation/start/close in the same mic error handling used by daemon recording.

## SEC-01 — clean

Общая оценка реализации фазы: gaps.
