# Learnings — govori

Non-obvious находки по проекту. Растёт со временем; самые свежие сверху.

## 2026-05-28 — Монетизация, нативные клиенты (iOS/Android), тесты/CI, headless-сборка

### iOS Shortcuts: GUI-сборка РАБОТАЕТ и нужна как первый шаг; тупик — только программная генерация plist
**Контекст:** диктовка «голос → текст под курсор» на iPhone.
**Находка (уточнено пользователем):** шорткат, **собранный руками в приложении «Команды» по инструкции, заработал отлично** — это быстрый валидный первый шаг: проверяет весь backend-пайплайн (relay, токены, коррекция, plain-text ответ) БЕЗ нативного приложения, Apple Developer аккаунта и сборки. **НЕ исключать этот шаг.** Тупиком оказался не Shortcuts, а **попытка генерить `.shortcut` plist программно** — там magic-variable wiring ломается молча, iOS 17+ требует подписи, Mac-CLI не тестит. То есть: шорткат собирает ПОЛЬЗОВАТЕЛЬ в GUI (надёжно), я даю пошаговую инструкцию — а не генерю plist.
**Ограничения Shortcuts (почему ДАЛЕЕ нужен нативный клиент, но не вместо первого шага):** вставка под курсор в чужое приложение шорткатом невозможна (только буфер + ручная вставка); per-customer лицензии не масштабируются. Это для ПРОДАЖ.
**Как применить — последовательность:** (1) **GUI-собранный Shortcut** — быстрая валидация пайплайна + личное/раннее использование (делаю инструкцию, не plist); (2) **нативная клавиатура** (iOS extension / Android IME) — для продаваемого продукта со вставкой под курсор. Relay переиспользуется всеми клиентами.

### Хендкрафт .shortcut plist — magic-variable wiring ломается молча
**Находка:** `WFInput`/значения действий требуют **WFTextTokenString с attachment-at-range** (placeholder `￼` + `attachmentsByRange {"{0, 1}": {OutputUUID,Type:ActionOutput,OutputName}}`), а НЕ голый `WFTokenAttachment` (тот молча сбрасывается → серый placeholder, пустое значение). `WFDictionaryKey` тоже token-string. `body=File` в сгенерённом plist слал пустое тело. Mac-CLI `shortcuts run` НЕ выполняет надёжно POST-шорткаты (sandbox). Импорт на маке: `open -a Shortcuts file` → клик «Add» через `AXRaise of window "" + key code 36` (нужно Accessibility-разрешение).
**Как применить:** не хендкрафтить сложные plist. Сервер с `?text=1`→plain-text + авто-chaining (действие без `WFInput` берёт выход предыдущего) убирает почти все magic-variable.

### Headless-сборка Android APK на маке (без Android Studio)
**Находка:** `brew install openjdk@17` (НЕ новее — openjdk@26 несовместим с AGP 8.4); cask `android-commandlinetools` (без дефиса!); `yes | sdkmanager --licenses`; `sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"`; `local.properties` с `sdk.dir`. **Системный gradle (brew 9.x) НЕ генерит wrapper для AGP-8.4-проекта** — качать gradle 8.7 binary напрямую и собирать им; `gradle wrapper` сработает только ПОСЛЕ конфигурации проекта 8.7. Debug APK сайдлоадится без Google Play. Подробности → [[reference_android_headless_build]].

### Типовые баги Android-скаффолда (Codex blind-gen)
**Находка:** (1) `settings.gradle.kts` дублирует version-catalog `from(...)` — gradle авто-грузит `libs`, убрать блок; (2) нет `gradle.properties` с `android.useAndroidX=true`; (3) `Theme.Material.NoTitleBar` не существует → `NoActionBar`; (4) `switchToNextInputMethod(token,..)` нет такой сигнатуры → `showInputMethodPicker()`; (5) `Throwable.cause` нужен `override val cause: Throwable?`.

### pytest на CI: `pytest` ≠ `python -m pytest`
**Находка:** консольный `pytest` НЕ добавляет cwd в `sys.path` (`ModuleNotFoundError`), а `python -m pytest` добавляет — локальный прогон обманывал. Фикс — `pytest.ini` с `pythonpath = .`. → [[reference_pytest_pythonpath]].

### Dokploy/Traefik — маршрут на хост-сервис + форс ACME
**Находка:** dynamic-конфиги `/etc/dokploy/traefik/dynamic/*.yml`; маршрут на хост через `http://172.17.0.1:PORT`, `certResolver: letsencrypt`. Traefik **не переповторяет ACME** после провала — форсить явным `tls.domains` (реальное изменение файла → reload). systemd **user**-unit: убрать `User=` (иначе exit 216/GROUP); `EnvironmentFile` не принимает `export KEY=val`. Релей бинить `0.0.0.0` чтоб docker-Traefik достал. → [[reference_dokploy_traefik]].

### Lemon Squeezy — API vs дашборд
**Находка:** **продукты/цены только в дашборде** (API не умеет), **webhooks через API**. License Keys `activation_limit=1` = нативная привязка. Signing secret ≠ API-ключ. Query-фильтры урл-энкодить (`filter%5Bstore_id%5D`). ⚠️ Apple IAP / Play Billing могут требовать свой биллинг для in-app подписок — вопрос открыт для стора-версий.

### Codex-скаффолды требуют fix-up пасса
**Находка:** Codex пишет быстро/добротно, но не компилит/не тестит → остаются ошибки уровня компиляции (5 в Android, контракт save_or_merge_note, `import json` пропущен). → [[feedback_codex_scaffold_fixup]].

### Whisper prompt — лимит 224 токена
**Находка:** Whisper читает только ~последние 224 токена `prompt` — переполненный словарь частично игнорируется. Доменный словарь → в пост-обработку (детерм. карта + Haiku), в whisper_prompt — тесное ядро.

### Секреты через Google Drive MCP
**Находка:** `read_file_content` возвращает markdown-escaped (`\_`) — убирать `\` (`tr -d '\\'`). MCP умеет только create+read, не delete — «затирать» пользователь сам. gh-токен может протухнуть молча: метаданные отвечают, а скачивание логов/артефактов даёт 401 — лечится `gh auth login`.

## 2026-04-23 — fn-down/fn-up race condition + Whisper hallucination filter + launchagent debugging

### fn-down/fn-up race: state mutation должен быть в callback, а не в thread
**Контекст:** коммиты 0603c59 + 0775cd2 пытались починить quick-tap race. Пользователь жаловался: "при нажатии fn не всегда реагирует старт записи" — логи показывали много `[mode]` без последующего `Recording...`.
**Находка:** старая архитектура раскидывала state между потоками: fn-down callback спавнил `start_recording` thread, который *асинхронно* ставил `recording=True` под `_state_lock`. Если fn-up приходил раньше, чем thread успевал взять lock (PortAudio init может блокировать сотни мс), ветка `elif recording:` проваливалась в пустоту — микрофон стартовал после fn-up и висел навсегда.
**Как применить:** для async macOS-daemons с CGEventTap — делать **sync state mutation в callback** под lock, а в thread выносить только блокирующий I/O (`sd.InputStream`, API calls). Тогда callback и следующий событийный callback всегда видят актуальный state. См. `govori.py:_start_mic_stream` — сейчас mic init в thread, но `recording=True/False` ставится синхронно в `cg_event_callback`.

### `not transcribing` в guard условии = скрытая регрессия UX
**Контекст:** при переделке race я добавил `if not recording and not transcribing:` в guard для старта новой записи.
**Находка:** `transcribing=True` живёт 5-10 сек пока идёт API-запрос к Whisper. Всё это время новые нажатия fn игнорировались — пользователь видел `[mode]` без `Recording...`. Старое поведение разрешало перекрывать идущую транскрипцию новой записью.
**Как применить:** при синхронизации state не добавляй новых условий в существующие guard — только воспроизводи старую семантику. Race-фиксы должны быть поведенчески-нейтральны. Единственное валидное условие для блокировки fn-down — `recording=True` (уже идёт запись).

### Две копии govori = источник "зависаний" CGEventTap
**Контекст:** пользователь отлаживал race внутри одного процесса, пока я не проверил `ps aux`.
**Находка:** был запущен launchagent (com.user.govori) + терминальная копия (`./govori` из shell). Оба регистрировали `CGEventTap` на fn. macOS доставляет событие обоим; один читает микрофон, второй в то же время видит `recording=False` и инициирует свой, потом оба конфликтуют. Симптом — "зависание", внешне неотличимое от внутрипроцессного race.
**Как применить:** ПЕРВЫЙ шаг при debugging fn/HUD/recording бага — `pgrep -lf 'python.*govori\.py'`. Если больше одного — убить лишнее до любой правки кода.

### `_ensure_singleton` ловит false-positives от pgrep
**Контекст:** после `launchctl kickstart -k ...` процесс не запускался — в логе `! Govori is already running (PID XXXXX). Another instance is active — refusing to start.`. Но `ps` не показывал такого PID.
**Находка:** `_ensure_singleton` использует `pgrep -f govori.py` — паттерн матчит *любую* командную строку с подстрокой `govori.py`, включая короткоживущие pipeline-процессы вроде `ps aux | grep govori.py` или `grep govori.py file`. Они исчезают до `ps -p`, но на момент `pgrep` существуют.
**Как применить:** сузить паттерн до `python.*govori\.py` в `_find_other_govori_pids` (govori.py:2882). Либо проверять по command (не args) через `pgrep -x python` + отдельный фильтр на аргументы через `/proc`-аналог.

### Whisper `language="ru"` не гарантирует русский вывод
**Контекст:** добавили конкретные галлюцинации ("Субтитры создавал DimaTorzok") в фильтр. Пользователь: "только русский, термины на англ OK, никаких других языков".
**Находка:** даже с `language="ru"` и `whisper_prompt` модель периодически выдаёт CJK-иероглифы (`ご視聴ありがとうございました`), арабицу, деванагари на тишине/шуме. Force language работает как hint, не constraint.
**Как применить:** фильтр на уровне вывода через Unicode-blocks. См. `_FOREIGN_SCRIPT_RE` в `govori.py:_is_hallucination` — blacklist CJK/Hangul/Arabic/Hebrew/Indic/Thai/Georgian/Ethiopic, любой символ из этих блоков → весь текст отбрасывается. Кириллица+латиница+цифры+пунктуация — allow-listed неявно.

### `_state_lock` удерживается во время блокирующих PortAudio syscalls
**Контекст:** анализ race — почему `start_recording` задерживается относительно fn-up.
**Находка:** `sd.InputStream.start()` и `audio_stream.stop()/close()` — блокирующие PortAudio syscalls, каждый может занимать 100-500мс на холодном старте. В оригинальном `start_recording` они вызывались *внутри* `with _state_lock:` — всё это время любой другой код, пытающийся взять lock (включая event callback для следующего fn), блокировался.
**Как применить:** для macOS daemons с CGEventTap — никогда не держать shared lock под блокирующим syscall. Event callback должен возвращаться за миллисекунды, иначе system events начнут дропаться или tap отключится. Держи lock только над RAM-операциями; I/O — отдельно, желательно в thread. В govori это решено частично: `_start_mic_stream` всё ещё держит lock под `sd.InputStream.start()`, но это терпимо т.к. callback больше не ждёт этот lock (state уже установлен).
