"""/setup — post-purchase onboarding shown after Lemon Squeezy checkout.

Displays the buyer's license key and walks them through installing the iPhone
shortcut with that key. The shared shortcut is published once to iCloud (by the
owner) and asks for the key on import; its URL comes from env
GOVORI_SHORTCUT_ICLOUD_URL.
"""
from __future__ import annotations

import html
import os

_TPL = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Govori · Установка</title>
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0b0b10">
<link rel="apple-touch-icon" href="/review/icon.png">
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
body { margin:0; font:16px/1.5 -apple-system,system-ui,sans-serif; background:#0b0b10; color:#e8e8ea;
       padding:max(20px,env(safe-area-inset-top)) 18px max(28px,env(safe-area-inset-bottom)); max-width:560px; margin:0 auto; }
h1 { font-size:22px; margin:8px 0 4px; }
.lead { color:#8a8a93; font-size:14px; margin-bottom:22px; }
.keybox { background:#16161d; border:1px solid #26262f; border-radius:14px; padding:16px; margin-bottom:14px; }
.keylabel { color:#8a8a93; font-size:12px; text-transform:uppercase; letter-spacing:.04em; margin-bottom:8px; }
.key { font:600 17px ui-monospace,Menlo,monospace; color:#3ddc84; word-break:break-all; }
.copy { margin-top:12px; width:100%; background:#1f6f43; color:#fff; border:0; border-radius:10px; padding:13px; font-size:15px; font-weight:600; }
ol { padding-left:20px; } li { margin-bottom:12px; }
.btn { display:block; text-align:center; background:#2a2a33; color:#fff; text-decoration:none; border-radius:10px; padding:13px; font-weight:600; margin-top:8px; }
.btn.primary { background:#3ddc84; color:#06281a; }
.warn { background:#2a1f12; border:1px solid #4a3a1a; color:#e0c088; border-radius:12px; padding:12px 14px; font-size:13px; margin-top:18px; }
.flash { position:fixed; left:50%; bottom:24px; transform:translateX(-50%); background:#1f6f43; color:#fff;
         padding:10px 18px; border-radius:20px; opacity:0; transition:.2s; pointer-events:none; }
.flash.show { opacity:1; }
.nokey { color:#ff9b9b; }
</style></head><body>
<h1>Govori готов 🎙️</h1>
<div class="lead">Спасибо за подписку! Осталось два шага — и диктовка заработает на айфоне.</div>

__KEYBLOCK__

<ol>
  <li><b>Установи команду:</b><br><a class="btn primary" id="addsc" href="__SHORTCUT_URL__">Добавить Govori в Команды</a></li>
  <li><b>Когда спросит ключ</b> — вставь свой лицензионный ключ (кнопка «Скопировать» выше).</li>
  <li><b>Повесь на Action Button:</b> Настройки → Кнопка действия → Быстрая команда → Govori.</li>
</ol>

<div class="warn">⚠️ Ключ работает на <b>одном устройстве</b>. Для второго нужна отдельная подписка — напиши в поддержку.</div>
<div class="flash" id="flash">Скопировано</div>
<script>
const KEY = __KEYJSON__;
function copyKey(){
  if(!KEY) return;
  navigator.clipboard.writeText(KEY).then(()=>{
    const f=document.getElementById('flash'); f.classList.add('show'); setTimeout(()=>f.classList.remove('show'),1400);
  });
}
const c=document.getElementById('copybtn'); if(c) c.onclick=copyKey;
</script>
</body></html>"""


def render_setup(key: str) -> str:
    shortcut_url = os.environ.get("GOVORI_SHORTCUT_ICLOUD_URL", "#")
    key = (key or "").strip()
    if key:
        keyblock = (
            '<div class="keybox"><div class="keylabel">Твой лицензионный ключ</div>'
            f'<div class="key">{html.escape(key)}</div>'
            '<button class="copy" id="copybtn">Скопировать ключ</button></div>'
        )
        keyjson = '"' + key.replace('"', '') + '"'
    else:
        keyblock = (
            '<div class="keybox"><div class="nokey">Ключ не передан в ссылке. '
            'Проверь письмо от Lemon Squeezy — ключ там, либо открой эту страницу '
            'по ссылке из чека.</div></div>'
        )
        keyjson = "null"
    return (_TPL
            .replace("__KEYBLOCK__", keyblock)
            .replace("__SHORTCUT_URL__", html.escape(shortcut_url))
            .replace("__KEYJSON__", keyjson))
