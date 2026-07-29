# govori — стратегия продукта и монетизации

**Статус:** idea validation phase
**Старт:** 2026-04-14 (как obsidian-voice → wisp → virbix → govori)
**Последний пересмотр:** 2026-04-19 (консолидация в govori/.planning/ после ребрендинга)

## Гипотеза в одном предложении

> Голосовой ввод для Mac с модульной архитектурой: core бесплатный (STT +
> paste в активное окно), модули платные (Smart Notes, Obsidian, Slack, Notion).
> Юзер обвешивает govori как ёлку — покупает только нужные модули.

## Почему этот путь лучше «Obsidian-плагина»

- **Код уже есть** (Python, работает) — не переписывать на TS
- **Шире аудитория** — не только Obsidian-юзеры, а все кто хотят голосовой ввод
- **Obsidian-интеграция — один из модулей**, а не весь продукт
- **Не завязаны на review Community Plugins** (4-8 недель)
- **Recurring upsell** — продал core, продал модуль, продал ещё. Модель Alfred Powerpack / Raycast Pro
- **Уникальное позиционирование** — никто не делает голосовой CLI с модулями.
  Superwhisper/MacWhisper — монолиты

## Риски этого пути (признаём)

- **Рынок меньше чем Obsidian** (десятки тысяч CLI-юзеров vs 1M Obsidian)
- **Mac-only** (Quartz, fn key) — отсекает Win/Linux. Долгосрочно — минус
- **Python-distribution** требует brew tap или installer.sh, не «one click»
- **License protection** слабая для open-source Python — рассчитываем на 90%
  честных, 10% пиратят (норма индустрии)

## Архитектура

```
govori-core (FREE, MIT, open source)
├── STT через Groq/OpenAI (BYOK — свой API key)
├── Hotkey → транскрипция → paste в активное окно
├── Базовая plugin-система (framework для модулей)
└── `govori license add XXX` — активация платных модулей

Модули (paid, closed source в приватном репо, license-gated):
├── 📝 Smart Notes — $29 one-time (ПЕРВЫЙ)
│   ├── Classification через Claude (type/urgency/context)
│   ├── Auto-routing в markdown с frontmatter
│   └── Контексты через YAML (уже работает)
│
├── 🧠 Obsidian — $19 (требует Smart Notes)
│   ├── Запись прямо в vault
│   ├── Smart-linking [[existing notes]]
│   └── Темплейты per type
│
├── 💬 Slack — $19 (на будущее)
├── 📋 Notion — $19 (на будущее)
└── 📅 Calendar — $19 (на будущее)

Bundle «govori Pro» — $79 one-time, все текущие + новые модули 2 года.
```

## Первый paid модуль — Smart Notes (не Obsidian)

**Почему:**
- Логика **уже написана** (`_note_pipeline_background`, `classify_note`)
- Работает **standalone** (markdown в папку) — без Obsidian
- Obsidian-юзеры указывают путь на vault → работает
- Не-Obsidian юзеры используют как standalone-систему заметок
- **Одним модулем покрываешь обе аудитории**

Obsidian-specific фичи (smart linking, темплейты) — второй модуль.

## Защита ключей и licensing

### API keys (токены OpenAI/Groq/Claude)
**BYOK** на всех фазах до 1000 платящих. Юзер вводит свой ключ, мы его не
видим. Ноль infra-risk. Для техничной аудитории — норма.

В маркетинге — **плюс**: «Privacy-first: we never see your voice or your keys».

### License protection для модулей
**MVP (200 строк):**
1. Gumroad генерирует license key при покупке
2. Webhook Gumroad → Cloudflare Worker → KV (free tier = 100k юзеров)
3. `govori license add XXX` — дёргает endpoint, сохраняет локально
4. **Heartbeat-модель** (STT всё равно требует интернет, оффлайн-grace не нужен):
   - Валидация на startup (блокирующе, 100-200мс)
   - Фоновый re-validate каждый час
   - Revoke работает в течение часа
   - Offline grace всего 24ч — только на случай блипов сети
5. **Бонус от частых heartbeat:**
   - Real-time metric активных юзеров (бесплатная аналитика)
   - Crash reports через пропущенные heartbeat
   - Детект утечки ключа (один key с 10+ IP за час)

**Cost:** CF Workers free tier 100k req/день. 1000 платящих × 24 heartbeat =
24k/день → бесплатно при любом масштабе до ~4000 платящих.

**Что НЕ делать:**
- Проверять license на каждую транскрипцию (+50-200мс к каждому использованию)
- Обфускация Python (всё равно читается)

## План: 12 недель до первых денег

### 🔍 Phase 0: Validation (Неделя 1-2) ← СЕЙЧАС
**Цель:** понять, есть ли спрос, **до кода**.

- [ ] Waitlist-страница на Beehiiv. Месседж:
  «AI-powered voice dictation for Mac. Modular — pay only for what you need.»
- [ ] GIF-демо: «нажал fn, сказал, текст появился» (30 сек)
- [ ] Скриншот-мокап интерфейса выбора модулей (Alfred-like)
- [ ] Пост в Obsidian Forum — про Obsidian-модуль в будущем
- [ ] Комментарий в [vox #7](https://github.com/vincentbavitz/obsidian-vox/issues/7)
- [ ] Пост в r/ObsidianMD
- [ ] Пост в r/macapps + r/commandline — про govori как voice-driven CLI
- [ ] **Gate: 30+ signups за 10 дней. Иначе — переосмыслить.**

### 🛠 Phase 1: Shareable MVP (Неделя 3-5)
**Цель:** базовый govori которым можно поделиться с beta-тестерами, БЕЗ
Obsidian, БЕЗ Notes — просто STT + paste. Плюс infra для лицензий.

- [ ] `install.sh` — one-line curl installer (Python venv + зависимости)
- [ ] Homebrew tap `brew tap genlorem/govori && brew install govori`
- [ ] Onboarding-скрипт: спрашивает API key, тестирует, сохраняет
- [ ] Cleanup govori-core: вынести notes-логику в отдельный модуль
- [ ] Закрытый репо `govori-modules` с заглушкой для Smart Notes
- [ ] Cloudflare Worker для лицензий (Gumroad webhook)
- [ ] Команды `govori license add XXX`, `govori license status`, `govori modules list`
- [ ] Раздать 10 beta-тестерам (бесплатно, за фидбек)
- [ ] **Gate: 8 из 10 успешно установили и пользуются неделю. Иначе — UX фикс.**

### 🚢 Phase 2: Первый модуль — Smart Notes (Неделя 6-8)
**Цель:** рабочий платный модуль, продажа через Gumroad за $29.

- [ ] Портировать notes-pipeline в формат модуля с license gate
- [ ] UI для настройки контекстов (файл YAML пока, не GUI — не усложнять)
- [ ] Gumroad setup: страница продукта, webhook, test purchase
- [ ] Документация: install + quick start + 3 примера использования
- [ ] Выложить govori-core на GitHub под MIT
- [ ] Lifetime deal для waitlist: **$19 first 100 early bird**
- [ ] Launch email по waitlist
- [ ] **Gate: 30+ продаж за 2 недели = go. <10 — переосмыслить offering.**

### 💰 Phase 3: Obsidian-модуль + маркетинг (Неделя 9-12)
**Цель:** $2-5k cash total, 100+ платящих.

- [ ] Obsidian-модуль ($19)
- [ ] Bundle govori Pro ($79 — all modules 2 года)
- [ ] Product Hunt launch (если есть 200+ installs)
- [ ] Гостевые посты на dev-блогах (indie hackers, hacker news, etc)
- [ ] Weekly build-in-public в Beehiiv
- [ ] **Gate: $3000+ total revenue к 12-й неделе. Иначе — переосмыслить.**

## Метрики по фазам

| Phase | KPI | Target | Gate-fail action |
|---|---|---|---|
| 0 | Waitlist signups | 30+ за 10 дней | Переосмыслить месседж |
| 1 | Beta success rate | 8 из 10 юзеров активны неделю | UX / install проблемы |
| 2 | Smart Notes sales | 30+ за 2 недели | Pricing / feature mismatch |
| 3 | Total revenue | $3000+ к 12-й неделе | Pivot или shutdown |

## Правила фокуса

1. **Не писать код в Phase 0.** Валидация сначала.
2. **Не усложнять govori-core.** Каждая фича там = не монетизируется. Всё
   ценное — в платные модули.
3. **Модуль должен работать standalone.** Smart Notes без Obsidian. Obsidian
   модуль без Slack. Не связывать модули друг с другом жёстко.
4. **BYOK всегда.** Не строить свой proxy-backend до 1000 платящих.
5. **Weekly update в Beehiiv** каждую пятницу — обязательно, build-in-public.
6. **Не бросать vipzal-admin** до MRR $3-5k.
7. **Не делать Windows/Linux** до стабильного $5k/мес на Mac. Mac-first.

## Что уже есть в кодовой базе (не теряем)

- STT через Groq/OpenAI с конфигурируемым провайдером ✓
- Plugin-система с YAML-контекстами ✓
- Notes-pipeline с Claude-классификацией ✓
- Stuck tasks tracking ✓
- Hotkey `fn` через Quartz ✓
- HUD-индикатор ✓
- Groq integration ✓

## Открытые вопросы

- [ ] Первая цена Smart Notes: $29 или $19 на старте? Склоняюсь к $29 с
  early-bird $19 первые 100
- [ ] Mobile companion (iOS app для записи → sync в Mac-govori)? Потом.
- [ ] Windows порт (когда $5k+ MRR на Mac)

## Домены

- govori.io ✓ куплен на Porkbun 2026-04-17 ($28/yr)
- govori.app — не проверяли
- govori.ru — не проверяли
- govori.kz — не проверяли
- govori.com — не проверяли

## Лог

**2026-04-14 v1** — проект заведён под именем `obsidian-voice`. Исследование:
obsidian-vox мёртв (76⭐, backend лежит), whisper-plugin (342⭐) делает
только dumb STT. Решили делать Obsidian-плагин с классификацией.

**2026-04-14 v2 (pivot)** — переосмыслили: вместо Obsidian-плагина делаем
продукт с модульной архитектурой. Obsidian-интеграция становится одним из
модулей. Код уже есть, аудитория шире, не завязаны на Obsidian Community
Plugins review. Первый модуль для продажи — Smart Notes (работает standalone,
покрывает и Obsidian, и non-Obsidian аудиторию).

**2026-04-15 v3** — финализировано название: **virbix**. От verbum (лат. слово)
+ vibration. Все домены свободны кроме .com. PyPI, GitHub — чисто.

**2026-04-17 v4** — второй ребрендинг: **virbix → govori**. Причина: выход
из whisper-brand cluster (MacWhisper, Wispr Flow, Superwhisper). Куплен
govori.io на Porkbun, GitHub репо `gennadiy403/govori`. Код переехал в
`~/Projects/govori/`.

**2026-04-19 v5** — консолидация: этот документ перенесён из застрявшего
`~/Projects/obsidian-voice/PLAN.md` в `~/Projects/govori/.planning/PRODUCT-STRATEGY.md`.
Все упоминания virbix заменены на govori. Директория obsidian-voice удалена.
