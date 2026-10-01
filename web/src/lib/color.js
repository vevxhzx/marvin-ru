/* Цветовые утилиты: чистые функции без DOM и без зависимостей — их же гоняет
   node --test (tests/color_contrast.test.mjs). Сюда переехали rgbOf/lumOf/mixHex из prefs.js,
   туда же добавлен автоподбор текста с гарантией WCAG AA (≥ 4.5:1). */

export const rgbOf = (hex) => {
  const s = String(hex || '').replace('#', '')
  const h = s.length === 3 ? s.split('').map((c) => c + c).join('') : s.padEnd(6, '0').slice(0, 6)
  const n = parseInt(h, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export const lumOf = (hex) => {
  const [r, g, b] = rgbOf(hex).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export const mixHex = (from, to, k) => '#' + rgbOf(from).map((v, i) => Math.round(v + (rgbOf(to)[i] - v) * k).toString(16).padStart(2, '0')).join('')

/** WCAG: отношение яркостей (L1+0.05)/(L2+0.05); максимум 21:1, минимум 1:1. */
export function contrast(hexA, hexB) {
  const a = lumOf(hexA), b = lumOf(hexB)
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

export const INK_DARK = '#101114'
export const INK_LIGHT = '#ffffff'

/** Цвет текста поверх фона: берём тот из двух кандидатов, что даёт больший контраст. */
export function pickInk(bg) {
  return contrast(bg, INK_DARK) >= contrast(bg, INK_LIGHT) ? INK_DARK : INK_LIGHT
}

/** Гарантия контраста ≥ target (по умолчанию 4.5:1 — WCAG AA).
    В «мёртвой полосе» яркости (~0.18–0.20) ни белый, ни тёмный текст не дотягивает до 4.5:1 —
    тогда слегка подправляем сам фон в сторону выбранного текста (максимум на 60% смешивания),
    пока контраст не наберётся. Если и этого мало — возвращаем как есть (лучшее из двух). */
export function fitAccentInk(bg, target = 4.5) {
  if (!/^#[0-9a-f]{6}$/i.test(String(bg))) return { bg, ink: pickInk(String(bg)) }
  const ink = pickInk(bg)
  if (contrast(bg, ink) >= target) return { bg, ink }
  const toward = ink === INK_LIGHT ? '#000000' : '#ffffff' // белый текст → фон затемняем, тёмный → осветляем
  for (let k = 0.02; k <= 0.6; k += 0.02) {
    const c = mixHex(bg, toward, k)
    if (contrast(c, ink) >= target) return { bg: c, ink }
  }
  return { bg, ink }
}

/* Акцентная палитра настроек: ровно 10 цветов, новых не заводим.
   Синий — дефолтный акцент приложения (DEFAULTS.accentHex), красный/янтарь/лайм — токены
   из web/DESIGN.md (--red/--amber/--lime), остальные — уже существующие в приложении hex.
   Выбор меняет ТОЛЬКО --accent: смысловые цвета статусов (--pos/--neg/--warn/--ai)
   от выбора не зависят и остаются как в DESIGN.md. */
export const ACCENT_PALETTE = [
  { id: 'blue', name: 'синий', hex: '#0a3cff' },
  { id: 'indigo', name: 'индиго', hex: '#5b5bf0' },
  { id: 'violet', name: 'фиолетовый', hex: '#8a5cff' },
  { id: 'rose', name: 'розовый', hex: '#ff4d8d' },
  { id: 'red', name: 'красный', hex: '#ff5b7a' },
  { id: 'orange', name: 'оранжевый', hex: '#ff7a1a' },
  { id: 'amber', name: 'янтарь', hex: '#f5b400' },
  { id: 'lime', name: 'лайм', hex: '#c6f24a' },
  { id: 'green', name: 'зелёный', hex: '#19b34a' },
  { id: 'teal', name: 'бирюза', hex: '#12b5a5' },
]
