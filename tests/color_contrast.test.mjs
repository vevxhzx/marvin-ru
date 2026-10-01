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
