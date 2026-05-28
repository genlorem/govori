"""Public landing page served at govori.io/ — functional MVP.

Replace later with the OpenDesign-made design; for now it makes the domain a
real product page with a working "Subscribe" button → Lemon Squeezy checkout.
Checkout URL from env GOVORI_CHECKOUT_URL.
"""
from __future__ import annotations

import html
import os

_DEFAULT_CHECKOUT = "https://hanzi-hunt.lemonsqueezy.com/checkout/buy/e7f4cf3f-8fd6-408f-9dff-3bf454b64ff5"

_TPL = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Govori — голос в текст под курсор</title>
<meta name="theme-color" content="#0b0b10">
<link rel="apple-touch-icon" href="/review/icon.png">
<link rel="icon" type="image/png" href="/review/icon.png">
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; margin: 0; -webkit-tap-highlight-color: transparent; }
body { font: 17px/1.55 -apple-system,system-ui,Segoe UI,sans-serif; background:#0b0b10; color:#e8e8ea;
       -webkit-font-smoothing: antialiased; }
.wrap { max-width: 720px; margin: 0 auto; padding: 0 22px; }
.hero { text-align:center; padding: clamp(56px,12vw,120px) 0 40px; }
.badge { width:84px; height:84px; border-radius:22px; background:#16161d; display:flex; align-items:center;
         justify-content:center; margin:0 auto 24px; border:1px solid #26262f; }
.badge svg { width:46px; height:46px; }
h1 { font-size: clamp(30px,7vw,46px); line-height:1.1; letter-spacing:-0.02em; font-weight:700; }
h1 .g { color:#3ddc84; }
.lead { color:#9a9aa3; font-size: clamp(17px,2.6vw,20px); margin:18px auto 0; max-width:540px; }
.cta { display:inline-block; margin-top:34px; background:#3ddc84; color:#06281a; text-decoration:none;
       font-weight:700; font-size:18px; padding:16px 34px; border-radius:14px; }
.cta:active { transform: translateY(1px); }
.price { color:#6a6a73; font-size:14px; margin-top:12px; }
.feats { display:grid; gap:14px; padding: 30px 0 10px; }
@media(min-width:600px){ .feats{ grid-template-columns:1fr 1fr; } }
.card { background:#16161d; border:1px solid #26262f; border-radius:16px; padding:20px; }
.card h3 { font-size:17px; margin-bottom:6px; }
.card h3 span { color:#3ddc84; margin-right:8px; }
.card p { color:#9a9aa3; font-size:15px; }
.how { padding: 36px 0; }
.how h2 { font-size:22px; margin-bottom:18px; }
.step { display:flex; gap:14px; margin-bottom:16px; align-items:flex-start; }
.step .n { flex:0 0 28px; height:28px; border-radius:50%; background:#1f6f43; color:#fff; font-weight:700;
           display:flex; align-items:center; justify-content:center; font-size:14px; }
.step p { color:#cfcfd6; font-size:15px; }
.foot { text-align:center; color:#5a5a63; font-size:13px; padding: 30px 0 50px; border-top:1px solid #1a1a22; margin-top:24px; }
.foot a { color:#8a8a93; }
</style></head><body>
<div class="wrap">
  <section class="hero">
    <div class="badge">
      <svg viewBox="0 0 180 180" fill="none"><rect x="67" y="30" width="46" height="78" rx="23" fill="#3ddc84"/>
      <path d="M46 74a44 44 0 0 0 88 0" stroke="#3ddc84" stroke-width="10" stroke-linecap="round"/>
      <rect x="85" y="118" width="10" height="26" rx="4" fill="#3ddc84"/>
      <rect x="64" y="142" width="52" height="8" rx="4" fill="#3ddc84"/></svg>
    </div>
    <h1>Говори — и текст <span class="g">появляется</span> под курсором</h1>
    <p class="lead">Голосовая диктовка для телефона. Зажми, скажи, отпусти — распознанный текст вставляется прямо туда, где курсор. В любом приложении.</p>
    <a class="cta" href="__CHECKOUT__">Оформить подписку</a>
    <div class="price">Подписка · отмена в любой момент</div>
  </section>

  <section class="feats">
    <div class="card"><h3><span>⌨</span>Под курсор</h3><p>Не буфер обмена — текст сразу в активное поле: Telegram, Notes, почта, заметки.</p></div>
    <div class="card"><h3><span>🎙</span>Hold-to-talk</h3><p>Зажал — говоришь, отпустил — готово. Без лишних тапов.</p></div>
    <div class="card"><h3><span>🧠</span>Умная коррекция</h3><p>Имена, проекты, термины распознаются правильно и дообучаются под тебя.</p></div>
    <div class="card"><h3><span>⚡</span>Быстро</h3><p>Распознавание за ~секунду. Русский и английские термины вперемешку.</p></div>
  </section>

  <section class="how">
    <h2>Как начать</h2>
    <div class="step"><div class="n">1</div><p>Оформи подписку — получишь лицензионный ключ на почту.</p></div>
    <div class="step"><div class="n">2</div><p>Установи приложение Govori (iPhone / Android) и введи ключ.</p></div>
    <div class="step"><div class="n">3</div><p>Включи клавиатуру Govori и диктуй в любом приложении.</p></div>
  </section>

  <div class="foot">Govori · <a href="/setup">У меня уже есть ключ</a></div>
</div>
</body></html>"""


def render_landing() -> str:
    checkout = os.environ.get("GOVORI_CHECKOUT_URL", _DEFAULT_CHECKOUT)
    return _TPL.replace("__CHECKOUT__", html.escape(checkout))
