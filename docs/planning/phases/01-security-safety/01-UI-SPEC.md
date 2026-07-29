---
phase: 1
slug: security-safety
status: draft
shadcn_initialized: false
preset: none
created: 2026-04-17
---

# Phase 1 -- UI Design Contract

> Visual and interaction contract for the Security & Safety phase. This phase modifies an existing 32px native macOS HUD (NSPanel) and adds a terminal-based privacy notice to CLI onboarding. No web UI. No component library.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none (native macOS, PyObjC) |
| Preset | not applicable |
| Component library | AppKit / Quartz (PyObjC bindings) |
| Icon library | Unicode glyphs (system font) |
| Font | NSFont.systemFontOfSize (San Francisco, macOS system default) |

---

## Spacing Scale

Not applicable in the traditional sense. The HUD is a fixed 32x32px NSPanel. All spacing is pixel-exact within that constraint.

| Token | Value | Usage |
|-------|-------|-------|
| hud_size | 32px | HUD window width and height |
| hud_corner | 16px | Corner radius (hud_size / 2 = circle) |
| hud_x | 6px | Left offset from screen edge |
| hud_y | 0px | Bottom offset from screen edge |
| label_height | 18px | Text label frame height |
| label_y | 7px | Vertical centering: (32 - 18) / 2 |
| tooltip_gap | 4px | Gap between HUD circle and tooltip panel |
| tooltip_padding | 8px | Internal padding of tooltip text |

Exceptions: Tooltip panel width is dynamic (auto-sized to text content, max 240px).

---

## Typography

### HUD Icon Label

| Role | Size | Weight | Line Height | Font |
|------|------|--------|-------------|------|
| HUD icon glyph | 14px | regular (400) | 18px frame | NSFont.systemFontOfSize_(14) |

### HUD Tooltip

| Role | Size | Weight | Line Height | Font |
|------|------|--------|-------------|------|
| Tooltip text | 11px | regular (400) | 1.3 | NSFont.systemFontOfSize_(11) |

### CLI Onboarding (terminal)

| Role | ANSI style | Usage |
|------|------------|-------|
| Section header | `\033[33m` (yellow) | Step headers, consistent with existing onboarding |
| Body text | default terminal | Privacy notice body |
| Dim/secondary | `\033[2m` (dim) | Supplementary info, consistent with existing pattern |
| Emphasis | `\033[1m` (bold) | Service names (OpenAI, Anthropic) |
| Link/path | `\033[36m` (cyan) | URLs and file paths |

---

## Color

### HUD Modes (existing + new)

All colors use `NSColor.colorWithRed_green_blue_alpha_` on the HUD label text. Background is fixed at rgba(0.10, 0.10, 0.10, 0.85).

| Mode | Glyph | RGBA | Hex Approx | Status |
|------|-------|------|-----------|--------|
| recording | `●` | (1.0, 0.3, 0.3, 1.0) | #FF4D4D | existing |
| transcribing | `◎` | (1.0, 0.85, 0.3, 1.0) | #FFD94D | existing |
| predict | `✦` | (0.7, 0.4, 1.0, 1.0) | #B366FF | existing |
| note | `✎` | (0.4, 0.9, 0.6, 1.0) | #66E699 | existing |
| note_saved | `✓` | (0.4, 1.0, 0.5, 1.0) | #66FF80 | existing |
| note_error | `✗` | (1.0, 0.3, 0.3, 1.0) | #FF4D4D | existing |
| **error_retryable** | `↻` | (1.0, 0.85, 0.3, 1.0) | #FFD94D | **NEW** |
| **error_fatal** | `✗` | (1.0, 0.3, 0.3, 1.0) | #FF4D4D | **NEW** |

### Color Rationale for New Modes

- **error_retryable** uses yellow/amber (same as "transcribing") because it signals "action needed, not broken" -- the user can click to retry. The retry glyph `↻` differentiates it from transcribing's `◎`.
- **error_fatal** uses red (same as existing error) because the user cannot fix it from the HUD. The `✗` glyph is reused from `note_error`.

### Tooltip Colors

| Element | RGBA | Usage |
|---------|------|-------|
| Background | (0.15, 0.15, 0.15, 0.92) | Slightly lighter than HUD bg for visual separation |
| Text | (0.95, 0.95, 0.95, 1.0) | High contrast white on dark |
| Border | none | Clean edge, matches macOS tooltip conventions |

### CLI Privacy Notice Colors

Uses existing ANSI escape code conventions from SETUP_STRINGS -- no new colors introduced.

---

## Interaction Contract

### HUD Click Behavior

The current HUD sets `setIgnoresMouseEvents_(True)`. This must change conditionally:

| HUD Mode | Mouse Events | Click Action |
|----------|-------------|--------------|
| recording | ignored | none |
| transcribing | ignored | none |
| predict | ignored | none |
| note | ignored | none |
| note_saved | ignored | none |
| note_error | ignored | none |
| **error_retryable** | **accepted** | Re-transcribe last audio buffer |
| **error_fatal** | **accepted** | Show tooltip (if not auto-shown) |

Implementation: Toggle `setIgnoresMouseEvents_` in `set_hud()` based on mode. Add `mouseDown_` handler to the HUD window/container.

### HUD Tooltip Behavior

| Trigger | Behavior |
|---------|----------|
| error_retryable shown | Tooltip appears automatically after 1.5s, dismisses on click (which triggers retry) |
| error_fatal shown | Tooltip appears automatically after 0.5s, persists until next recording or 10s timeout |
| Hover over HUD in error state | Tooltip appears immediately |
| Successful retry | HUD transitions to "transcribing" mode, tooltip dismissed |
| Failed retry | HUD stays in error_retryable, tooltip updates with attempt count |

### Tooltip Panel Spec

| Property | Value |
|----------|-------|
| Type | NSPanel (borderless, non-activating) |
| Position | 4px right of HUD circle (x: 42, y: 0) |
| Width | Auto-sized to text, max 240px |
| Height | Auto-sized to text, min 24px |
| Corner radius | 6px |
| Background | rgba(0.15, 0.15, 0.15, 0.92) |
| Font | System 11px regular |
| Text color | rgba(0.95, 0.95, 0.95, 1.0) |
| Padding | 8px all sides |
| Animation | Fade in 0.2s ease-out |
| Z-order | Same level as HUD (NSFloatingWindowLevel + 1) |

### Pulse Animation Changes

| Mode | Animation |
|------|-----------|
| recording | Pulse (existing): opacity 1.0 -> 0.4, 0.8s, infinite |
| transcribing | Pulse (existing) |
| error_retryable | Slow pulse: opacity 1.0 -> 0.6, 1.2s, infinite (gentler to indicate waiting state) |
| error_fatal | No pulse (static) -- signals "stuck, needs attention outside the app" |

### Audio Buffer Retention for Retry

| Event | Buffer Action |
|-------|--------------|
| Recording starts | Clear previous buffer |
| Recording stops | Buffer retained in `audio_chunks` |
| Transcription succeeds | Buffer retained (overwritten on next recording) |
| Transcription fails (retryable) | Buffer retained for retry |
| Retry succeeds | Buffer retained (overwritten on next recording) |
| Retry fails | Buffer retained, retry counter incremented |
| Max retries (3) | Transition to error_fatal, buffer discarded |

---

## Copywriting Contract

### HUD Tooltip Messages

| Scenario | Copy (en) | Copy (ru) |
|----------|-----------|-----------|
| API timeout | "Transcription timed out. Click to retry." | "Транскрипция не ответила. Нажми для повтора." |
| API network error | "Connection failed. Click to retry." | "Нет соединения. Нажми для повтора." |
| API 5xx error | "Server error. Click to retry." | "Ошибка сервера. Нажми для повтора." |
| Retry attempt N | "Retrying... (attempt N/3)" | "Повтор... (попытка N/3)" |
| Retry exhausted | "Transcription failed. Try recording again." | "Не удалось распознать. Попробуй записать ещё раз." |
| No microphone | "No microphone found." | "Микрофон не найден." |
| Mic permission denied | "Microphone access denied." | "Доступ к микрофону запрещён." |
| Accessibility revoked | "Accessibility revoked -- hotkeys disabled." | "Доступ отозван -- горячие клавиши отключены." |

### CLI Privacy Notice

Inserted as a new step between Step 1 (API Keys) and Step 2 (Accessibility Permission). Step numbering changes to 4 total steps.

**English (`privacy_notice`):**
```
\033[33m  -- Step 2/4 -- Privacy Notice --------------------------------\033[0m

  Govori sends data to cloud APIs for processing:

    \033[1mVoice audio\033[0m  -->  OpenAI Whisper API (speech-to-text)
    \033[1mNote text\033[0m    -->  Anthropic Claude API (classification)

  \033[2mAudio is not stored after transcription. Notes are processed
  but not retained by Anthropic. Keys stay local on your machine.\033[0m

```

**Russian (`privacy_notice`):**
```
\033[33m  -- Шаг 2/4 -- Конфиденциальность ----------------------------\033[0m

  Govori отправляет данные в облачные API для обработки:

    \033[1mАудио голоса\033[0m  -->  OpenAI Whisper API (распознавание речи)
    \033[1mТекст заметок\033[0m -->  Anthropic Claude API (классификация)

  \033[2mАудио не сохраняется после транскрипции. Заметки обрабатываются,
  но не хранятся на серверах Anthropic. Ключи остаются на вашем устройстве.\033[0m

```

**Step renumbering:**
- Step 1/4: API Keys (was 1/3)
- Step 2/4: Privacy Notice (NEW)
- Step 3/4: Accessibility Permission (was 2/3)
- Step 4/4: How to Use (was 3/3)

No confirmation prompt after privacy notice -- display is informational per D-02. Flow continues automatically to Step 3.

### Terminal Startup Warning Messages

| Scenario | Copy (en) | Copy (ru) |
|----------|-----------|-----------|
| No input device at startup | "Warning: no microphone detected. Plug one in before recording." | "Предупреждение: микрофон не обнаружен. Подключи перед записью." |

Uses existing terminal print pattern: `print("symbol message", flush=True)` with `!` prefix for warnings.

---

## State Machine: HUD Modes

```
                    +-----------+
                    |   idle    |  (HUD hidden)
                    +-----+-----+
                          |
                    fn pressed
                          |
                    +-----v-----+
                    | recording |  ● red, pulse
                    +-----+-----+
                          |
                    fn released
                          |
                    +-----v-------+
                    | transcribing|  ◎ yellow, pulse
                    +-----+-------+
                          |
              +-----------+-----------+
              |           |           |
           success    retryable    fatal error
              |        error       (no mic, etc)
              |           |           |
        +-----v-----+ +--v-----------v--+
        |   idle     | |error_retryable | error_fatal |
        | (or note/  | |  ↻ yellow      |  ✗ red     |
        |  predict)  | |  slow pulse    |  static    |
        +------------+ |  clickable     |  tooltip   |
                       +--+-------------+--+---------+
                          |                |
                        click            next fn press
                          |                |
                    +-----v-------+   +----v----+
                    | transcribing|   |  idle   |
                    +-------------+   +---------+
```

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| not applicable | none | native macOS app, no package registry |

---

## Design Principles Referenced

1. **Visibility of system status** (Nielsen): HUD dot is always-visible feedback. Error states must be immediately distinguishable from normal operation through color AND glyph change, not color alone.

2. **Error recovery** (Nielsen): Retryable errors offer a direct action (click to retry) rather than requiring the user to re-record. This preserves the audio buffer investment.

3. **Recognition over recall**: Error tooltips describe the problem AND the action in one line. The user does not need to remember what the HUD states mean.

4. **Minimal interruption for informational content**: Privacy notice is non-blocking (D-02), consistent with the "zero UI chrome" philosophy. It informs without demanding interaction.

5. **Graceful degradation**: Fatal errors (no mic, accessibility revoked) do not crash or exit. The app continues running and auto-recovers when conditions change (D-11, D-13).

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
