---
phase: quick
plan: 260422-bgo
type: execute
wave: 1
depends_on: []
files_modified:
  - govori.py
autonomous: true
requirements: []
must_haves:
  truths:
    - "Quick tap (fn held < 200ms) never leaves recording stuck True"
    - "start_recording() aborts silently if fn-up already signalled cancel before the thread ran"
  artifacts:
    - path: "govori.py"
      provides: "Both race-condition fixes applied"
  key_links:
    - from: "cg_event_callback fn-up branch"
      to: "cancel_recording()"
      via: "background thread, unconditional on quick tap"
    - from: "start_recording()"
      to: "_state_lock cancelled check"
      via: "early-return guard before setting recording=True"
---

<objective>
Close the race condition where fn is released before the start_recording() background thread runs, leaving recording=True forever with the mic never stopping.

Purpose: A quick tap currently bypasses the cancel path entirely because the fn-up guard `if recording:` evaluates False before the thread sets recording=True. The mic stream starts regardless and can never be stopped.

Output: Two surgical edits to govori.py — one in cg_event_callback (fn-up branch) and one in start_recording().
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@/Users/genlorem/Projects/govori/govori.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Remove outer `if recording:` guard from fn-up quick-tap path</name>
  <files>govori.py</files>
  <action>
At line 2430–2439, the fn-up branch currently wraps both the quick-tap cancel and the stop_and_transcribe dispatch inside `if recording:`. The quick-tap cancel must fire regardless of recording state to handle the race.

Replace:
```python
    elif not is_down and prev_fn_down:
        if recording:
            held = time.time() - _fn_press_time
            if held < 0.20:
                threading.Thread(
                    target=lambda: cancel_recording(skip_hud=True, quiet=True),
                    daemon=True,
                ).start()
            else:
                threading.Thread(target=stop_and_transcribe, daemon=True).start()
```

With:
```python
    elif not is_down and prev_fn_down:
        held = time.time() - _fn_press_time
        if held < 0.20:
            # Always cancel on quick tap — covers race where start_recording
            # thread hasn't set recording=True yet.
            threading.Thread(
                target=lambda: cancel_recording(skip_hud=True, quiet=True),
                daemon=True,
            ).start()
        elif recording:
            threading.Thread(target=stop_and_transcribe, daemon=True).start()
```

The `elif recording:` on the stop path is safe — if recording is False here and held >= 0.20, the user held fn but never started (unusual edge case), and doing nothing is correct.
  </action>
  <verify>grep -n "elif not is_down and prev_fn_down" /Users/genlorem/Projects/govori/govori.py && grep -A8 "elif not is_down and prev_fn_down" /Users/genlorem/Projects/govori/govori.py</verify>
  <done>fn-up branch computes `held` unconditionally, quick-tap cancel fires without checking recording state, stop_and_transcribe guarded by `elif recording:`</done>
</task>

<task type="auto">
  <name>Task 2: Guard start_recording() against cancelled signal set before thread ran</name>
  <files>govori.py</files>
  <action>
At line 1376–1390, start_recording() currently resets `cancelled=False` unconditionally at line 1388, overwriting any cancel signal the fn-up handler deposited before this thread ran.

Insert an early-return guard after `if recording: return` (line 1377) and before the `if audio_stream is not None:` block. Also move the `cancelled=False` reset inside that guard so it only clears the flag on legitimate abort:

Replace:
```python
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
        _retry_count = 0
        audio_chunks = []
```

With:
```python
    with _state_lock:
        if recording:
            return
        if cancelled:                 # fn-up fired before we ran — abort silently
            cancelled = False         # reset flag for next recording
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
        _retry_count = 0
        audio_chunks = []
```

The `cancelled=False` reset inside the abort branch is needed because cancel_recording() also sets cancelled=True and expects it to be cleared by the next recording cycle.
  </action>
  <verify>grep -n "fn-up fired before we ran" /Users/genlorem/Projects/govori/govori.py</verify>
  <done>start_recording() returns without setting recording=True when cancelled is already True on entry; cancelled flag reset to False on abort path</done>
</task>

</tasks>

<threat_model>
Not applicable — local hotkey/threading fix, no trust boundary changes.
</threat_model>

<verification>
After both edits:
1. `python3 -c "import ast, sys; ast.parse(open('govori.py').read()); print('syntax ok')"` — no syntax errors
2. Manual smoke test: tap fn quickly (hold < 200ms) → HUD must not appear, mic must not stay on, next fn-hold must work normally
3. Normal hold (> 200ms) → transcription still fires as expected
</verification>

<success_criteria>
- Quick tap never leaves recording=True
- start_recording() silently aborts when fn-up beat it to the lock
- No regression on normal hold-to-dictate flow
- govori.py passes AST parse check
</success_criteria>

<output>
No SUMMARY file required for quick fixes.
</output>
