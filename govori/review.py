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


ICON_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAALQAAAC0CAIAAACyr5FlAAAEzElEQVR4nO3dO27bQBRGYSpQRxhw5c4195ANeU3ZUPYw6zDYpxDgyLJ+vmZI3sf5ijQJrLHm8A4lK8ml71+7/fX9ywGPkso4fu79ENf9vjRB7Or+6d0plPZx0MTxvp7ztpU0i4Mm4lXSIA6yMOi2KZWJVMVBFrET+VX5wLBv805tmRxkkWSErJ4clOHX2r1bFwdleLdqB5ceK2SR8IhZNDkoI54lezofB2VENbuzM3FQRmzT+7v9fQ6ENxUHYyODiV2WcVBGHmqvn8dBGdk83XHuOSA9iYOxkVP/Y3g8xkEZmfXf++BYgfQtDsYG+rvhweSA9D8OxgYeSmByQCIOzMXBmYJ7tx6YHJCIA5OfIU1+pgx/P9Rvld9/uqz6/uXS968J45gIQin5QkkXx4Ys0iaSKI7KLBIm8osyzu3MshSvVvbYyyFBH5e3t/curgO2sMQ9YiJPjmMu7iHuCIkcByqFjePIC3oIOjxixnH8bg0R+wgYx1n7NITrI2AcaCVaHOdevkOs4REtDjQUKg4LF+5gYA2thIoDbREHJOJAgjjsHPaDmZVUihMHmiMOSMQBiTggEQck4oBEHJCIAxJxQCIOSMQBiTggEQck4oBEHJCIAxJxQCIOSMQBiTggEQck4oBEHJCIAxJxQCIOSMQBiTggEQck4oBEHJCIAxJxQCIOSMQBiTggEQck4oBEHJCIAyHimP7HX+38L41lciWO/gnba2fe/bM5/P2wE8Hm7+X2q/1vxG4cjq6wym/QbCUW4wifhZdKPN1zzKZj4ckteg3uovcXB1LHMTsAzA6PUjE2LIw9B3Es4WtED65Waz2OmsvorEuwOFyzyziWMHW4lED3oQ7iWLLBRvoodWXYHBum41jI8nU5GF6b+zgWXlJqD465Iot4lIVlmB0bXddd3t7eO9vqn+WdruBS/YiWy7A+OZrMj532oEQvw0ccyx3WR4n42sTlsbL2Sd/14xSl0Re3PzY8xbF2X5snUtp9QRdlOItjpz2oP4yGiGX4i2PDRb/rZgyWFtOcvzg23zc03Jjh7AUcw2UcNfeVlTs0nPS4p/AaR6sXjTWfHYldhu84vLypUHyW4T4O44kUt1nEeYfU5h4Uk6tKF4fBnSjG1pP3WDF1xJQQWcSM48RESqAsIsdxcCIlXBbx4zjxwz4xpIjjS+Z3tDbIFUfUj2ztJMhL2W2W7HrJWkb2ODCNOCARByTigEQckIgDEnFAIg5IxAGJOCARByTigEQckIgDCT7PcfpHi+P9oD9CHKayiJQIxwrixmF2bHS215YiDuyHOBA3Dss3fcXw2lLEgf1EeClr8O6vOJ8ZN5e+f+37l7OXAYs4ViARByTiwGQc4/ip/wCSGsdPJgck4sBcHJwsuHfrgckBiTiwIA5OFjyUwOSA9C0OhgfGuze9mByQHuNgeGQ2fn+v/MnkoI+cxh8/ReFYgfQ8DoZHNk93XE4O+shD7fXUsUIfGUzsMvcc6DbGwfCIbXp/5ycHfUQ1u7OLjhX6iGfJnl5XfS3+hksAyy/1dTekjBDvVu3g6lcr9OHX2r27bn4MjhhHtl3S29/nYIR4sXmnrvWPyggxq/ICvrZaAYmY0mSuN4jjYTVUcqK2Z32zOL5QSXe4ne7//gEvIo1lbpZh/gAAAABJRU5ErkJggg=="


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


def dictionary_entries() -> list[dict]:
    """The permanent corrections map, newest-added first.

    corrections.json is a plain {from: to} dict; Python preserves insertion
    order, and accepted entries are appended, so reversing yields most-recent
    first (seed entries sink to the bottom).
    """
    if not CORRECTIONS_MAP.exists():
        return []
    try:
        cmap = json.loads(CORRECTIONS_MAP.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [{"from": k, "to": v} for k, v in reversed(list(cmap.items()))]


def remove_correction(frm: str) -> None:
    """Drop an entry from the permanent map (e.g. a wrong accept)."""
    if not frm or not CORRECTIONS_MAP.exists():
        return
    try:
        cmap = json.loads(CORRECTIONS_MAP.read_text(encoding="utf-8"))
    except Exception:
        return
    if frm in cmap:
        del cmap[frm]
        CORRECTIONS_MAP.write_text(
            json.dumps(cmap, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("review: removed {} ({} entries left)", frm, len(cmap))


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
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Govori">
<meta name="theme-color" content="#0b0b10">
<link rel="apple-touch-icon" href="/review/icon.png">
<link rel="icon" type="image/png" href="/review/icon.png">
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
.dictrow { display:flex; align-items:center; gap:8px; padding:9px 12px; border-bottom:1px solid #1e1e26; font-size:15px; }
.dictrow .from { color:#b0b0b8; text-decoration:none; }
.dictrow .arrow { color:#5a5a63; }
.dictrow .to { color:#3ddc84; font-weight:600; flex:1; }
.dictrow .del { background:none; border:0; color:#5a5a63; font-size:18px; padding:2px 8px; flex:0; }
.dfilter { width:100%; background:#16161d; border:1px solid #26262f; border-radius:10px; color:#e8e8ea;
           padding:10px 12px; font-size:15px; margin-bottom:10px; }
.addrow { display:flex; align-items:center; gap:6px; margin-bottom:10px; }
.addinp { flex:1; min-width:0; background:#16161d; border:1px solid #26262f; border-radius:10px;
          color:#e8e8ea; padding:10px; font-size:14px; }
.addbtn { flex:0 0 44px; background:#1f6f43; color:#fff; border:0; border-radius:10px; font-size:22px; padding:8px; }
</style></head><body>
<h1>Ревью словаря Govori</h1>
<div class="sub" id="sub">загрузка…</div>
<div id="list"></div>
<div id="dictwrap">
  <h2 style="font-size:16px;margin:24px 0 4px;">Словарь <span class="tag" id="dictcount"></span></h2>
  <div style="color:#8a8a93;font-size:13px;margin-bottom:12px;">новые слова сверху</div>
  <div class="addrow">
    <input id="addfrom" class="addinp" placeholder="как слышит (ошибка)">
    <span class="arrow">→</span>
    <input id="addto" class="addinp" placeholder="как правильно">
    <button class="addbtn" id="addbtn">＋</button>
  </div>
  <input class="dfilter" id="dfilter" placeholder="поиск по словарю…" oninput="renderDict()">
  <div id="dict"></div>
</div>
<div class="flash" id="flash"></div>
<script>
// Token lives in the page URL (?token=…). The data/action calls are separate
// requests that the auth middleware also guards, so forward the token to them.
const TOKEN = new URLSearchParams(location.search).get('token') || '';
const q = TOKEN ? ('?token=' + encodeURIComponent(TOKEN)) : '';
async function load() {
  const r = await fetch('/review/data' + q); const cards = await r.json();
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
  await fetch('/review/action' + q, {method:'POST',
    headers:{'Content-Type':'application/json', 'X-Govori-Token': TOKEN},
    body: JSON.stringify({ts:c.ts, from:c.from, to:c.to, accept})});
  flash(accept ? '✓ В словарь: '+c.to : 'Пропущено');
  el.remove();
  if(!document.querySelectorAll('.card').length) load();
  if(accept) loadDict();
}

let DICT = [];
async function loadDict() {
  const r = await fetch('/review/dict' + q); DICT = await r.json();
  document.getElementById('dictcount').textContent = DICT.length;
  renderDict();
}
async function addEntry() {
  const f = document.getElementById('addfrom').value.trim();
  const t = document.getElementById('addto').value.trim();
  if (!f || !t) { flash('заполни оба поля'); return; }
  await fetch('/review/action' + q, {method:'POST',
    headers:{'Content-Type':'application/json', 'X-Govori-Token': TOKEN},
    body: JSON.stringify({from:f, to:t, accept:true})});
  document.getElementById('addfrom').value=''; document.getElementById('addto').value='';
  flash('✓ Добавлено: '+t);
  loadDict();
}
document.getElementById('addbtn').onclick = addEntry;
function renderDict() {
  const f = (document.getElementById('dfilter').value||'').toLowerCase();
  const box = document.getElementById('dict'); box.innerHTML='';
  const rows = DICT.filter(e => !f || (e.from+e.to).toLowerCase().includes(f));
  for (const e of rows) {
    const row = document.createElement('div'); row.className='dictrow';
    row.innerHTML = '<span class="from">'+esc(e.from)+'</span><span class="arrow">→</span>'
      + '<span class="to">'+esc(e.to)+'</span><button class="del">✕</button>';
    row.querySelector('.del').onclick = () => delEntry(e, row);
    box.appendChild(row);
  }
}
async function delEntry(e, row) {
  if(!confirm('Удалить из словаря: '+e.from+' → '+e.to+'?')) return;
  row.style.opacity=.4;
  await fetch('/review/action' + q, {method:'POST',
    headers:{'Content-Type':'application/json', 'X-Govori-Token': TOKEN},
    body: JSON.stringify({remove:e.from})});
  flash('Удалено: '+e.from); row.remove();
  DICT = DICT.filter(x => x.from !== e.from);
  document.getElementById('dictcount').textContent = DICT.length;
}
load(); loadDict();
</script></body></html>"""


def render_page() -> str:
    return PAGE


def icon_bytes() -> bytes:
    import base64  # noqa: PLC0415

    return base64.b64decode(ICON_PNG_B64)
