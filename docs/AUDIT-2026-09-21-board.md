# Аудит 21.09.2026 — интерактивная доска (этап 1 плана)

Повод: прошлая сессия Arena умерла на доработке доски; в 0.11.0/0.11.1 уже закрыты дубль текста, панели под topbar, CAS-sync и стрелки. Этот документ — **полный аудит по плану этапа 1** (редактор · геометрия · размеры · backend), без новой ветки, без Electron и без «больше фич». Источник истины — код `8875f84` (`v0.11.1`).

Принцип тот же: **better, not bigger**. Сначала дыры и целостность, не копия Figma.

---

## Карта кода (что открывать)

| Слой | Файл | Роль |
|---|---|---|
| Геометрия | `web/src/lib/board.js` (110 стр.) | ratios, frame_height, якоря стрелок (u,v), bbox, цвета, шрифты — **одна** формула с сервером |
| Холст | `web/src/components/BoardCanvas.jsx` (~830) | canvas + HTML-слой текста, жесты, undo, `PUT /sync` |
| Страница | `web/src/pages/Board.jsx` (~320) | список/редактор, ctx-бар 44px, тулбар слева, кадры справа, mobile bar |
| Стили | `web/src/index.css:657–665` | `body.board-page` прячет tabbar, ctx без скроллбара |
| Сервис | `core/services/boards.py` (~767) | CRUD, `sync_board` (CAS+token), `save_asset`, chat_rule, frame_height |
| API | `core/api/app.py:1491–1655` | `/api/boards…`, `/sync`, `/asset`, legacy item CRUD |
| Модель | `core/db.py:246–273` | `Board.revision/last_sync/view`, `BoardItem` |
| Тесты | `tests/test_boards.py` (8) | CRUD, раскадровка, chat, API, graph, agent, **sync atomic**, asset |
| Доки | `docs/features.md` «Доска», `CHANGELOG.md` 0.11.0–0.11.1 | |

Версия: `core/__init__.py` → `0.11.1`. CI на `8875f84` зелёный (pytest 3.11/3.12 + `web/site up to date`). Локально `tests/test_boards.py`: **8 passed**.

---

## Что уже сделано хорошо (0.11.1) — не ломать

1. **Текст без дублей.** `EditableText`: contentEditable заполняется **один раз** в `useLayoutEffect([editing])`, не через React-children. `onInput` → `innerText` в `data`, React DOM не переписывает. Esc откатывает к `startVal`.
2. **Один DOM-слой на текстовый объект.** Стикер/текст/подпись кадра рисуются только HTML-слоем; canvas их не дублирует. Подпись стрелки — canvas, HTML только в edit.
3. **Панели вне холста.** Ctx-бар — отдельная строка `h-[44px]` под шапкой редактора (`Board.jsx ~179`). Тулбар — колонка слева `border-r`, не absolute поверх. Topbar сайта (`--topbar-h: 56px`) + `height: calc(100dvh - var(--topbar-h))`. `body.board-page .tabbar { display: none }`.
4. **Стрелки.** `anchorPoint` / `nearestAnchor` / `arrowPoints` с (u,v); legacy без u/v — `clipToBox` к границе. Ручки from/to, перенос за тело (move), прилипание при создании.
5. **Сохранение.** `PUT /api/boards/{id}/sync` + `revision` CAS + `token` идемпотентность (`last_sync`). 409 → баннер merge (`adoptFresh`). Камера (`view`) revision не двигает. Лимит 5000 объектов / 8 МБ.
6. **Картинки.** `POST …/asset`: PNG/JPG/WebP/GIF, EXIF, thumbnail 4096, hash-dedup, путь только `boards/…` в `data/media`. SVG/HTML → 400. Внешний URL в `src` → `null`.
7. **Undo.** Снимки JSON до 100; после sync временные id чинятся regexp-ом в истории. Правка текста = один snapshot на сеанс (`startEdit`/`stopEdit`).
8. **Chat.** `раскадровка:`, `на доску:`, `что по доске?`, `мои доски` — rules, без LLM. Стикер не кладётся поверх (`place_sticky`).

---

## Этап 1A. Редактор и взаимодействия — чеклист

Легенда: ✅ ок по коду · ⚠️ дыра/край · ❌ сломано · ⏸ не реализовано (и не врём, что есть)

### Создание и выбор

| Сценарий | Статус | Где / комментарий |
|---|---|---|
| Рука по умолчанию | ✅ | `Board.jsx` `useState('hand')`; H/V, Space, МКН |
| Создание протягиванием + ghost | ✅ | `kind:'create'`, `setGhost`, клик < 6px → DEFAULT_SIZE |
| Стикер квадрат / кадр по ratio / Shift-квадрат | ✅ | `onPointerMove` create |
| Выбор кликом | ✅ | hit z-desc |
| Рамка (marquee) | ✅ | `rectsIntersect`; стрелка — если конец в рамке |
| Shift/Ctrl мультивыбор | ✅ | toggle в set |
| Ctrl+A | ✅ | |
| Esc сброс / инструмент | ✅ | |
| Двойной клик → edit; пусто → стикер | ✅ | |
| Enter на sticky/text/frame | ✅ | |
| Hit по повёрнутому | ✅ | `unrotate` |

### Перенос / ресайз / поворот

| Сценарий | Статус | Где / комментарий |
|---|---|---|
| Move одного / группы | ✅ | `placeFrom` от orig |
| Alt+drag = копия | ✅ | snapshot + `duplicateSel` mid-drag |
| Shift-ось / Ctrl-snap 20 | ✅ | |
| Стрелки клавиатуры ±1/±10 | ✅ | snapshot только на `!repeat` — ок |
| 8 ручек + пропорция frame/image/sticky | ✅ | corner+shift; frame всегда ratio |
| Group scale за угол (шрифт растёт) | ✅ | `scaleFrom` sticky/text font_size |
| Поворот, Shift 15° | ✅ | ручка над mid-top |
| Ink move/scale | ✅ | points + width |
| Free arrow move (концы без item) | ✅ | |
| Привязанная стрелка «едет» с объектом | ✅ | концы по item id, redraw |
| **Locked** | ❌ | В ctx есть `a==='lock'`, **пункта меню нет**, `data.locked` нигде не читается (move/resize/delete). Мёртвый код + импорт `Lock`. Убрать или довести. |
| Ресайз текста по контенту | ✅ | `onGrow` у text |
| Ресайз кадра с n-ручкой (y) | ✅ | `it.y = oy+oh-it.h` |

### Стрелки

| Сценарий | Статус | Где / комментарий |
|---|---|---|
| Прилипание к границе (u,v) | ✅ | |
| Перенос за тело | ✅ | hit distSeg < 7/k |
| Drag конца + reattach | ✅ | `arrowend` |
| Свободная линия | ✅ | from/to как {x,y} |
| Стиль arrow/line, цвет, толщина | ✅ | ctx-бар |
| Подпись стрелки (dblclick) | ✅ | |
| Стрелка внутри/к кадру | ✅ | frame в hit (не skip) |
| Стрелка → ink | ✅ | from/to ink запрещены (`type !== 'ink'`) |
| Удаление объекта уносит стрелки | ✅ | client + `delete_items` + sync drop |
| Стрелка на несуществующий id при sync | ✅ | ValueError, откат |

### Текст

| Сценарий | Статус | Где / комментарий |
|---|---|---|
| Один слой, без дубля букв | ✅ | EditableText |
| Esc откат | ✅ | |
| blur / клик мимо → stopEdit | ✅ | pointerdown холста зовёт stopEdit |
| Ctrl+Enter / single Enter | ✅ | |
| Шрифт/size/bold/italic/align/цвет | ✅ | setSelData + text_style сервер |
| Markdown-light (просмотр) | ✅ | `Md` / `inline` |
| Быстрый ввод + автосейв 500ms | ✅ | schedule; inflight→again |
| IME/составной ввод | ⚠️ | не тестировался отдельно; innerText обычно ок, но нет явной защиты `isComposing` |
| Курсор после sync id remap | ✅ | editing id обновляется из id_map |

### Карандаш / ластик / картинки

| Сценарий | Статус | Где / комментарий |
|---|---|---|
| Pen stroke | ✅ | quadratic сглаживание в draw |
| Ластик **целого** штриха | ⏸ | CHANGELOG: «ластик стирает штрих целиком» — by design, не кусок |
| Ctrl+V картинка | ✅ | clipboard files → asset |
| Drop файла / на кадр | ✅ | frame → data.image |
| Drop note (`application/x-note`) | ✅ | |
| EXIF/huge/SVG | ✅ | сервер |

### Буфер и история

| Сценарий | Статус | Где / комментарий |
|---|---|---|
| Ctrl+Z/Y/Shift+Z | ✅ | глобально, если не typing |
| Ctrl+D duplicate | ✅ | стрелки между дублями тоже |
| Ctrl+C | ✅ | только `clipRef` (внутри вкладки), system clipboard не трогаем |
| **Ctrl+V объектов** | ❌ | `onPaste`: `clipRef && !t` — если в OS-буфере есть **любой** текст (часто), объекты **не** вставляются, вместо этого создаётся sticky/text из `text/plain`. Плюс paste через `setSel(старые id)+duplicateSel`: если оригинал удалён — пусто. Нужен paste клонами из `clipRef` с приоритетом над plain text. |
| Ctrl+X | ✅ | clip + delete |
| Ctrl+V текст → sticky/text | ✅ | >140 → text |
| История >100 | ✅ | shift |
| Undo после id_map | ✅ | regexp id/item |
| Серверная история undo | ⏸ | только сессия вкладки (CHANGELOG) |

### Камера / экспорт

| Сценарий | Статус | Где / комментарий |
|---|---|---|
| Wheel pan, Ctrl+wheel zoom | ✅ | passive:false |
| Pinch | ✅ | |
| fitAll / fit sel / 100% | ✅ | Ctrl+1/2/0 |
| Restore view если центр в viewport, иначе fit | ✅ | load effect |
| zoom-to-fit в пустоту | ✅ | `fitTo(null)` → дефолт центр |
| Export PNG / print storyboard | ✅ | |
| beforeunload flush | ✅ | |

### Конфликт / reload

| Сценарий | Статус | Где / комментарий |
|---|---|---|
| 409 → banner merge/take | ✅ | |
| adoptFresh keepMine | ✅ | diff strip + новые id |
| Chat sticky во время открытой вкладки | ✅ | revision↑ → 409 на next sync |
| Reload с dirty | ⚠️ | beforeunload flush async **без** `e.returnValue` — браузер может убить вкладку до ответа; риск потери последних 500ms жеста |
| Две вкладки одновременно | ✅ | CAS; UX — баннер |

---

## Этап 1B. Геометрия и визуальные слои

| Проверка | Статус | Детали |
|---|---|---|
| Кнопки не под topbar сайта | ✅ | редактор ниже `--topbar-h`; ctx не absolute |
| Тулбар не перекрывает объекты | ✅ | flex-колонка вне wrap |
| Ctx-бар фиксированной высоты | ✅ | 44px, overflow-x auto |
| Контекстное меню в зоне | ✅ | `min(m.x, W-220)`, `min(m.y, H-260)` относительно `.board-wrap` |
| Панель кадров справа | ✅ | 250px lg+, toggle |
| Холст vs нижняя навигация сайта | ✅ | tabbar hidden на board-page |
| **Mobile tool dock vs холст** | ⚠️ | absolute `bottom-0` bar (~52px + safe-area **не** заложен) **поверх** canvas, padding у wrap нет → объекты/ручки за нижним краем недоступны, especially iPhone home indicator |
| Горизонтальный скролл страницы | ✅ | board-page overflow hidden; ctx scrollbar hidden |
| Тема dark/light sticky/ink | ✅ | MutationObserver class; STICKY light/dark |
| Номера/sec/label читаемы на зуме | ✅ | fs ∝ w/320; HTML scale |
| Tooltip side=right у тулбара | ✅ | CSS `[data-tip-side=right]` |
| z-index menu 70 / ctx 60 | ✅ | |
| `data-tip` на topbar не под ctx | ✅ | ctx ниже шапки редактора |

### Тестовые размеры (прогон по коду + что гонять в браузере)

Разметка адаптивная (`md:` тулбар, `lg:` кадры, mobile dock). **Живой скрин-прогон в этой среде не делался** (нет GUI-браузера с вашими данными). Чеклист для ручного:

| Viewport | Ожидание | Риск |
|---|---|---|
| 1440×900 | тулбар+кадры+ctx | низкий |
| 1280×720 | то же, меньше холст | низкий |
| 1024×768 | кадры ещё есть (lg=1024) | ctx overflow-x |
| 768×1024 | без side frames, есть тулбар md | ок |
| 390×844 | mobile dock, нет left tools | **dock ест низ холста** |
| 320×700 | то же + узкий ctx scroll | dock + safe-area |

---

## Этап 1C. Backend

| Кейс | Статус | Где |
|---|---|---|
| CAS старая revision → BoardConflict/409 | ✅ | sync + test |
| Повтор token → тот же id_map, без дублей | ✅ | last_sync |
| Временные id < 0 → id_map | ✅ | |
| Стрелки remap after flush | ✅ | |
| Удаление = нет в snapshot | ✅ | current not in ids → delete |
| Стрелка на missing item | ✅ | ValueError до commit |
| inf/nan coords | ✅ | number() finite |
| Слишком большой JSON / >5000 | ✅ | |
| min size < 12 (не arrow/ink) | ✅ | |
| Чужой item_id другой доски | ✅ | |
| Архив → sync ValueError | ✅ | |
| Restore archive | ✅ | PUT archived:false (UI «вернуть») |
| SVG onload | ✅ | save_asset ValueError |
| path traversal src | ✅ | _safe_src |
| External URL image | ✅ | src null |
| bulk_update / per-item API | ✅ | legacy; редактор ими не пользуется (только sync) |
| race two sync same rev | ✅ | SQL UPDATE … WHERE revision |
| **Повреждённый data JSON в БД** | ⚠️ | `_data` → `{}` молча; объект «пустой», не 500 — ок, но UI может удивить |
| **5000 объектов perf** | ⚠️ | лимит есть; тест на 300 заявлен в CHANGELOG, автотеста нагрузки нет |
| note_id/link_id битые | ✅ | сбрасываются в null |
| frame_height JS ≡ Python | ✅ | одна формула (caption lines) |
| green в text_color/ink | ✅ | color() + themeColor |
| chat_rule ложные срабатывания | ✅ | «сценарий: такой…» длинный → None; test |
| graph board node | ✅ | test |
| agent routes | ✅ | test |

### Чего в тестах ещё нет (добавить при правках)

- paste/clone id remap на клиенте — юнит на `board.js` нет (нет vitest в web/).
- `adoptFresh` merge.
- beforeunload / двойной inflight schedule.
- 409 через TestClient уже есть; multi-client concurrent — нет.
- Mobile layout — только руками.

---

## Найденные баги (приоритет)

### P0 — чинить сейчас

1. **Ctrl+V скопированных объектов почти не работает**  
   `BoardCanvas.jsx` `onPaste`: условие `clipRef && !t` отсекает вставку, как только OS-буфер непустой. Плюс duplicate через старые id.  
   *Фикс:* если `clipRef.length` — клонировать из clip (новые uid, +24,+24), игнор plain text; иначе image/text.

2. **Mobile dock поверх холста без padding**  
   `Board.jsx` absolute bottom bar; `board-wrap` на всю flex-area.  
   *Фикс:* `padding-bottom` у canvas-колонки на `md:hidden` зоне ≈ 56px + `safe-area-inset-bottom`, либо dock в document flow.

### P1 — добить или вырезать

3. **Lock мёртвый** — убрать ветку/`Lock` import **или** провести: ignore move/resize/delete + пункт меню + иконка. Сейчас — мусор.
4. **beforeunload без гарантии flush** — `navigator.sendBeacon` на sync сложно (JSON+auth); минимум `e.preventDefault(); e.returnValue=''` если dirty, плюс keepalive fetch.
5. **Ластик только whole stroke** — ок как limitation; если нужен partial — отдельная задача, не сейчас.

### P2 — качество

6. IME `isComposing` в EditableText.
7. Нет мини-карты (не планируется — CHANGELOG).
8. Нет серверного undo.
9. Бандл сайта ~1 МБ (board+recharts+всё) — не баг доски, но первый paint тяжёлый; code-split — этап 2.
10. `.bat` LF без `.gitattributes` — Windows ZIP риск (вне доски, этап 2 launch).

### Не баги (ложные из скринов/памяти)

- «Текст дублируется» / «панели под topbar» — **закрыто в 0.11.1**. Если снова видишь дубль — это либо старый `web/site` без rebuild, либо другой баг (пришли свежий скрин + версия из подвала).
- «Чат еле отвечает» из прошлой сессии Arena — **не** про latency продукта; измерений не было.

---

## Этап 2 (план) — только инвентаризация, без работы в этом файле

Кратко, чтобы план не потерялся; **не делается в рамках этого аудита**:

| Тема | Сейчас в репо | Оценка |
|---|---|---|
| Первый запуск | `install.bat`, `setup.py`, `start.bat`, `config.example.yaml` | wizard есть; .bat LF |
| Трей / автозапуск | `autostart.bat`, voice_client | нет нормального tray-UI статуса |
| Backup | scheduler/proactive упоминания | нет одной кнопки «бэкап» в UI |
| Onboarding | Empty hints на доске/разделах | нет единого тура |
| Jarvis vs Marvin | identity, NOTICE, Apache-2 | ок как продукт |
| Electron | — | **не нужно** |

Приоритет этапа 2 после зелёной доски: launch/status/backup/onboarding, не виджеты.

---

## Что сделано по итогам этого аудита (код)

Минимальные правки по P0/P1 без расползания scope:

1. `BoardCanvas.jsx` — paste объектов из `clipRef` клонами; приоритет над plain text; убран мёртвый lock.
2. `Board.jsx` — нижний отступ холста под mobile dock + safe-area.

Regression: `pytest tests/test_boards.py` + ручной Ctrl+C/V, mobile 390.

**Не** делалось: partial eraser, beacon flush, code-split, .gitattributes, bump версии (оставить на commit с CHANGELOG, если пойдут в main).

---

## План работ дальше (коротко)

1. Закрыть P0/P1 из этого файла (часть уже в коде рядом с аудитом).
2. Ручной прогон чеклиста 1A на 1440 и 390 + конфликт из чата.
3. 1–2 теста API на archived sync и huge ink points (если дырок всплывёт).
4. `docs/features.md` — одна строка про clipboard «только в пределах вкладки».
5. Этап 2 — отдельный `AUDIT-…-launch.md`, не смешивать.

---

## Вердикт

Доска в `0.11.1` — **уже рабочий FigJam-light**, не прототип: геометрия единая, sync честный, текст и панели починены. Остались **реальные** дыры: **вставка скопированных объектов**, **мобильный низ**, **dead lock**, и мягкий риск потери dirty на закрытии вкладки. Это не «переписать редактор», а точечный pass.

Этап 1 плана (аудит) — этот файл. Исправления P0 — в тех же `BoardCanvas.jsx` / `Board.jsx` без новой ветки.
