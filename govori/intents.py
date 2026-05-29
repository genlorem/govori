"""Intent routing helpers for note-mode relay."""
from __future__ import annotations

import json
import os
import re
import subprocess

from loguru import logger

from . import config as cfg
from . import notes


_BRAIN_CMD = [
    '/home/gen/brain/engine/.venv/bin/python',
    '/home/gen/brain/engine/query.py',
]
_INTENTS = {'note', 'ask', 'do'}


def _default_meta(base: dict) -> dict:
    meta = dict(base or {})
    meta.setdefault('intent', 'note')
    meta.setdefault('target', None)
    meta.setdefault('summary', meta.get('title') or 'note')
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
{{"intent": "note|ask|do", "target": "<one context key or null>", "summary": "<short human RU one-liner, max 90 chars>"}}

Контексты пользователя, используй target только из этих ключей:
{cfg.NOTES_CFG['contexts_desc']}

Правила:
- ask: вопросы и просьбы вспомнить/найти информацию в личном графе знаний:
  "сколько", "когда", "что по", "какой статус", "напомни мне что", "узнай".
- do: императивы, где нужно что-то сделать или делегировать:
  "сделай", "отправь", "напиши письмо", "поставь задачу", "собери отчёт",
  "напомни <кому-то>", "запроси".
- note: идеи, наблюдения, личные todo, решения и обычные заметки.

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
        meta['intent'] = intent
        meta['target'] = target
        meta['summary'] = summary
        return meta
    except Exception as exc:
        logger.info(f'intent classify error: {exc}')
        meta['intent'] = 'note'
        meta['target'] = None
        meta['summary'] = meta.get('summary') or meta.get('title') or 'note'
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
