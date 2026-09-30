# Дизайн-система сайта

Один источник правды — `src/index.css` (голова файла). Всё остальное собирается из этих классов; новые «локальные» стили в компонентах не заводим.

## Принципы
- Ассистент — центр. На главной сверху: контекст дня и композер; ниже — задачи и события; деньги свёрнуты.
- **Три ступени фона одного тёмно-синего.** Тёмная тема строится на `--bg`/`--sf`/`--sf2` (#0f1530 / #151c3d / #1c2550 — surface-1/2/3): страница — самая тёмная, карточка светлее, вложенная поверхность ещё светлее. Светлая тема сохраняется (`--bg #e9ecf3`, `--sf #ffffff`), ступени те же токены.
- **Один лаймовый градиент-герой на экран.** `.hero` — лаймовый градиент (`--lime`), только для денег/успеха. Не ставим два героя на одну страницу.
- **Цвет только по смыслу.** Лайм = деньги/ok, янтарь = ожидание, красный = просрочка/риск, фиолетовый = ИИ. Всё остальное — нейтральные поверхности. Ярких «светлых» карточек (лавандовая `.p1`, мятная `.p2`) больше нет: это тёмные карточки с тинтом своего цвета (10–12 %) и рамкой 1px.
- Плоские поверхности, тонкие линии, тени только для приподнятых слоёв.
- Действия ассистента показываются карточкой результата (`.act-card`), а не техническим логом.
- Каждая пустота объясняет, что делать (`Empty` с подсказкой → фраза уходит в чат). Пустые виджеты (нет данных) делаем компактными, а не «полупустыми на пол-экрана».
- Минимальный размер текста — 12px, подписи (`--ink-3`) — с достаточным контрастом.

## Палитра
| смысл | токен | тёмная | светлая |
|---|---|---|---|
| поверхность 1 (страница) | `--bg` | `#0f1530` | `#e9ecf3` |
| поверхность 2 (карточка) | `--sf` | `#151c3d` | `#ffffff` |
| поверхность 3 (вложенная) | `--sf2` | `#1c2550` | `#f0f1f6` |
| деньги / ok | `--lime` / `--pos` | `#c6f24a` | `#3f7d12` |
| ожидание | `--amber` / `--warn` | `#f5b400` | `#a16207` |
| просрочка / риск | `--red` / `--neg` | `#ff5b7a` | `#d92d4b` |
| ИИ | `--ai` | `#a78bfa` | `#7c3aed` |
| акцент (бренд) | `--accent` / `--acc` | настройка | настройка |

Тёмная тема — те же токены, переопределены в `.dark` / `:root[data-theme="dark"]`.

## Токены
| группа | токены |
|---|---|
| фон и поверхности | `--bg` `--bg-2` `--surface` `--surface-2` `--sf` `--sf2` `--fill` `--fill-2` |
| текст | `--ink` (основной) `--ink-2` (вторичный) `--ink-3` (приглушённый) |
| линии | `--line` `--line-2` |
| смысл | `--lime` `--amber` `--red` `--ai` и алиасы `--pos` `--neg` `--warn` (+ `-soft` для подложек) |
| карточки-тинты | `.tint-ok .tint-warn .tint-neg .tint-ai .tint-acc` (тёмный фон + тинт 10–12 % + рамка 1px) |
| тени | `--shadow-1..3` |
| радиусы | `--r-sm` `--r-md` `--r-lg` `--r-xl` |
| отступы | `--s-1..10` (4px-сетка) |
| раскладка | `--sidebar-w` `--sidebar-w-min` `--topbar-h` `--content-max` |
| движение | `--t-fast` `--t-base`, `--ease-out` `--ease-io` `--ease-spring` |

## Компоненты (классы)
- Текст: `.display .h1 .h2 .h3 .h4 .t-body .t-sm .caption .label .idx .num .mono .muted .faint`
- Поверхности: `.panel .card .elevated .fill .rule .hair .row .row-hover`
- Кнопки: `.btn-primary .btn-ghost .btn-soft .btn-dark .btn-danger .btn-icon(.outlined)` + `.btn-sm .btn-lg`
- Выбор: `.pill(.on) .chip(.on) .seg .switch(.on) .badge(.accent/.pos/.neg/.warn)`
- Ввод: `.input .composer .inline-edit`
- Подсказки: `[data-tip]` (+ `data-tip-side="right|bottom"`), `.kbd`
- Ассистент: `.act-card` `.msg-me` `.msg-bot` `.md` `.cursor` `.thinking` `.dot-live` `.now-line`
- React (`components/ui.jsx`): `Section PageHead Empty Sheet Field Seg Pills Switch Skeleton ListSkeleton Confirm Swipe` и тосты `toast()/useToast()/Toaster`.

## Главная — настраивается
«настроить главную» внизу страницы: блоки вкл/выкл и порядок (стрелки или перетаскивание мышью), приветствие/строка контекста/быстрые слова, плотность «спокойно/подробно». Хранится в `localStorage` (`today.prefs.v1`, `today.order.v2`). По умолчанию показаны только задачи, календарь и свёрнутые деньги.

## Клавиатура
`⌘K` палитра · `⌘J` чат · `Esc` закрыть · `Enter` отправить, `Shift+Enter` новая строка · `Alt+1…7` разделы · в календаре `←/→` день, `T` сегодня · в палитре `↑↓ / Tab / Ctrl+J/K`.

## События между частями интерфейса
- `assistant:chat` `{text, send?}` — открыть чат с текстом (send — отправить сразу).
- `assistant:busy` `true|false` — ассистент думает (статус в сайдбаре).
- `assistant:event` — событие SSE от ядра (reminder, chat, recurring, pc_state…).

## Настройки вида (`src/lib/prefs.js`)

Один стор для всего, что пользователь может подкрутить в интерфейсе. Хранится в `localStorage` под ключом `ui.prefs.v1`, применяется CSS-переменными на `<html>` (`apply()`), поэтому работает без перезагрузки и без бэкенда.

| ключ | что делает | где крутится |
|---|---|---|
| `accent` | акцентный цвет (6 вариантов из `ACCENTS`) → `--accent-light/--accent-dark` | настройки → вид |
| `font` | масштаб интерфейса `--ui-zoom` (0.92 / 1 / 1.1) | настройки → вид |
| `radius` | коэффициент скруглений `--r-k`; все `rounded-*` в Tailwind и `.panel/.sheet` идут через `calc(Npx * var(--r-k))` | настройки → вид |
| `motion` | `false` → класс `.no-motion` на html, анимации выключены | настройки → вид |
| `hiddenNav` | скрытые разделы боковой панели («сегодня» и «настройки» нельзя скрыть, страницы остаются доступны через ⌘K) | настройки → вид |
| `tabbar` | 2–5 путей для нижней панели телефона; `compactNav` — только иконки | настройки → вид |
| `address` | как обращаться в приветствии (пусто → `owner.name` из config) | вид / «настроить главную» |
| `showGreeting / showContext / showQuick` | шапка главной | вид / «настроить главную» |
| `density` | `calm` (до 3 строк в блоке, без подписей) / `full` | «настроить главную» |
| `hiddenBlocks` + порядок (`useOrder`) | состав и порядок блоков главной, DnD мышью | «настроить главную» |

Правила: новые настройки добавлять в `DEFAULTS` и, если это визуал, — в `apply()`; в UI использовать `usePrefs()` (подписка на изменения) и `prefs.set(patch)`. Кнопка «сбросить вид» → `prefs.reset()`.

## Платформа и клавиши
Подписи горячих клавиш берутся из `kb()/kbAlt()/kbShiftEnter` (`src/lib/api.js`): на macOS ⌘/⌥/⇧, на Windows и Linux — `Ctrl+`/`Alt+`/`Shift+`. Обработчики и так слушают `metaKey || ctrlKey`; менять нужно только подписи. Не хардкодить символ ⌘ в JSX.

## Приоритет задач
`PriorityDot` (`ui.jsx`) — точка + всплывающее меню через портал в `body` (строки лежат внутри `.swipe` с `overflow:hidden`, обычный absolute-попап там обрезался). Сортировка внутри групп задач — `prefs.tasksSort` (`priority | due | new`), переключатель над списком.

## Reference page pass · 2026

The current visual target is the supplied `джарвис · сегодня.html` reference. The shared CSS keeps the same tokens across every route:

- light `#e9ecf3`, dark `#0f1530` background (surface-1), cards `#151c3d` (surface-2) / `#1c2550` (surface-3);
- 232px dark-navy sidebar, 30px radius, 16px outer inset;
- active navigation item in the accent colour (default — настройка «тема и цвет»);
- 12-column bento utilities with 16px gaps and no content max-width;
- 28–30px cards, 26px padding, thin 1px border, restrained shadows;
- hero — lime gradient `--lime`; brand accent — `--accent` (в настройках);
- Inter Tight-style display hierarchy and tabular numerals for data labels;
- reference easing `cubic-bezier(.16,1,.3,1)` and reduced-motion fallbacks;
- empty states use `Empty` and a chat chip rather than a dead blank panel; a widget with no data is compact and honest.

## Навигация и пояснения (2026)
- Сайдбар сгруппирован: **план** (сегодня/задачи/календарь), **деньги** (финансы/заказы), **люди**, **джарвис** (мозг/память/настройки). Пустой дыры под логотипом нет — меню начинается сразу под ним, помодоро и статус прижаты к низу.
- Помодоро живёт **только в сайдбаре** (и в шапке на телефоне, когда активен). На странице заказов он не дублируется.
- Цвет вкладки (`.PageAccent`) больше не кнопка в шапке — выбор в «Настройки → тема и цвет». `pageAccents` и `usePageAccent` работают как раньше.
- Длинные пояснения в разделах прячем в тултип (`Section tip=…`), а не в текст под заголовком.

Routes and components use the same primitives from `src/index.css` and `components/ui.jsx`; page logic, API calls, hooks, storage and tests remain separate from the visual layer.
