"""Glossary-driven post-correction of Whisper transcripts (Layer 1).

Whisper's `prompt` is capped at ~224 tokens, so the domain vocabulary can't all
fit there. This module runs the FULL glossary (terms.md + people.md + a growing
misrecognition map) through Claude Haiku after transcription to fix garbled
project names, tools, and people — handling Russian inflection, which a naive
find-replace can't.

The corrector is also the detector: every edit Haiku makes is logged to
`~/life/state/govori-corrections.jsonl`, feeding the review loop (Layer 2).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from loguru import logger

from . import config as cfg

CONFIG_DIR = Path.home() / ".config" / "govori"
TERMS_FILE = CONFIG_DIR / "terms.md"
PEOPLE_FILE = CONFIG_DIR / "people.md"
# Misrecognition map grown by the /review loop: {"ThrillScale": "Tailscale", ...}
CORRECTIONS_MAP = CONFIG_DIR / "corrections.json"
# Append-only audit log of every edit Haiku makes (Layer 2 input)
CORRECTIONS_LOG = Path.home() / "life" / "state" / "govori-corrections.jsonl"

_glossary_cache: str | None = None
_glossary_mtime: float = 0.0


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def _load_corrections_map() -> dict[str, str]:
    if not CORRECTIONS_MAP.exists():
        return {}
    try:
        return json.loads(CORRECTIONS_MAP.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("corrections.json unreadable: {}", exc)
        return {}


def _build_glossary() -> str:
    """Assemble the full glossary string for the Haiku system prompt.

    Unlike whisper_prompt this has NO length limit — include the people context
    lines verbatim (they help Haiku disambiguate), plus the learned map.
    """
    parts: list[str] = []
    terms = _read_lines(TERMS_FILE)
    if terms:
        parts.append("КАНОНИЧЕСКИЕ ТЕРМИНЫ/ПРОЕКТЫ/КОМПАНИИ:\n" + "\n".join(terms))
    people = _read_lines(PEOPLE_FILE)
    if people:
        parts.append("ЛЮДИ (имя — кто это):\n" + "\n".join(people))
    cmap = _load_corrections_map()
    if cmap:
        pairs = "\n".join(f"{k} → {v}" for k, v in cmap.items())
        parts.append("ИЗВЕСТНЫЕ ОШИБКИ РАСПОЗНАВАНИЯ (искажение → правильно):\n" + pairs)
    return "\n\n".join(parts)


def _glossary() -> str:
    """Cached glossary, invalidated when any source file changes."""
    global _glossary_cache, _glossary_mtime
    mtimes = [p.stat().st_mtime for p in (TERMS_FILE, PEOPLE_FILE, CORRECTIONS_MAP) if p.exists()]
    newest = max(mtimes) if mtimes else 0.0
    if _glossary_cache is None or newest > _glossary_mtime:
        _glossary_cache = _build_glossary()
        _glossary_mtime = newest
    return _glossary_cache


_SYSTEM = """Ты — функция исправления доменных терминов в русской голосовой транскрипции.

На вход — расшифровка речи пользователя. В ней Whisper часто коверкает названия проектов, компаний, инструментов и фамилии в фонетическую кашу. Твоя ЕДИНСТВЕННАЯ задача — заменить искажённые доменные термины на канонические из глоссария.

ЖЁСТКИЕ ПРАВИЛА:
- Исправляй ТОЛЬКО доменные сущности: имена людей, названия проектов/компаний/инструментов/мест, технические термины из глоссария.
- СОХРАНЯЙ грамматическую форму (падеж, число): «веб-зальным» → «вип-зальным», а не «ВИП-зал». Меняешь только узнаваемый корень/имя, окончание оставляешь.
- НИКОГДА не добавляй и не убирай слова. Замена должна быть примерно той же длины. НЕ раскрывай аббревиатуры в полные фразы («ПО» оставь «ПО», не превращай в «отечественное ПО»).
- НЕ перефразируй, НЕ меняй смысл, НЕ исправляй грамматику/пунктуацию обычных слов, НЕ переводи.
- Если сомневаешься, что слово — это доменный термин, НЕ трогай его.
- Обычные русские слова, не входящие в глоссарий, не трогай никогда.

Верни СТРОГО JSON без markdown — ТОЛЬКО список замен, НЕ переписывай текст целиком:
{"edits": [{"from": "<точная подстрока как в тексте>", "to": "<канонический вариант с тем же окончанием>"}]}
- "from" — точная подстрока КАК ОНА ЕСТЬ в тексте (с тем же регистром и окончанием), чтобы её можно было найти и заменить программно.
- Если правок нет — {"edits": []}.
- НЕ возвращай исходный или исправленный текст, только массив edits."""


def _apply_map(text: str) -> tuple[str, list[dict]]:
    """Deterministic word-boundary replacement from the learned corrections map.

    Instant (no network). Word boundaries (Unicode-aware) prevent corrupting
    innocent words that merely contain a key as a substring — e.g. mapping
    'скво'→'SKVO' must NOT touch 'сквозь'. Inflected variants are caught by the
    Haiku pass and then added to the map as their own exact entries over time.
    Longest keys first so multi-word entries win over their fragments.
    """
    cmap = _load_corrections_map()
    corrected = text
    edits: list[dict] = []
    for frm in sorted(cmap, key=len, reverse=True):
        to = cmap[frm]
        if not frm or not to or frm == to:
            continue
        pattern = r"(?<!\w)" + re.escape(frm) + r"(?!\w)"
        new, n = re.subn(pattern, lambda _m, t=to: t, corrected)
        if n:
            corrected = new
            edits.append({"from": frm, "to": to})
    return corrected, edits


def correct_transcript(text: str, *, source: str = "dict", use_ai: bool = True) -> tuple[str, list[dict]]:
    """Two-stage correction. Returns (corrected_text, edits).

    Stage 1 (always): deterministic learned map — instant, no network.
    Stage 2 (use_ai): Haiku for the long tail / not-yet-learned errors.
    Fails open: on any error returns the best-so-far text. Only NEW (Haiku)
    edits are logged to CORRECTIONS_LOG for the review loop.
    """
    if not text or len(text.split()) < 1:
        return text, []

    # Stage 1 — deterministic map (0 ms)
    text, det_edits = _apply_map(text)

    if not use_ai:
        return text, det_edits

    from .notes import _get_anthropic_client  # noqa: PLC0415

    client = _get_anthropic_client()
    glossary = _glossary()
    if client is None or not glossary:
        return text, det_edits
    t0 = time.monotonic()
    try:
        resp = client.messages.create(
            model=cfg.NOTES_CFG["classifier_model"] if cfg.NOTES_CFG else "claude-haiku-4-5-20251001",
            max_tokens=max(800, len(text) * 2),
            temperature=0,
            # System + glossary is identical across calls → cache it. The glossary
            # is the bulk of the input; caching cuts latency and cost on the
            # repeated dictations a user does in a burst (5-min cache TTL).
            system=[
                {
                    "type": "text",
                    "text": f"{_SYSTEM}\n\n=== ГЛОССАРИЙ ===\n{glossary}",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": text}],
            timeout=8.0,
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        data = json.loads(raw)
        edits = data.get("edits", []) or []
    except Exception as exc:
        logger.info("glossary correction skipped: {}", exc)
        return text, det_edits
    # Apply edits deterministically in Python (Haiku only decides what to change,
    # not regenerate the whole text — keeps output tiny and latency low).
    corrected = text
    ai_edits: list[dict] = []
    for e in edits:
        frm, to = e.get("from"), e.get("to")
        if frm and to and frm in corrected and frm != to:
            corrected = corrected.replace(frm, to)
            ai_edits.append({"from": frm, "to": to})
    latency = (time.monotonic() - t0) * 1000
    if ai_edits:
        logger.info("glossary AI: {} edit(s) in {:.0f}ms: {}", len(ai_edits), latency,
                    ", ".join(f"{e['from']}→{e['to']}" for e in ai_edits))
        # Only Haiku-discovered (new) edits feed the review loop; map hits are known.
        _log_edits(text, corrected, ai_edits, source)
    else:
        logger.debug("glossary AI: no edits ({:.0f}ms)", latency)
    return corrected, det_edits + ai_edits


def _log_edits(raw: str, corrected: str, edits: list[dict], source: str) -> None:
    try:
        CORRECTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source": source,
            "raw": raw,
            "corrected": corrected,
            "edits": edits,
            "reviewed": False,
        }
        with CORRECTIONS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("could not log correction: {}", exc)
