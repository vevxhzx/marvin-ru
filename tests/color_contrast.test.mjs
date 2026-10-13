// ЧАСТЬ 1В — контраст акцентных цветов (настройки → тема и цвет).
// Чистые функции из web/src/lib/color.js: яркость WCAG, автоподбор текста, палитра ≤10.
// Запуск: npm test  →  node --test tests/server_api.test.mjs tests/color_contrast.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  lumOf, contrast, pickInk, fitAccentInk, normHex, ACCENT_PALETTE, INK_DARK, INK_LIGHT,
} from '../web/src/lib/color.js'

test('яркость: белый = 1, чёрный ≈ 0', () => {
  assert.ok(Math.abs(lumOf('#ffffff') - 1) < 1e-6)
  assert.ok(lumOf('#000000') < 1e-6)
})

test('контраст: белый на чёрном = 21:1; #767676 на белом — классические ~4.5:1', () => {
  assert.ok(Math.abs(contrast('#ffffff', '#000000') - 21) < 0.1)
  const r = contrast('#767676', '#ffffff')
  assert.ok(r >= 4.5 && r < 4.6, `got ${r}`)
})

test('палитра: не больше 10 цветов, у каждого hex и уникальное название', () => {
  assert.ok(ACCENT_PALETTE.length <= 10, `palette size ${ACCENT_PALETTE.length}`)
  const names = new Set(ACCENT_PALETTE.map((c) => c.name))
  assert.equal(names.size, ACCENT_PALETTE.length)
  for (const c of ACCENT_PALETTE) assert.match(c.hex, /^#[0-9a-f]{6}$/i, `${c.id}: ${c.hex}`)
})

test('каждый цвет палитры: текст поверх него ≥ 4.5:1 (WCAG AA)', () => {
  for (const c of ACCENT_PALETTE) {
    const { bg, ink } = fitAccentInk(c.hex)
    assert.ok(contrast(bg, ink) >= 4.5, `${c.name} ${c.hex} ink=${ink}: ${contrast(bg, ink).toFixed(2)}`)
  }
})

test('автоподбор: светлый фон → тёмный текст, тёмный фон → белый', () => {
  assert.equal(pickInk('#ffffff'), INK_DARK)
  assert.equal(pickInk('#000000'), INK_LIGHT)
})

test('мёртвая полоса яркости (~0.18–0.20): fitAccentInk подправляет фон до ≥ 4.5:1', () => {
  // #7a7a7a: белый текст даёт ≈4.29, тёмный ≈4.40 — оба ниже AA, нужна подгонка фона
  const before = contrast('#7a7a7a', pickInk('#7a7a7a'))
  assert.ok(before < 4.5, `sanity: expected failing color, got ${before}`)
  const { bg, ink } = fitAccentInk('#7a7a7a')
  assert.notEqual(bg, '#7a7a7a')
  assert.ok(contrast(bg, ink) >= 4.5, `${bg}/${ink}: ${contrast(bg, ink).toFixed(2)}`)
})

test('достаточный контраст — фон не меняется', () => {
  for (const hex of ['#000000', '#ffffff', '#0a3cff', '#f5b400', '#c6f24a']) {
    const { bg, ink } = fitAccentInk(hex)
    assert.equal(bg, hex, `${hex} should stay untouched (ink=${ink})`)
    assert.ok(contrast(bg, ink) >= 4.5)
  }
})

test('normHex: свой цвет из настроек — строгий #rrggbb или null', () => {
  assert.equal(normHex('#0a3cff'), '#0a3cff')
  assert.equal(normHex('#ABC'), '#aabbcc')
  assert.equal(normHex('abc'), '#aabbcc')
  assert.equal(normHex('#AbC123'), '#abc123')
  assert.equal(normHex('red'), null)
  assert.equal(normHex('#12345'), null)
  assert.equal(normHex('#gggggg'), null)
  assert.equal(normHex(''), null)
  assert.equal(normHex(null), null)
  assert.equal(normHex('var(--accent)'), null)
})

test('свой цвет: текст поверх любого валидного hex считается той же математикой', () => {
  for (const hex of ['#123456', '#abcdef', '#fedcba', '#808080']) {
    const norm = normHex(hex)
    assert.equal(norm, hex.toLowerCase())
    const { bg, ink } = fitAccentInk(norm)
    assert.ok(contrast(bg, ink) >= 4.5, `${hex}: ${contrast(bg, ink).toFixed(2)}`)
  }
})

// ЧАСТЬ 2 — a11y-ворота: статический скан web/src (без сборки и браузера).
// Проверки: img с alt, иконки-кнопки (button и Pressable) с доступным именем,
// кликабельные не-<button> (div и span) с ролью/табиндексом/клавиатурой.
// Отдельно — мобильная копия web/src/mapp: там интерактивом может быть только
// <button type="button">, и у каждого экрана, который тянет данные, есть
// загрузка/пусто/ошибка (см. tests в конце файла).
// Pressable-миграции — только тривиальные (см. отчёт W10); строки-раскрытия с
// вложенными кнопками — редизайн, не трогаем.
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join, relative } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const WEB_SRC = join(ROOT, 'web', 'src')
const MAPP_SRC = join(WEB_SRC, 'mapp')

function filesUnder(dir) {
  const out = []
  const walk = (d) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      if (e.name === 'node_modules' || e.name === 'site') continue
      const p = join(d, e.name)
      if (e.isDirectory()) walk(p)
      else if (/\.(jsx|js|tsx|ts)$/.test(e.name)) out.push(p)
    }
  }
  walk(dir)
  return out
}

const webFiles = () => filesUnder(WEB_SRC)
const mappFiles = () => filesUnder(MAPP_SRC)

// Тег с учётом `{...}` в атрибутах (стрелки `=>` и `style={{...}}` содержат `>`).
const TAG_ATTRS = '((?:\\{[^}]*\\}|[^>])*)'
const tagRe = (name) => new RegExp(`<${name}\\b${TAG_ATTRS}>`, 'gs')

const relOf = (f) => relative(ROOT, f).replace(/\\/g, '/')
/* Комментарии вырезаем, разметка в комментарии («это отдельная
   <button>») разметкой не является. Проход с учётом строк: иначе `accept="image/*"`
   съел бы полфайла. */
function stripComments(src) {
  let out = ''
  let i = 0
  let quote = ''
  while (i < src.length) {
    const c = src[i]
    if (quote) {
      out += c
      if (c === '\\') { out += src[i + 1] || ''; i += 2; continue }
      if (c === quote) quote = ''
      i++
      continue
    }
    if (c === '"' || c === "'" || c === '`') { quote = c; out += c; i++; continue }
    if (c === '/' && (src[i + 1] === '*' || src[i + 1] === '/')) {
      const block = src[i + 1] === '*'
      const stop = block ? src.indexOf('*/', i + 2) : src.indexOf('\n', i + 2)
      const end = stop < 0 ? src.length : (block ? stop + 2 : stop)
      out += ' '.repeat(end - i)
      i = end
      continue
    }
    out += c
    i++
  }
  return out
}
const srcOf = (f) => stripComments(readFileSync(f, 'utf8'))

/* Доступное имя: aria-label / aria-labelledby / title. Любое выражение
   (`aria-label={t('…')}`) именем считаем, а вот пустая строка — нет: иначе
   `aria-label=""` проскакивал бы как «подпись есть». */
const hasName = (attrs) => {
  if (/\baria-labelledby=|\btitle=/.test(attrs)) return true
  if (!/\baria-label\s*=/.test(attrs)) return false
  const lit = attrs.match(/\baria-label\s*=\s*("[^"]*"|\{'[^']*'\}|\{"[^"]*"\})/)
  if (!lit) return true
  return lit[1].replace(/[{}\s"']/g, '').length > 0
}

test('a11y: каждый <img> имеет alt', () => {
  const bad = []
  for (const f of webFiles()) {
    const t = srcOf(f)
    for (const m of t.matchAll(tagRe('img'))) {
      if (!/\balt=/.test(m[0])) bad.push(`${relative(ROOT, f)}: ${m[0].slice(0, 90)}`)
    }
  }
  assert.deepEqual(bad, [], `img без alt:\n${bad.join('\n')}`)
})

test('a11y: кнопка только с иконкой имеет доступное имя', () => {
  // data-tip — визуальный тултип, скринридер его не читает: засчитываем только
  // aria-label / aria-labelledby / title либо видимый текст.
  const bad = []
  for (const f of webFiles()) {
    const t = srcOf(f)
    for (const m of t.matchAll(/<button\b((?:\{[^}]*\}|[^>])*)>([\s\S]*?)<\/button>/g)) {
      const [, attrs, inner] = m
      if (hasName(attrs)) continue
      const text = inner.replace(/<[^>]+>/g, '')
      if (/[A-Za-z\u0400-\u04FF]/.test(text)) continue
      const line = t.slice(0, m.index).split('\n').length
      bad.push(`${relative(ROOT, f)}:${line}: ${(attrs.trim().slice(0, 60))}`)
    }
  }
  assert.deepEqual(bad, [], `кнопки-иконки без имени:\n${bad.join('\n')}`)
})

test('a11y: иконка-Pressable тоже имеет доступное имя', () => {
  // Pressable рендерит настоящий <button> — правило то же. Сейчас нарушений
  // ноль, проверка держит состояние (раньше эта дыра проходила молча).
  const bad = []
  for (const f of webFiles()) {
    const t = srcOf(f)
    for (const m of t.matchAll(/<Pressable\b((?:\{[^}]*\}|[^>])*)>([\s\S]*?)<\/Pressable>/g)) {
      const [, attrs, inner] = m
      if (hasName(attrs)) continue
      if (/[A-Za-z\u0400-\u04FF]/.test(inner.replace(/<[^>]+>/g, ''))) continue
      const line = t.slice(0, m.index).split('\n').length
      bad.push(`${relative(ROOT, f)}:${line}: ${attrs.trim().slice(0, 60)}`)
    }
  }
  assert.deepEqual(bad, [], `Pressable-иконки без имени:\n${bad.join('\n')}`)
})

test('a11y: div с onClick — роль, фокус и клавиатура', () => {
  // Чистые «глушилки» всплытия (внутри — настоящие кнопки) — не интерактив, пропускаем.
  const isGuard = (tag) => /onClick=\{\s*\(\s*e\s*\)\s*=>\s*e\.stopPropagation\(\)\s*\}/.test(tag)
  // Известные строки-раскрытия с вложенными кнопками/полями: в role="button" их
  // заворачивать нельзя (вложенный интерактив), нужен редизайн — список здесь,
  // чтобы ворота ловили только НОВЫЕ нарушения. Убранные из кода — удалить и отсюда
  // (проверка ниже упадёт с подсказкой, если маркер исчез).
  const KNOWN = [
    { file: 'web/src/pages/Memory.jsx', marker: '!edit && setOpen', why: 'FactRow: раскрытие + вложенные поле/кнопки' },
    { file: 'web/src/pages/Memory.jsx', marker: 'onClick={onToggle}', why: 'Entry: раскрытие + вложенные Link/кнопка' },
  ]
  const seen = new Set()
  const bad = []
  for (const f of webFiles()) {
    const rel = relative(ROOT, f).replace(/\\/g, '/')
    const t = srcOf(f)
    for (const m of t.matchAll(tagRe('div'))) {
      const tag = m[0]
      if (!/\sonClick\s*=/.test(tag) || isGuard(tag)) continue
      const known = KNOWN.find((k) => rel === k.file && tag.includes(k.marker))
      if (known) { seen.add(`${known.file}::${known.marker}`); continue }
      const line = t.slice(0, m.index).split('\n').length
      const missing = [
        /\brole=/.test(tag) ? null : 'role',
        /\btabIndex/i.test(tag) ? null : 'tabIndex',
        /onKeyDown|onKeyPress|onKeyUp/.test(tag) ? null : 'keyboard',
      ].filter(Boolean)
      if (missing.length) bad.push(`${rel}:${line}: нет ${missing.join('/')} :: ${tag.slice(0, 110).replace(/\s+/g, ' ')}`)
    }
  }
  for (const k of KNOWN) {
    assert.ok(seen.has(`${k.file}::${k.marker}`), `a11y-allowlist протух: ${k.file} :: ${k.marker} — строка исправлена? уберите запись из KNOWN (${k.why})`)
  }
  assert.deepEqual(bad, [], `div-onClick без a11y:\n${bad.join('\n')}`)
})

// ЧАСТЬ 3 — мобильная копия (web/src/mapp). Здесь правила строже десктопных:
// интерактивом может быть только <button type="button"> (DESIGN.md), а экран,
// который тянет данные, обязан показать загрузку, пустоту и ошибку.


test('a11y: <span onClick> — роль, фокус и клавиатура (та же логика, что для div)', () => {
  // Раньше скан брал только <div onClick>, и кликабельные сегменты-подписи на
  // <span> проходили незамеченным: их не видно с клавиатуры вообще.
  const isGuard = (tag) => /onClick=\{\s*\(\s*e\s*\)\s*=>\s*e\.stopPropagation\(\)\s*\}/.test(tag)
  // Известный долг в чужом файле: переключатели сегментов в настройках темы.
  // Помечаем soft: проверка протухшего не делает — файл правит владелец pages/*,
  // и его правка не должна ронять эту ветку. Когда переделаете на <button> —
  // удалите запись.
  const KNOWN_SOFT = [
    { file: 'web/src/pages/Settings.jsx', marker: `setMode('auto')`, why: 'сегмент темы (auto) — вне зоны этой правки' },
    { file: 'web/src/pages/Settings.jsx', marker: `setMode('light')`, why: 'сегмент темы (light) — вне зоны этой правки' },
    { file: 'web/src/pages/Settings.jsx', marker: `setMode('dark')`, why: 'сегмент темы (dark) — вне зоны этой правки' },
    { file: 'web/src/pages/Settings.jsx', marker: 'set({ tint: id })', why: 'сегмент оттенка — вне зоны этой правки' },
    { file: 'web/src/pages/Settings.jsx', marker: 'set({ font: id })', why: 'сегмент шрифта — вне зоны этой правки' },
    { file: 'web/src/pages/Settings.jsx', marker: 'set({ radius: id })', why: 'сегмент скруглений — вне зоны этой правки' },
  ]
  const bad = []
  for (const f of webFiles()) {
    const rel = relOf(f)
    const t = srcOf(f)
    for (const m of t.matchAll(tagRe('span'))) {
      const tag = m[0]
      if (!/\sonClick\s*=/.test(tag) || isGuard(tag)) continue
      if (KNOWN_SOFT.some((k) => rel === k.file && tag.includes(k.marker))) continue
      const line = t.slice(0, m.index).split('\n').length
      const missing = [
        /\brole=/.test(tag) ? null : 'role',
        /\btabIndex/i.test(tag) ? null : 'tabIndex',
        /onKeyDown|onKeyPress|onKeyUp/.test(tag) ? null : 'keyboard',
      ].filter(Boolean)
      if (missing.length) bad.push(`${rel}:${line}: нет ${missing.join('/')} :: ${tag.slice(0, 110).replace(/\s+/g, ' ')}`)
    }
  }
  assert.deepEqual(bad, [], `span-onClick без a11y:\n${bad.join('\n')}`)
})

test('a11y: в мобильной копии интерактив — только <button> (div/span-onClick запрещены)', () => {
  // Кнопка внутри role="button" невалидна, поэтому в mapp клик — всегда
  // <button type="button">, а «глушилки» всплытия — единственное исключение.
  const isGuard = (tag) => /onClick=\{\s*\(\s*e\s*\)\s*=>\s*e\.stopPropagation\(\)\s*\}/.test(tag)
  const bad = []
  for (const f of mappFiles()) {
    const rel = relOf(f)
    const t = srcOf(f)
    for (const tag of ['div', 'span']) {
      for (const m of t.matchAll(tagRe(tag))) {
        const el = m[0]
        if (!/\sonClick\s*=/.test(el) || isGuard(el)) continue
        const line = t.slice(0, m.index).split('\n').length
        bad.push(`${rel}:${line}: <${tag} onClick> — нужен <button type="button"> :: ${el.slice(0, 100).replace(/\s+/g, ' ')}`)
      }
    }
  }
  assert.deepEqual(bad, [], `интерактив не на <button> в mapp:\n${bad.join('\n')}`)
})

test('a11y: в мобильной копии у каждой кнопки указан type', () => {
  // Без type кнопка внутри <form> отправляет форму по Enter/тапу — «случайные»
  // сохранения и закрытия. Десктопные файлы на это не смотрим: правило для mapp.
  const bad = []
  for (const f of mappFiles()) {
    const rel = relOf(f)
    const t = srcOf(f)
    for (const m of t.matchAll(tagRe('button'))) {
      if (/\btype=/.test(m[0])) continue
      const line = t.slice(0, m.index).split('\n').length
      bad.push(`${rel}:${line}: ${m[0].replace(/\s+/g, ' ').slice(0, 80)}`)
    }
  }
  assert.deepEqual(bad, [], `кнопки без type в mapp:\n${bad.join('\n')}`)
})

// ---------- состояния экранов мобильной копии ----------

/* Экран считается «тянущим данные», если зовёт api.*. Правило не привязано к
   именам компонентов-обёрток: годятся и десктопные Empty/ErrorState/Skeleton,
   и мобильные MEmpty/MError/MLoading/MSkeleton/MListSkeleton. */
const mappScreens = () => filesUnder(join(MAPP_SRC, 'screens')).filter((f) => /\.jsx$/.test(f))
const USES = {
  error: /<MLoadError\b|<MError\b|<ErrorState\b/,
  empty: /<MEmpty\b|<Empty\b/,
  loading: /<MLoading\b|<MSkeleton\b|<MListSkeleton\b|<Skeleton\b|<ListSkeleton\b/,
}
const RETRY = /\bonRetry=/

test('состояния: экран, который грузит данные, показывает ошибку с повтором', () => {
  const bad = []
  for (const f of mappScreens()) {
    const t = srcOf(f)
    if (!/\bapi\./.test(t)) continue                       // данных не тянет — состояния не нужны
    const rel = relOf(f)
    if (!USES.error.test(t)) { bad.push(`${rel}: нет ErrorState/MError`); continue }
    if (!RETRY.test(t)) bad.push(`${rel}: ошибка показана, но повтор не отдаётся (нет onRetry=)`)
  }
  assert.deepEqual(bad, [], `экраны без состояния ошибки:\n${bad.join('\n')}`)
})

test('состояния: экран, который грузит данные, показывает загрузку', () => {
  const bad = []
  for (const f of mappScreens()) {
    const t = srcOf(f)
    if (!/\bapi\./.test(t)) continue
    const rel = relOf(f)
    if (!USES.loading.test(t)) bad.push(`${rel}: нет скелетона (Skeleton/ListSkeleton/MLoading)`)
  }
  assert.deepEqual(bad, [], `экраны без состояния загрузки:\n${bad.join('\n')}`)
})

test('состояния: экран со списком данных показывает пустоту с объяснением', () => {
  // Экраны без своих списков (меню «ещё», чат) перечислены явно: пустота там
  // выражена приветствием, а не блоком Empty. Если экран начнёт рисовать список —
  // проверка сама попросит убрать его из списка (см. assert ниже).
  const NO_LIST = {
    'web/src/mapp/screens/More.jsx': 'меню-хаб: своих списков нет, плитки — навигация',
    'web/src/mapp/screens/Chat.jsx': 'чат: пустота — приветствие (chat.hello), как в десктопном Chat',
  }
  const bad = []
  for (const f of mappScreens()) {
    const t = srcOf(f)
    if (!/\bapi\./.test(t)) continue
    const rel = relOf(f)
    if (USES.empty.test(t)) {
      if (NO_LIST[rel]) bad.push(`${rel}: в списке исключений, но Empty уже есть — уберите запись`)
      continue
    }
    if (!NO_LIST[rel]) bad.push(`${rel}: тянет данные, но нигде не показывает пустоту (Empty)`)
  }
  assert.deepEqual(bad, [], `экраны без пустого состояния:\n${bad.join('\n')}`)
})

test('состояния: в мобильной копии нет голых заглушек «загружаю…»/«не загрузилось»', () => {
  // Старая мода: текст вместо состояния — пользователь видит пустой экран без
  // объяснения. Ищем именно «голый» текстовый узел `>{t('m.loading')}<`; те же
  // ключи внутри примитивов (title=`t('m.load_err')`, sr-only) — законные.
  const naked = />\s*\{t\('(m\.loading|m\.load_err|m\.list_empty|m\.empty_sub|m\.empty_brain|m\.empty_orders)'\)\}\s*</g
  const bad = []
  for (const f of mappFiles()) {
    const t = srcOf(f)
    for (const m of t.matchAll(naked)) {
      const line = t.slice(0, m.index).split('\n').length
      bad.push(`${relOf(f)}:${line}: ${m[0].replace(/\s+/g, ' ')} — вместо примитива состояния`)
    }
  }
  assert.deepEqual(bad, [], `голые заглушки состояний в mapp:\n${bad.join('\n')}`)
})

test('состояния: mapp переиспользует десктопные примитивы, а не дублирует их', () => {
  // Правило заказа: логику Empty/ErrorState/Skeleton не копируем — оборачиваем.
  const ui = srcOf(join(MAPP_SRC, 'ui.jsx'))
  assert.match(ui, /from '\.\.\/components\/ui'/, 'mapp/ui.jsx должен импортировать примитивы из components/ui')
  for (const name of ['Empty', 'ErrorState', 'Skeleton', 'ListSkeleton']) {
    assert.ok(new RegExp(`\\b${name}\\b`).test(ui), `mapp/ui.jsx должен использовать ${name}`)
  }
  for (const f of mappFiles()) {
    const t = srcOf(f)
    for (const name of ['Empty', 'ErrorState', 'Skeleton', 'ListSkeleton']) {
      const decl = new RegExp(`(function|const)\\s+${name}\\b|export function ${name}\\b`)
      if (decl.test(t)) assert.fail(`${relOf(f)}: свой компонент ${name} — бери из components/ui.jsx`)
    }
  }
})
