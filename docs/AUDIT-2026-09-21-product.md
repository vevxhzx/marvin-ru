# Аудит продукта 21.09.2026 — все фронты + этап 2 плана

Повод: закрыть план из прошлой сессии (доска → система целиком). Источник истины — код ветки `arena/01a0c4fe-marvin-ru` после `ccb29c6` + этот pass. Принцип **better, not bigger**: без Electron, без мультипользователя, без копии Figma.

Связанные документы: `docs/AUDIT-2026-09-21-board.md` (этап 1), `docs/AUDIT-2026-09-18-presence.md`, `ROADMAP.md`.

---

## 0. Статус этапов плана

| # | Этап плана | Статус | Где результат |
|---|---|---|---|
| 1 | Аудит и правка доски | ✅ | `AUDIT-2026-09-21-board.md` + Ctrl+V / mobile dock / lock |
| 2 | Регрессия доски (размеры) | ⚠️ код+чеклист; живой Chromium GUI здесь нет | чеклист в board-аудите |
| 3 | Backend доски + тесты | ✅ | `tests/test_boards.py` 8, sync/asset |
| 4 | Навигация и UX сценарии | ✅ этот файл §3–4 | |
| 5 | Windows-запуск / update | ✅ §5 + `.gitattributes` | |
| 6 | Минимальные launch/status/backup | ✅ restore UI + force backup | §6 |
| 7 | Jarvis/Marvin sync | ✅ identity + STT hints | §7 |
| 8 | Полный pytest + site build | ✅ | 336+ tests |
| 9 | Итоговый отчёт | ✅ | этот файл |

---

## 1. Карта продукта (что это)

**Marvin** — личный ассистент на ПК: Telegram + сайт + голос. Одна SQLite `data/assistant.db`, имя из `config.yaml` (`core/identity.py`). Лицензия Apache-2.0, `NOTICE`.

| Канал | Вход | Код |
|---|---|---|
| Сайт | React/Vite → `web/site` (закоммичен build) | `web/src/**`, API FastAPI |
| Telegram | aiogram bot, owner_id only | `core/telegram/bot.py` |
| Голос ПК | `voice.bat` → `voice_client.py` → API | STT/TTS, wake |
| Ядро | `start.bat` → `run.py` | scheduler, brain, services |

**Разделы сайта (NAV):** сегодня · задачи · календарь · финансы · заказы · мозг · **доска** · люди · память · настройки. Alt+0…9. Mobile tabbar 2–5 слотов (prefs).

---

## 2. Тесты и CI (факт)

- Локально: **333** было + **3** backup/restore = **336** (или 333+3 в test_backup_restore).
- `tests/test_boards.py` — 8.
- `tests/test_backup_restore.py` — list/restore/path-traversal/API.
- CI jobs: pytest 3.11, 3.12, `web/site up to date` (npm build + porcelain).
- Секреты не в git (`.gitignore`: config.yaml, data/, *.db, .env, .venv).

---

## 3. UX / юзабилити по разделам

Легенда: 💎 дорого и цельно · ✅ ок · ⚠️ шероховатость · ❌ дыра

### 3.1 Оболочка (App)

| | |
|---|---|
| Sidebar groups «рабочее / система» | ✅ |
| LiveDot + LivePopover (presence) | 💎 |
| Palette Ctrl+K | 💎 |
| Chat drawer | ✅ |
| Theme auto/light/dark + accents/tints | 💎 design tokens в `index.css` |
| PageGuard на crash страницы | ✅ |
| Mobile tabbar vs board (tabbar hidden) | ✅ |
| Footer version + ollama | ✅ |
| 10 пунктов меню | ⚠️ много для новичка; скрытие в «вид» спасает, default всё равно dense |
| Бандл ~1.0 MB JS gzip 305 KB | ⚠️ первый paint; board+recharts+finance в одном chunk — code-split P2 |

### 3.2 Сегодня

| | |
|---|---|
| Приветствие + context line | 💎 |
| Composer → chat stream + act-cards | 💎 |
| Блоки drag-reorder / hide | ✅ |
| Focus / ScreenTime / Forecast widgets | ✅ |
| Empty states с hint → chat | 💎 единый паттерн |
| «сэр» в empty | ⚠️ address из prefs, но часть empty хардкодит «сэр» |

### 3.3 Задачи / цели / календарь / финансы / заказы / люди / мозг / память

| Раздел | Оценка | Заметки |
|---|---|---|
| Задачи | ✅ | Seg views, swipe, aims tab, quick add via chat |
| Календарь | ✅ | month/week, shared done with tasks |
| Финансы | 💎/⚠️ | мощно (долги, 50/30/20, forecast) — перегружает новичка; OK для фриланс-ядра |
| Заказы | ✅ | gated `freelance.enabled` |
| Люди | ✅ | dossier auto |
| Мозг | ✅ | notes/links/graph |
| Память | ✅ | facts layers + timeline (0.10) |
| Настройки | 💎 | 8 cats, status cards, appearance — образец |

### 3.4 Доска

См. board-аудит. После фикса: Ctrl+V объектов, mobile dock padding, dead lock out.

### 3.5 Общие UI-паттерны (целостность дизайна)

**Уже едино:**
- `PageHead` + mono `label` kicker + `h1` tracking
- `Empty` + glyph + hint chip
- `btn-primary` / `btn-soft` / `btn-ghost` / `btn-icon`
- `Card` / `Section` / `Field` / `Seg` / `Pills` / `Switch`
- 4-pt spacing, Inter + JetBrains Mono, semantic pos/neg/warn
- focus-visible accent ring

**Расхождения (не критично):**
- Категории финансов / screen / memory — hardcoded hex (`#7c3aed`, `#30d158`) вместо CSS vars → при кастомном акценте «чужие» пятна.
- `Widgets.jsx` `var(--green, #30d158)` — fallback ок, лучше `--pos`.
- PDF storyboard print — свои `#111/#ddd`, нормально (print).
- Settings GoogleConnect: `bg-emerald-500` tailwind raw — единственный raw emerald.

**К какому дизайну идти (не «другой продукт», а заточка текущего):**

1. **Оставить** нейтральный paper + strong accent (уже «дорого» на Today/Settings/Board). Не Material, не glassmorphism-everywhere.
2. **Упростить IA для first-run:** wizard после setup предлагает «режим»: *личное* (скрыть заказы/доску/фриланс) / *фриланс* (как сейчас) / *всё*. Сейчас freelance toggle есть, но default menu всё равно 8 рабочих пунктов.
3. **Не** делать Electron shell. Tray уже в voice_client; ядро = console window — принять или позже tiny tray-host без Chromium.
4. Code-split: `Board` + `Finance` charts dynamic import — единственный perf-ход с ROI.

---

## 4. Первый запуск (путь «ничего не знаю о Python»)

| Шаг | Как сейчас | Оценка |
|---|---|---|
| Download ZIP / Release | README + install.md | ✅ |
| Python 3.12 + PATH | install.bat checks `where python` | ✅ |
| `install.bat` → setup.py venv+pip | chcp 65001 в setup.py | ✅ |
| `start.bat` loop + pip quiet | ✅ | |
| Browser `/setup` wizard | hardware → model → cloud → TG | 💎 |
| Ollama optional | cloud-only path | ✅ |
| TG only / site only | with_tg flag, token empty → warn | ✅ |
| Voice separate | install_voice + voice.bat | ✅ понятно, но 2 окна |
| Phone | phone.bat + QR | ✅ |
| Update | update.bat pip | ✅ |
| Autostart | Startup .lnk WindowStyle=7 | ✅ |
| Publish | publish.bat gh release zip | ✅ Marvin-specific |

**Боли новичка:**
1. Два чёрных окна (start + voice) — «это нормально?» README говорит, но страшно.
2. Ollama «нужна или нет» — мастер объясняет; README table local/hybrid/cloud ок.
3. `.bat` были **LF-only** → на чистом ZIP `cmd` мог ломать `goto` — **фикc: `.gitattributes *.bat eol=crlf`**.
4. Restore из бэкапа был «скопируй .db руками» (ROADMAP P1) — **сделано UI**.

**Не делать:** Electron (+100–200 МБ). Сначала: один `start.bat` уже поднимает ядро; voice опционален.

---

## 5. Windows launch (этап 2 план)

| Фича из плана | Сейчас | Вердикт |
|---|---|---|
| start.bat единый | да, loop restart | ✅ |
| Системный трей ядра | нет (только voice tray) | ⏸ P2 tiny host; не Electron |
| Автозапуск | autostart.bat | ✅ |
| Отдельный процесс голоса | voice.bat | ✅ |
| Browser only first run | ASSISTANT_NO_BROWSER + setup_done | ✅ |
| Статус ядро/TG/Ollama/voice/PC | Settings → система → status cards | 💎 |
| Кнопка «перезапустить» | нет (текст «закрой start.bat») | ⚠️ API restart опасен; оставить текстом |
| Открыть папку данных | нет | ⚠️ можно `file://` не работает; показать path + copy |
| Бэкап сейчас | был | ✅ + force если disabled |
| Restore | **новый** | ✅ |
| Диагностика без мусора | status cards + «проверь себя» chat/health | ✅ |
| Win notifications | browser Notification API | ✅ partial (не toast OS из ядра) |
| Виджет / DND / global hotkeys | нет | ⏸ «можно потом» |
| Свернуть в трей без консоли | нет | ⏸ |

---

## 6. Backup / restore (сделано в этом pass)

| API | |
|---|---|
| `POST /api/backup` | `backup_db(force=True)` — ручной даже если nightly off |
| `GET /api/backups` | list backup-*.db |
| `POST /api/backups/restore` `{name}` | safety pre-restore, replace db, drop wal/shm, needs_restart |

UI: Настройки → память и данные → «восстановить из бэкапа».  
Тесты: `tests/test_backup_restore.py`.  
Ограничение (честно): media не версионируется по дате снимка (зеркало актуальное); после restore обязателен restart.

---

## 7. Jarvis vs Marvin (целостность бренда)

| | |
|---|---|
| Default name Марвин | `identity.NAME` / config.example |
| NOTICE / LICENSE Apache-2 | ✅ |
| README «Marvin» | ✅ |
| STT Whisper prompt «Джарвис» | ❌→✅ заменён на `identity.title()` |
| persona «кентом с мозгами Джарвиса» | ✅ метафора ок (стиль, не бренд продукта) |
| check_ollama.py docstring Джарвис | ⚠️ мелочь |
| bot log «ДВА ДЖАРВИСА» | ⚠️ внутренний лог |
| Titles окон bat «Assistant» | ✅ нейтрально (имя в UI) |

Продукт = **Marvin** (репо marvin-ru); «Джарвис» — только tone-of-voice / legacy logs.

---

## 8. Безопасность (коротко)

Уже крепко (из прошлых аудитов + код):
- owner_id TG only
- API token off-localhost
- money/destructive confirm
- board asset no SVG/HTML, path traversal blocked
- restore name allowlist regex
- open_app no shell
- window titles not in prompt

P2 из ROADMAP: rate-limit chat off-loopback; pending id binding.

---

## 9. Что чинить / что нет

### Сделано сейчас
1. Board P0 (прошлый commit).
2. `.gitattributes` bat CRLF.
3. Backup restore API+UI+tests.
4. `backup_db(force=)` для кнопки.
5. STT prompts → identity name.
6. Этот аудит + board-аудит.

### Нужно (P1, мало кода)
- Empty «сэр» → `prefs.address` / identity owner.
- Показать path `data/` copy-button в status.
- check_ollama / dual-bot log: «два ядра» вместо Джарвис.

### Можно потом (P2)
- dynamic import Board + Finance recharts.
- Core tray without Electron (pystray + hidden console).
- Partial ink eraser.
- Rate-limit API chat.

### Не нужно
- Electron, collab boards, accounts, cloud backend, mobile native app, Figma-layers.

---

## 10. Дизайн: итоговая рекомендация

**Не менять визуальный язык.** Система уже цельная (tokens, type, empty, status).  
«Выглядит дорого»: Today, Settings status, Board editor, Chat act-cards, LiveDot.  
«Ещё прототип»: Finance density для non-freelancer; 10 nav items; console windows; 1 MB bundle.

Траектория: **tighten** (fewer defaults visible, split chunks, restore/backup done) — не **rebrand**.

---

## 11. Проверка «обычный пользователь понимает?»

| Вопрос | Ответ в продукте |
|---|---|
| Что такое мозг? | Раздел + empty hints + docs |
| Задачи vs цели vs вехи | Aims UI + chat rules |
| Где доска? | Nav + Alt+0 |
| Где клиент? | Люди / заказы |
| Почему заказ просрочен | pulse / late_nudge settings |
| Пачкой оплата | client pay_mode |
| Деньги | Finance + chat |
| Экранное время | Settings voice + Today block |
| Зачем voice.bat | install.md + status card |
| «Без модели» | footer + status ollama |
| Куда данные | data/assistant.db, settings copy |
| Архив | boards/orders patterns |
| Обновление | update.bat / publish releases |
| Restore backup | **теперь UI** |

---

## 12. Вердикт

Продукт для **одного человека на Windows** уже зрелый: onboarding wizard, status, presence, board, freelance stack. Этап 1 (доска) и этап 2 (launch hygiene + backup restore + bat CRLF + brand STT) — **закрыты в коде и документах**. Остальное — polish и ROADMAP P2, не «дырявый MVP».

Дальше по желанию: code-split, tray для ядра, address в empty states. Electron — нет.
