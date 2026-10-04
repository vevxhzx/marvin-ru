// ЧАСТЬ 1В — контраст акцентных цветов (настройки → тема и цвет).
// Чистые функции из web/src/lib/color.js: яркость WCAG, автоподбор текста, палитра ≤10.
// Запуск: npm test  →  node --test tests/server_api.test.mjs tests/color_contrast.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  lumOf, contrast, pickInk, fitAccentInk, ACCENT_PALETTE, INK_DARK, INK_LIGHT,
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

// ЧАСТЬ 2 — a11y-ворота: статический скан web/src (без сборки и браузера).
// Три проверки: img с alt, иконки-кнопки с доступным именем, div-onClick с
// ролью/табиндексом/клавиатурой. Pressable-миграции — только тривиальные
// (см. отчёт W10); строки-раскрытия с вложенными кнопками — редизайн, не трогаем.
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join, relative } from 'node:path'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const WEB_SRC = join(ROOT, 'web', 'src')

function webFiles() {
  const out = []
  const walk = (dir) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      if (e.name === 'node_modules' || e.name === 'site') continue
      const p = join(dir, e.name)
      if (e.isDirectory()) walk(p)
      else if (/\.(jsx|js|tsx|ts)$/.test(e.name)) out.push(p)
    }
  }
  walk(WEB_SRC)
  return out
}

// Тег с учётом `{...}` в атрибутах (стрелки `=>` и `style={{...}}` содержат `>`).
const TAG_ATTRS = '((?:\\{[^}]*\\}|[^>])*)'
const tagRe = (name) => new RegExp(`<${name}\\b${TAG_ATTRS}>`, 'gs')

test('a11y: каждый <img> имеет alt', () => {
  const bad = []
  for (const f of webFiles()) {
    const t = readFileSync(f, 'utf8')
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
    const t = readFileSync(f, 'utf8')
    for (const m of t.matchAll(/<button\b((?:\{[^}]*\}|[^>])*)>([\s\S]*?)<\/button>/g)) {
      const [, attrs, inner] = m
      if (/aria-label|aria-labelledby|\btitle=/.test(attrs)) continue
      const text = inner.replace(/<[^>]+>/g, '')
      if (/[A-Za-z\u0400-\u04FF]/.test(text)) continue
      const line = t.slice(0, m.index).split('\n').length
      bad.push(`${relative(ROOT, f)}:${line}: ${(attrs.trim().slice(0, 60))}`)
    }
  }
  assert.deepEqual(bad, [], `кнопки-иконки без имени:\n${bad.join('\n')}`)
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
    const t = readFileSync(f, 'utf8')
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
