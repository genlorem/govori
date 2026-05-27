"""Note classification, persistence, merge checks, and note-mode pipeline."""
from __future__ import annotations
import datetime
import json
import os
import re
import threading
import time
from pathlib import Path
import av
import numpy as np
from loguru import logger
try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None
from . import config as cfg
try:
    from .hud import _tooltip, set_hud
except Exception:
    # Headless context (VPS relay): no HUD — replace with no-ops so the
    # note pipeline (transcribe → classify → save) works without macOS.
    def set_hud(*args, **kwargs):
        return None

    def _tooltip(*args, **kwargs):
        return ""
from .state import PERMANENT_API_ERROR, stash_retry_buffer
from .transcribe import _is_hallucination, transcribe_with_fallback
VALID_TYPES = {'idea', 'commitment', 'observation', 'todo', 'decision', 'question', 'other'}
VALID_URGENCY = {'low', 'medium', 'high'}
_anthropic_client = None

def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    if Anthropic is None:
        logger.error('anthropic package not installed - run: pip install anthropic')
        return None
    key = os.environ.get('ANTHROPIC_API_KEY')
    if not key:
        logger.error('ANTHROPIC_API_KEY not set - check ~/.config/govori/env')
        return None
    _anthropic_client = Anthropic(api_key=key)
    return _anthropic_client

def _save_note_audio_background(audio, duration_sec):
    """Persist recorded audio as compressed Opus for later recall/verification."""
    try:
        now = datetime.datetime.now()
        date_dir = Path.home() / 'life' / 'state' / 'govori-audio' / now.strftime('%Y-%m-%d')
        date_dir.mkdir(parents=True, exist_ok=True)
        stem = now.strftime('%H%M%S') + f'_{int(round(duration_sec))}s'
        out_path = date_dir / f'{stem}.opus'
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        audio_n = audio / peak * 0.9 if peak > 0 else audio
        audio_int16 = (audio_n * 32767).astype(np.int16)
        container = av.open(str(out_path), mode='w', format='ogg')
        stream = container.add_stream('libopus', rate=cfg.SAMPLE_RATE, layout='mono')
        stream.bit_rate = 32000
        frame = av.AudioFrame.from_ndarray(audio_int16.reshape(1, -1), format='s16', layout='mono')
        frame.rate = cfg.SAMPLE_RATE
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
        container.close()
        size_kb = out_path.stat().st_size / 1024
        logger.success(f'audio saved: {out_path.name} ({size_kb:.1f} KB)')
    except Exception as e:
        logger.warning(f'audio-save failed (non-fatal): {e}')

def _note_pipeline_background(audio, duration_sec):
    """Full note pipeline: transcribe -> filter -> classify -> save. No HUD updates."""
    threading.Thread(target=lambda a=audio, d=duration_sec: _save_note_audio_background(a, d), daemon=True).start()
    text = transcribe_with_fallback(audio, duration_sec, model_override=cfg.CONFIG.note_model)
    if text is PERMANENT_API_ERROR:
        set_hud(True, mode='error_fatal', tooltip=_tooltip('api_network'))
        return
    if text is None:
        stash_retry_buffer([audio], {'note_mode': True, 'predict_mode': False, 'auto_send': False, 'duration': duration_sec})
        set_hud(True, mode='error_retryable', tooltip=_tooltip('api_network'))
        return
    if _is_hallucination(text):
        logger.bind(event='hallucination').info(f'hallucination filtered: {text}')
        return
    if not text:
        logger.debug('Empty transcript')
        return
    logger.bind(event='transcript').info(text)
    save_or_merge_note(text, duration_sec)

def _sanitize_slug(s, maxlen=40):
    s = (s or 'note').strip().lower()
    s = re.sub('[^a-z0-9]+', '-', s)
    s = re.sub('-+', '-', s).strip('-')
    return (s or 'note')[:maxlen]

def _validate_meta(data):
    """Coerce classifier output into the schema, dropping invalid values."""
    if not cfg.NOTES_CFG:
        return data
    contexts = data.get('contexts') or []
    if isinstance(contexts, str):
        contexts = [contexts]
    contexts = [c for c in contexts if c in cfg.NOTES_CFG['valid_contexts']]
    if not contexts:
        contexts = [next(iter(cfg.NOTES_CFG['valid_contexts']))] if cfg.NOTES_CFG['valid_contexts'] else ['default']
    type_ = data.get('type', 'other')
    if type_ not in VALID_TYPES:
        type_ = 'other'
    urgency = data.get('urgency', 'low')
    if urgency not in VALID_URGENCY:
        urgency = 'low'
    tags = data.get('tags') or []
    if isinstance(tags, str):
        tags = [tags]
    tags = [str(t).strip().lower() for t in tags if t][:4]
    related = data.get('related_stuck') or []
    if isinstance(related, str):
        related = [related]
    related = [r for r in related if r in cfg.NOTES_CFG['valid_stuck']]
    title = str(data.get('title') or 'note').strip()
    return {'title': title, 'contexts': contexts, 'type': type_, 'urgency': urgency, 'tags': tags, 'related_stuck': related}

def segment_by_context(text, contexts):
    """Разбить текст заметки на секции '## <context>' когда затронуто
    несколько проектов. Наследует временные/приоритетные маркеры («завтра»,
    «срочно», «до пятницы») из общего начала ко всем секциям — они относятся
    ко всем упомянутым проектам пока явно не переопределены.

    Fallback: если contexts пуст или содержит 1 элемент — возвращает текст
    без изменений. Если Haiku недоступен или ответ невалидный — возвращает
    оригинал. Никогда не блокирует pipeline.
    """
    if not text or len(contexts) < 2:
        return text
    if cfg.NOTES_CFG is None:
        return text
    client = _get_anthropic_client()
    if client is None:
        return text
    contexts_desc = cfg.NOTES_CFG['contexts_desc']
    contexts_list = ', '.join(contexts)
    system = f'Ты структурируешь многотематическую голосовую заметку.\n\nНа входе — один связный текст заметки, в котором пользователь последовательно\nговорит о нескольких проектах. Твоя задача: разбить текст на секции\nпо проектам, НЕ теряя информацию.\n\nКОНТЕКСТЫ ПОЛЬЗОВАТЕЛЯ:\n{contexts_desc}\n\nВ ЭТОЙ ЗАМЕТКЕ ЗАТРОНУТЫ: {contexts_list}\n\nПРАВИЛА:\n1. Для каждого контекста из списка создай секцию с заголовком `## <context_key>`\n   (ровно тот ключ что в списке выше — marquiz, persona, skvo и т.д., не русские названия).\n2. В каждую секцию помести фрагмент текста, относящийся к этому контексту.\n3. Секции располагай в том порядке, как контексты упоминались в тексте.\n4. НЕ меняй слова пользователя. НЕ переписывай. НЕ сокращай. НЕ добавляй.\n5. НАСЛЕДОВАНИЕ временных/приоритетных маркеров:\n   - Если в начале заметки есть маркер типа «завтра», «срочно», «до пятницы»,\n     «в первую очередь» и т.п., и он явно относится к нескольким упомянутым\n     проектам — повтори этот маркер в каждой релевантной секции.\n   - Если маркер сказан ЯВНО про один конкретный пункт (например, «...проверить\n     их завтра» — только про документы Наташи) — оставляй его ТОЛЬКО в той секции.\n   - Если не уверен к скольки проектам относится маркер — оставь только там\n     где он изначально был сказан.\n6. Разговорные связки ("А ещё", "И ещё нужно", "Так ещё") оставляй в тех\n   секциях где они изначально были — не теряй интонацию переключения.\n7. Если какой-то контекст из списка фактически не упоминается в тексте —\n   НЕ создавай для него секцию (лучше вернуть меньше секций чем пустые).\n\nВерни ТОЛЬКО текст с секциями, без пояснений, кавычек, markdown-обёрток.\nНе добавляй преамбулу перед первой секцией `##` — заголовок должен быть\nпервой строкой.'
    try:
        resp = client.messages.create(model=cfg.NOTES_CFG['classifier_model'], max_tokens=max(800, len(text) * 3), temperature=0, system=system, messages=[{'role': 'user', 'content': text}])
        segmented = resp.content[0].text.strip()
        if segmented.startswith('```'):
            segmented = re.sub('^```(?:\\w+)?\\s*', '', segmented)
            segmented = re.sub('\\s*```\\s*$', '', segmented)
        if not segmented.startswith('## '):
            logger.info(f'  [segment] skipped — no section headers in output')
            return text
        if len(segmented) < len(text) * 0.7 or len(segmented) > len(text) * 2.5:
            logger.info(f'  [segment] skipped — length delta suspicious (orig {len(text)}, segmented {len(segmented)})')
            return text
        logger.info(f"  [segment] split into {segmented.count('## ')} section(s)")
        return segmented
    except Exception as e:
        logger.info(f'  [segment] failed (non-fatal): {e}')
        return text

def classify_note(text):
    """Classify transcribed note via Claude. Returns validated meta dict."""
    if not cfg.NOTES_CFG:
        return {'title': 'note', 'contexts': ['default'], 'type': 'other', 'urgency': 'low', 'tags': [], 'related_stuck': [], 'review': True}
    anthropic_client = _get_anthropic_client()
    if anthropic_client is None:
        return {'title': 'note', 'contexts': ['default'], 'type': 'other', 'urgency': 'low', 'tags': [], 'related_stuck': [], 'review': True}
    stuck_block = ''
    if cfg.NOTES_CFG['stuck_desc']:
        stuck_block = f"\nUser's ongoing stuck tasks (link note to one if relevant):\n{cfg.NOTES_CFG['stuck_desc']}\n"
    system = f"""You classify voice notes for a user with multiple contexts.\n\nUser's contexts (use these exact keys):\n{cfg.NOTES_CFG['contexts_desc']}\n{stuck_block}\nGiven a transcribed note, return STRICT JSON ONLY with these fields:\n- title: 2-5 word slug in latin kebab-case (e.g. "work-deploy-issue"). When\n  the note spans multiple contexts, pick a title that reflects the PRIMARY\n  (first-mentioned) context, not a generic summary.\n- contexts: array of ALL applicable context keys. Return MULTIPLE entries\n  when the note clearly mentions distinct projects. Better to over-tag\n  than under-tag: if the user talks about 3 projects, return all 3 keys.\n  Order: first-mentioned first (this becomes the "primary" context).\n- type: one of [idea, commitment, observation, todo, decision, question, other]\n- urgency: one of [low, medium, high]\n- tags: 1-4 short lowercase tags (free-form)\n- related_stuck: array with zero or more stuck task keys (only if relevant)\n\nReturn ONLY valid JSON, no markdown, no commentary."""
    try:
        resp = anthropic_client.messages.create(model=cfg.NOTES_CFG['classifier_model'], max_tokens=400, temperature=0, system=system, messages=[{'role': 'user', 'content': text}])
        raw = resp.content[0].text.strip()
        if raw.startswith('```'):
            raw = re.sub('^```(?:json)?\\s*', '', raw)
            raw = re.sub('\\s*```\\s*$', '', raw)
        data = json.loads(raw)
        return _validate_meta(data)
    except Exception as e:
        logger.info(f'Classify error: {e}')
        return {'title': 'note', 'contexts': ['default'], 'type': 'other', 'urgency': 'low', 'tags': [], 'related_stuck': [], 'review': True}

def _resolve_path(template, now):
    """Resolve path template with {year}, {month}, ~ expansion."""
    s = template.replace('{year}', now.strftime('%Y')).replace('{month}', now.strftime('%m'))
    return Path(os.path.expanduser(s))

def save_as_note(text, duration_sec, silent=False):
    """Classify + write markdown file + append to recent index."""
    if not cfg.NOTES_CFG:
        logger.info('notes plugin not configured')
        return
    try:
        meta = classify_note(text)
        now = datetime.datetime.now().astimezone()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H%M')
        slug = _sanitize_slug(meta['title'])
        note_id = f'{date_str}_{time_str}_{slug}'
        target_dir = _resolve_path(cfg.NOTES_CFG['output_dir'], now)
        target_dir.mkdir(parents=True, exist_ok=True)
        note_path = target_dir / f'{note_id}.md'
        fm_lines = ['---', f'id: {note_id}', f"created: {now.isoformat(timespec='seconds')}", 'source: voice', f'duration_sec: {int(round(duration_sec))}', f"contexts: {json.dumps(meta['contexts'], ensure_ascii=False)}", f"type: {meta['type']}", f"urgency: {meta['urgency']}", f"tags: {json.dumps(meta['tags'], ensure_ascii=False)}", f"related_stuck: {json.dumps(meta['related_stuck'], ensure_ascii=False)}"]
        if meta.get('review'):
            fm_lines.append('review: true')
        fm_lines.append('---')
        fm_lines.append('')
        fm_lines.append(text.strip())
        fm_lines.append('')
        note_path.write_text('\n'.join(fm_lines), encoding='utf-8')
        index_path = _resolve_path(cfg.NOTES_CFG['index_file'], now)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_entry = {'id': note_id, 'created': now.isoformat(timespec='seconds'), 'path': str(note_path), 'contexts': meta['contexts'], 'type': meta['type'], 'urgency': meta['urgency'], 'related_stuck': meta['related_stuck'], 'summary': text.strip()[:200]}
        with index_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(index_entry, ensure_ascii=False) + '\n')
        logger.info(f"✎ saved: {note_path.name} [{', '.join(meta['contexts'])}] {meta['type']}/{meta['urgency']}")
        if not silent:
            set_hud(True, 'note_saved')
    except Exception as e:
        logger.info(f'save_as_note error: {e}')
        if not silent:
            set_hud(True, 'note_error')
    if not silent:

        def _hide():
            time.sleep(1.2)
            set_hud(False)
        threading.Thread(target=_hide, daemon=True).start()
MERGE_WINDOW_HOURS = 6
MERGE_CONFIDENCE_THRESHOLD = 0.85

def _find_merge_candidates(contexts, hours=MERGE_WINDOW_HOURS):
    """Return recent index entries matching context, within time window."""
    if not cfg.NOTES_CFG or not contexts:
        return []
    cutoff = datetime.datetime.now().astimezone() - datetime.timedelta(hours=hours)
    entries = _read_index_entries(limit=20)
    out = []
    ctx_set = set(contexts)
    for e in entries:
        try:
            created = datetime.datetime.fromisoformat(e.get('created', ''))
        except Exception:
            continue
        if created < cutoff:
            continue
        if not set(e.get('contexts') or []) & ctx_set:
            continue
        if not Path(e.get('path', '')).exists():
            continue
        out.append(e)
    return out

def _decide_merge(new_text, candidates):
    """Ask Haiku whether new_text continues one of candidates.
    Returns dict: {action: 'new'|'merge', target_id, confidence, reason}."""
    if not candidates:
        return {'action': 'new', 'target_id': None, 'confidence': 1.0, 'reason': 'no candidates'}
    anthropic_client = _get_anthropic_client()
    if anthropic_client is None:
        return {'action': 'new', 'target_id': None, 'confidence': 0.0, 'reason': 'no anthropic'}
    cand_block = '\n'.join((f"[{i}] id={e['id']}  ({e.get('type', '')}/{e.get('urgency', '')})  {e.get('summary', '')[:160]}" for i, e in enumerate(candidates)))
    system = 'You decide whether a new voice note is a CONTINUATION of an existing recent note or a NEW standalone thought.\n\nRules:\n- MERGE only if the new text clearly extends, corrects, or adds detail to ONE existing note on the SAME specific topic.\n- If the new text introduces a different subject, decision, or action — it\'s NEW.\n- When in doubt — prefer NEW. A false merge silently loses information; a false new just creates one extra file.\n\nReturn STRICT JSON only:\n{"action": "new" | "merge", "target_index": <int or null>, "confidence": <0.0-1.0>, "reason": "<short>"}'
    user = f'EXISTING RECENT NOTES:\n{cand_block}\n\nNEW TEXT:\n{new_text}'
    try:
        resp = anthropic_client.messages.create(model=cfg.NOTES_CFG['classifier_model'], max_tokens=200, temperature=0, system=system, messages=[{'role': 'user', 'content': user}])
        raw = resp.content[0].text.strip()
        if raw.startswith('```'):
            raw = re.sub('^```(?:json)?\\s*', '', raw)
            raw = re.sub('\\s*```\\s*$', '', raw)
        data = json.loads(raw)
        action = data.get('action', 'new')
        idx = data.get('target_index')
        conf = float(data.get('confidence', 0.0))
        reason = data.get('reason', '')
        target_id = None
        if action == 'merge' and isinstance(idx, int) and (0 <= idx < len(candidates)):
            target_id = candidates[idx]['id']
        else:
            action = 'new'
        return {'action': action, 'target_id': target_id, 'confidence': conf, 'reason': reason, 'candidate': candidates[idx] if target_id else None}
    except Exception as e:
        logger.info(f'merge decision error: {e}')
        return {'action': 'new', 'target_id': None, 'confidence': 0.0, 'reason': str(e)}

def _confirm_merge(decision, new_text):
    """Hook for user confirmation. Currently auto-resolves by threshold.
    Future: will show HUD panel and wait for user choice.
    Returns final decision dict (same shape)."""
    if decision['action'] == 'merge' and decision['confidence'] >= MERGE_CONFIDENCE_THRESHOLD:
        return decision
    return {'action': 'new', 'target_id': None, 'confidence': decision['confidence'], 'reason': f"below threshold ({decision['confidence']:.2f}) — " + decision.get('reason', '')}

def _apply_merge_append(candidate, new_text, duration_sec):
    """Append new_text as a timestamped block to the candidate's markdown file."""
    path = Path(candidate['path'])
    now = datetime.datetime.now().astimezone()
    ts_short = now.strftime('%H:%M')
    original = path.read_text(encoding='utf-8')
    fm_lines, body = _split_frontmatter(original)
    if fm_lines:
        fm_lines = _update_frontmatter_amended(fm_lines, now.isoformat(timespec='seconds'))
    appended = body.rstrip() + f'\n\n## {ts_short} (voice)\n{new_text.strip()}\n'
    if fm_lines:
        path.write_text('\n'.join(fm_lines) + '\n\n' + appended, encoding='utf-8')
    else:
        path.write_text(appended, encoding='utf-8')
    try:
        index_path = _resolve_path(cfg.NOTES_CFG['index_file'], now)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        merge_entry = {'id': f"{candidate['id']}+merge_{now.strftime('%H%M')}", 'created': now.isoformat(timespec='seconds'), 'path': str(path), 'contexts': candidate.get('contexts', []), 'type': candidate.get('type', ''), 'urgency': candidate.get('urgency', ''), 'merged_into': candidate['id'], 'summary': new_text.strip()[:200]}
        with index_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(merge_entry, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.info(f'(merge index write failed: {e})')
    logger.info(f'⇪ merged into: {path.name} (conf n/a)')

def save_or_merge_note(text, duration_sec):
    """Entry point: classify → merge-check → either merge or save as new.

    Returns a result dict for callers that need it (e.g. server.py):
        {'action': 'merged'|'saved', 'meta': {...}, 'path': str, 'note_id': str}
    or None if NOTES_CFG is missing or an exception bubbled up.
    Existing callers (mac daemon, CLI) ignore the return value.
    """
    if not cfg.NOTES_CFG:
        logger.info('notes plugin not configured')
        return None
    try:
        meta = classify_note(text)
        if len(meta.get('contexts', [])) > 1:
            text = segment_by_context(text, meta['contexts'])
        candidates = _find_merge_candidates(meta['contexts'])
        decision = _decide_merge(text, candidates)
        decision = _confirm_merge(decision, text)
        if decision['action'] == 'merge' and decision.get('target_id'):
            cand = decision.get('candidate') or next((c for c in candidates if c['id'] == decision['target_id']), None)
            if cand:
                _apply_merge_append(cand, text, duration_sec)
                return {'action': 'merged', 'meta': meta, 'path': cand.get('path', ''), 'note_id': cand.get('id', '')}
        path, note_id = _save_note_with_meta(text, duration_sec, meta)
        return {'action': 'saved', 'meta': meta, 'path': path, 'note_id': note_id}
    except Exception as e:
        logger.info(f'save_or_merge_note error: {e}')
        return None

def _save_note_with_meta(text, duration_sec, meta):
    """Write note using a pre-computed meta dict (avoids re-classifying)."""
    now = datetime.datetime.now().astimezone()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H%M')
    slug = _sanitize_slug(meta['title'])
    note_id = f'{date_str}_{time_str}_{slug}'
    target_dir = _resolve_path(cfg.NOTES_CFG['output_dir'], now)
    target_dir.mkdir(parents=True, exist_ok=True)
    note_path = target_dir / f'{note_id}.md'
    fm_lines = ['---', f'id: {note_id}', f"created: {now.isoformat(timespec='seconds')}", 'source: voice', f'duration_sec: {int(round(duration_sec))}', f"contexts: {json.dumps(meta['contexts'], ensure_ascii=False)}", f"type: {meta['type']}", f"urgency: {meta['urgency']}", f"tags: {json.dumps(meta['tags'], ensure_ascii=False)}", f"related_stuck: {json.dumps(meta['related_stuck'], ensure_ascii=False)}"]
    if meta.get('review'):
        fm_lines.append('review: true')
    fm_lines.append('---')
    fm_lines.append('')
    fm_lines.append(text.strip())
    fm_lines.append('')
    note_path.write_text('\n'.join(fm_lines), encoding='utf-8')
    index_path = _resolve_path(cfg.NOTES_CFG['index_file'], now)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_entry = {'id': note_id, 'created': now.isoformat(timespec='seconds'), 'path': str(note_path), 'contexts': meta['contexts'], 'type': meta['type'], 'urgency': meta['urgency'], 'related_stuck': meta['related_stuck'], 'summary': text.strip()[:200]}
    with index_path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(index_entry, ensure_ascii=False) + '\n')
    logger.info(f"✎ saved: {note_path.name} [{', '.join(meta['contexts'])}] {meta['type']}/{meta['urgency']}")
    return (str(note_path), note_id)

def _read_index_entries(limit=30):
    if not cfg.NOTES_CFG:
        return []
    entries = []
    now = datetime.datetime.now()
    seen = set()
    for months_back in range(0, 12):
        d = now - datetime.timedelta(days=30 * months_back)
        path = _resolve_path(cfg.NOTES_CFG['index_file'], d)
        if not path.exists() or str(path) in seen:
            continue
        seen.add(str(path))
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except Exception:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if not entry.get('path') or not entry.get('summary'):
                continue
            entries.append(entry)
        if len(entries) >= limit * 3:
            break
    entries.sort(key=lambda e: e.get('created', ''), reverse=True)
    return entries[:limit]

def _split_frontmatter(md):
    """Returns (frontmatter_lines, body)."""
    lines = md.splitlines()
    if not lines or lines[0].strip() != '---':
        return ([], md)
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            end = i
            break
    if end is None:
        return ([], md)
    return (lines[:end + 1], '\n'.join(lines[end + 1:]).lstrip('\n'))

def _update_frontmatter_amended(fm_lines, timestamp):
    """Add or extend `amended:` list in frontmatter."""
    for i, line in enumerate(fm_lines):
        if line.startswith('amended:'):
            try:
                arr = json.loads(line.split(':', 1)[1].strip())
                if not isinstance(arr, list):
                    arr = []
            except Exception:
                arr = []
            arr.append(timestamp)
            fm_lines[i] = f'amended: {json.dumps(arr, ensure_ascii=False)}'
            return fm_lines
    fm_lines.insert(-1, f'amended: {json.dumps([timestamp], ensure_ascii=False)}')
    return fm_lines
