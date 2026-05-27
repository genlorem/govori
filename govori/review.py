"""Layer 2 — review loop UI + data ops for glossary self-learning.

Serves a mobile-friendly page (iPhone Safari) listing the term corrections Haiku
made. The user accepts good ones (→ permanent corrections.json map, so they're
fixed instantly everywhere afterward) or dismisses noise. Reviewed records are
flagged in the append-only log so they stop showing.
"""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from .correct import CORRECTIONS_LOG, CORRECTIONS_MAP


def _read_log() -> list[dict]:
    if not CORRECTIONS_LOG.exists():
        return []
    out = []
    for line in CORRECTIONS_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _write_log(records: list[dict]) -> None:
    tmp = CORRECTIONS_LOG.with_suffix(".jsonl.tmp")
    tmp.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    tmp.replace(CORRECTIONS_LOG)


def pending_edits() -> list[dict]:
    """Flatten un-reviewed log records into individual edit cards (newest first)."""
    cards = []
    for rec in _read_log():
        if rec.get("reviewed"):
            continue
        ts = rec.get("ts", "")
        for i, e in enumerate(rec.get("edits", [])):
            cards.append(
                {
                    "ts": ts,
                    "idx": i,
                    "from": e.get("from", ""),
                    "to": e.get("to", ""),
                    "context": rec.get("corrected", ""),
                    "source": rec.get("source", ""),
                }
            )
    cards.reverse()
    return cards


def accept_correction(frm: str, to: str) -> None:
    """Add a misrecognition→canonical pair to the permanent map."""
    if not frm or not to:
        return
    cmap = {}
    if CORRECTIONS_MAP.exists():
        try:
            cmap = json.loads(CORRECTIONS_MAP.read_text(encoding="utf-8"))
        except Exception:
            cmap = {}
    cmap[frm] = to
    CORRECTIONS_MAP.write_text(
        json.dumps(cmap, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("review: accepted {} -> {} ({} entries)", frm, to, len(cmap))


def mark_reviewed(ts: str) -> None:
    """Flag every log record with this timestamp as reviewed."""
    records = _read_log()
    changed = False
    for r in records:
        if r.get("ts") == ts and not r.get("reviewed"):
            r["reviewed"] = True
            changed = True
    if changed:
        _write_log(records)


PAGE = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Govori · Ревью словаря</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
body { margin:0; font:16px/1.4 -apple-system,system-ui,sans-serif; background:#0b0b10; color:#e8e8ea;
       padding:max(16px,env(safe-area-inset-top)) 16px max(24px,env(safe-area-inset-bottom)); }
h1 { font-size:20px; margin:4px 0 2px; }
.sub { color:#8a8a93; font-size:13px; margin-bottom:18px; }
.card { background:#16161d; border:1px solid #26262f; border-radius:14px; padding:14px; margin-bottom:12px; }
.edit { font-size:19px; font-weight:600; margin-bottom:8px; }
.from { color:#ff6b6b; text-decoration:line-through; text-decoration-color:#ff6b6b80; }
.arrow { color:#6a6a73; margin:0 8px; }
.to { color:#3ddc84; }
.ctx { color:#9a9aa3; font-size:13px; margin-bottom:12px; max-height:3.6em; overflow:hidden; }
.ctx b { color:#cfcfd6; font-weight:600; }
.row { display:flex; gap:8px; }
button { flex:1; border:0; border-radius:10px; padding:12px; font-size:15px; font-weight:600; }
.ok { background:#1f6f43; color:#fff; }
.no { background:#2a2a33; color:#c9c9d0; }
.empty { text-align:center; color:#6a6a73; padding:48px 0; }
.tag { font-size:11px; color:#6a6a73; background:#20202a; padding:2px 7px; border-radius:6px; }
.flash { position:fixed; left:50%; bottom:24px; transform:translateX(-50%); background:#1f6f43;
         color:#fff; padding:10px 18px; border-radius:20px; opacity:0; transition:.2s; pointer-events:none; }
.flash.show { opacity:1; }
</style></head><body>
<h1>Ревью словаря Govori</h1>
<div class="sub" id="sub">загрузка…</div>
<div id="list"></div>
<div class="flash" id="flash"></div>
<script>
async function load() {
  const r = await fetch('/review/data'); const cards = await r.json();
  const list = document.getElementById('list');
  document.getElementById('sub').textContent = cards.length
    ? cards.length + ' правок на проверку. «Верно» → попадёт в постоянный словарь.'
    : '';
  if (!cards.length) { list.innerHTML = '<div class="empty">✓ Всё проверено</div>'; return; }
  list.innerHTML = '';
  for (const c of cards) {
    const ctx = (c.context||'').replace(new RegExp(c.to.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&'),'g'), '<b>'+c.to+'</b>');
    const el = document.createElement('div'); el.className='card';
    el.innerHTML =
      '<div class="edit"><span class="from">'+esc(c.from)+'</span><span class="arrow">→</span><span class="to">'+esc(c.to)+'</span></div>'
      + '<div class="ctx">'+ctx+'</div>'
      + '<div class="row"><button class="ok">✓ Верно</button><button class="no">Пропустить</button></div>'
      + '<div style="margin-top:8px"><span class="tag">'+c.source+'</span></div>';
    el.querySelector('.ok').onclick = () => act(c, true, el);
    el.querySelector('.no').onclick = () => act(c, false, el);
    list.appendChild(el);
  }
}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function flash(t){const f=document.getElementById('flash');f.textContent=t;f.classList.add('show');setTimeout(()=>f.classList.remove('show'),1400);}
async function act(c, accept, el) {
  el.style.opacity=.4;
  await fetch('/review/action', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ts:c.ts, from:c.from, to:c.to, accept})});
  flash(accept ? '✓ В словарь: '+c.to : 'Пропущено');
  el.remove();
  if(!document.querySelectorAll('.card').length) load();
}
load();
</script></body></html>"""


def render_page() -> str:
    return PAGE
