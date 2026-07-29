"""Intent routing helpers for note-mode relay."""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import threading
from pathlib import Path

from loguru import logger

from . import config as cfg
from . import notes
from . import session_control


_BRAIN_CMD = [
    '/home/gen/brain/engine/.venv/bin/python',
    '/home/gen/brain/engine/query.py',
]
_INTENTS = {'note', 'ask', 'do'}
_DECISION_LOG = Path.home() / 'govori-notes' / 'index' / 'intent-decisions.jsonl'
_decision_log_lock = threading.Lock()


def _default_meta(base: dict) -> dict:
    meta = dict(base or {})
    meta.setdefault('intent', 'note')
    meta.setdefault('target', None)
    meta.setdefault('summary', meta.get('title') or 'note')
    meta.setdefault('confidence', 'high')
    return meta


def _strip_json(raw: str) -> str:
    raw = (raw or '').strip()
    if raw.startswith('```'):
        raw = re.sub('^```(?:json)?\\s*', '', raw)
        raw = re.sub('\\s*```\\s*$', '', raw)
    return raw


def classify_intent(text: str) -> dict:
    """Classify note metadata, then route it as note/ask/do."""
    try:
        base = notes.classify_note(text)
    except Exception as exc:
        logger.info(f'intent base classify error: {exc}')
        base = {'title': 'note', 'contexts': ['default'], 'type': 'other', 'urgency': 'low', 'tags': [], 'related_stuck': []}
    meta = _default_meta(base)
    try:
        if not cfg.NOTES_CFG:
            return meta
        client = notes._get_anthropic_client()
        if client is None:
            return meta
        valid_contexts = sorted(cfg.NOTES_CFG['valid_contexts'])
        system = f"""Ты роутер намерений для голосовой заметки пользователя.

Сначала уже была выполнена классификация заметки. Не повторяй её. Твоя задача:
определить намерение пользователя и вернуть STRICT JSON ONLY:
{{"intent": "note|ask|do", "target": "<one context key or null>", "summary": "<short human RU one-liner, max 90 chars>", "confidence": "high|low"}}

Контексты пользователя, используй target только из этих ключей:
{cfg.NOTES_CFG['contexts_desc']}

Правила:
- ask: вопросы и просьбы вспомнить/найти информацию в личном графе знаний:
  "сколько", "когда", "что по", "какой статус", "напомни мне что", "узнай".
- do: императивы, где нужно что-то сделать или делегировать:
  "сделай", "отправь", "напиши письмо", "поставь задачу", "собери отчёт",
  "напомни <кому-то>", "запроси".
- note: идеи, наблюдения, личные todo, решения и обычные заметки.
- confidence: "high" если тип однозначен; "low" только при реальных сомнениях — текст двусмысленный, обрывочный, или подходит под 2+ типа (тогда телефон спросит подтверждение). Не ставь "low" без веской причины.

target должен быть одним ключом из списка или null. summary — коротко по-русски, до 90 символов.
Верни только валидный JSON, без markdown и пояснений."""
        user = json.dumps(
            {
                'text': text,
                'base_meta': base,
                'valid_contexts': valid_contexts,
            },
            ensure_ascii=False,
        )
        resp = client.messages.create(
            model=cfg.NOTES_CFG['classifier_model'],
            max_tokens=160,
            temperature=0,
            system=system,
            messages=[{'role': 'user', 'content': user}],
        )
        data = json.loads(_strip_json(resp.content[0].text))
        intent = data.get('intent') if isinstance(data, dict) else None
        if intent not in _INTENTS:
            intent = 'note'
        target = data.get('target') if isinstance(data, dict) else None
        if target not in cfg.NOTES_CFG['valid_contexts']:
            target = None
        summary = str(data.get('summary') or meta.get('title') or 'note').strip()
        if len(summary) > 90:
            summary = summary[:87].rstrip() + '...'
        confidence = data.get('confidence') if isinstance(data, dict) else None
        if confidence not in ('high', 'low'):
            confidence = 'high'
        meta['intent'] = intent
        meta['target'] = target
        meta['summary'] = summary
        meta['confidence'] = confidence
        return meta
    except Exception as exc:
        logger.info(f'intent classify error: {exc}')
        meta['intent'] = 'note'
        meta['target'] = None
        meta['summary'] = meta.get('summary') or meta.get('title') or 'note'
        meta['confidence'] = 'high'
        return meta


def _node_excerpt(node: dict) -> str:
    title = str(node.get('title') or node.get('id') or 'untitled').strip()
    body = str(node.get('body') or '').strip()
    if len(body) > 600:
        body = body[:597].rstrip() + '...'
    neighbors = node.get('neighbors') or []
    if neighbors:
        neighbor_text = ', '.join(str(n) for n in neighbors[:6] if n)
        if neighbor_text:
            return f'### {title}\n{body}\nСвязи: {neighbor_text}'
    return f'### {title}\n{body}'


def _render_nodes(nodes: list[dict], limit: int = 6000) -> str:
    chunks = []
    total = 0
    for node in nodes:
        chunk = _node_excerpt(node)
        next_len = len(chunk) + (2 if chunks else 0)
        if total + next_len > limit:
            break
        chunks.append(chunk)
        total += next_len
    return '\n\n'.join(chunks)


def brain_answer(text: str) -> str:
    """Answer from the user's external brain graph."""
    cmd = [*_BRAIN_CMD, text, '--limit', '8', '--json']
    try:
        result = subprocess.run(
            cmd,
            timeout=25,
            capture_output=True,
            text=True,
            env=os.environ,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning(f'brain query timeout: {exc}')
        return 'Не смог обратиться к мозгу сейчас.'
    except Exception as exc:
        logger.warning(f'brain query failed: {exc}')
        return 'Не смог обратиться к мозгу сейчас.'
    if result.returncode != 0:
        logger.warning(f'brain query nonzero: code={result.returncode} stderr={result.stderr[:500]!r}')
        return 'Не смог обратиться к мозгу сейчас.'
    try:
        nodes = json.loads(result.stdout)
    except Exception as exc:
        logger.warning(f'brain query json parse failed: {exc}; stdout={result.stdout[:500]!r}')
        return 'Не смог обратиться к мозгу сейчас.'
    if not isinstance(nodes, list):
        logger.warning(f'brain query returned non-list: {type(nodes).__name__}')
        return 'Не смог обратиться к мозгу сейчас.'
    if not nodes:
        return 'Не нашёл в мозге данных по этому вопросу.'
    try:
        client = notes._get_anthropic_client()
        if client is None or not cfg.NOTES_CFG:
            return 'Не смог обратиться к мозгу сейчас.'
        context = _render_nodes(nodes)
        system = (
            'Отвечай на вопрос пользователя ТОЛЬКО на основе приведённых выдержек '
            'из его личного графа знаний. Кратко, 1-4 предложения, по-русски. '
            'Если данных недостаточно — честно скажи об этом. Не выдумывай.'
        )
        user = f'ВОПРОС:\n{text}\n\nВЫДЕРЖКИ ИЗ ГРАФА:\n{context}'
        resp = client.messages.create(
            model=cfg.NOTES_CFG['classifier_model'],
            max_tokens=500,
            temperature=0,
            system=system,
            messages=[{'role': 'user', 'content': user}],
        )
        return resp.content[0].text.strip()
    except Exception as exc:
        logger.warning(f'brain answer failed: {exc}')
        return 'Не смог обратиться к мозгу сейчас.'


def dispatch_command(text: str, target: str | None) -> str:
    """Phase-1 command dispatch stub."""
    # TODO Phase 2: route commands via Agent Mailbox (NATS) to the project agent.
    notes.save_or_merge_note(text, 0.0)
    project = target or 'не определён'
    return (
        f"Команда распознана (проект: {project}) и сохранена. "
        "Делегацию агенту проекта добавлю в следующей версии."
    )


def classify_do_action(text: str) -> dict:
    """Route a do-intent transcript to a direct executor (Phase 2.1).

    Currently only `session_ask` is implemented: send a message into one of
    the user's live Claude Code sessions via session-manager. Everything
    else falls through to `dispatch_command`'s note-and-stash stub.

    Returns {"action": "session_ask"|"other", "message": str|None,
    "candidates": [session_id, ...]}. `candidates` is ranked, best match
    first; empty if nothing plausible matched or no sessions are live.
    """
    default = {'action': 'other', 'message': None, 'candidates': []}
    sessions = session_control.list_sessions()
    if not sessions:
        return default
    session_ids = [s.get('id') for s in sessions if s.get('id')]
    if not session_ids:
        return default
    try:
        if not cfg.NOTES_CFG:
            return default
        client = notes._get_anthropic_client()
        if client is None:
            return default
        system = f"""Ты роутер действий для голосовой команды пользователя (тип "do" уже определён на предыдущем шаге).

Проверь: не просит ли пользователь отправить сообщение в одну из его АКТИВНЫХ Claude Code сессий (управляются через session-manager) — например "спроси у X: ...", "скажи сессии Y ...", "передай в X ...", "напиши в сессию про Z ...".

Если да — верни:
{{"action": "session_ask", "message": "<полезная нагрузка без маршрутизирующей фразы, НОРМАЛИЗОВАННАЯ: исправь очевидные огрехи распознавания речи, сохрани смысл, не выдумывай нового>", "candidates": ["<id сессии из списка ниже>", ...до 3, по релевантности упоминанию, пусто если ни одна не подходит]}}

Если это НЕ про голосовое управление сессиями — верни {{"action": "other", "message": null, "candidates": []}}.

Живые сессии:
{chr(10).join(session_ids)}

Верни только валидный JSON, без markdown и пояснений."""
        resp = client.messages.create(
            model=cfg.NOTES_CFG['classifier_model'],
            max_tokens=250,
            temperature=0,
            system=system,
            messages=[{'role': 'user', 'content': text}],
        )
        data = json.loads(_strip_json(resp.content[0].text))
        if not isinstance(data, dict):
            return default
        action = data.get('action') if data.get('action') in ('session_ask', 'other') else 'other'
        message = data.get('message') if isinstance(data.get('message'), str) else None
        candidates = [c for c in (data.get('candidates') or []) if c in session_ids]
        if action != 'session_ask':
            return default
        return {'action': action, 'message': message, 'candidates': candidates[:3]}
    except Exception as exc:
        logger.info(f'do-action classify error: {exc}')
        return default


def session_ask_execute(session_id: str, message: str) -> str:
    """Inject `message` into `session_id`'s pane via session-manager. Fire-and-forget."""
    tagged = f'[голос/Говори, возможна неточность распознавания] {message}'
    result = session_control.ask_session(session_id, tagged)
    if not result.get('ok', True) and 'error' in result:
        return f'Не смог достучаться до сессии {session_id}: {result["error"]}'
    return f'✓ отправлено в {session_id}'


def log_intent_decision(entry: dict) -> None:
    """Append a predicted-vs-chosen record for later accuracy analysis.

    One line per menu-mediated decision (note/ask/do type choice, or the
    session_ask target/cancel choice) — best-effort, never raises.
    """
    try:
        record = dict(entry)
        record.setdefault('ts', datetime.datetime.now().astimezone().isoformat(timespec='seconds'))
        _DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _decision_log_lock, _DECISION_LOG.open('a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception as exc:
        logger.info(f'intent decision log failed (non-fatal): {exc}')
