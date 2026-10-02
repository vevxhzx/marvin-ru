/* lib/motion.js — движение как основа оболочки.

   Один подход на всё приложение: Web Animations API. Пружины считаются физикой
   (stiffness/damping/mass) и превращаются в `linear(...)`-easing — сама анимация идёт
   вне главного потока, а выглядит как настоящая пружина. rAF остаётся только там,
   где значение нужно читать и прерывать на ходу (морфинг пилюли, счёт чисел, жесты).

   Никаких зависимостей. Уважает `prefers-reduced-motion` и настройку «меньше
   движения» (классы .no-motion / .no-anim на <html>): тогда конечное состояние
   ставится сразу, анимация не запускается.

   Анимируем только transform/opacity (плюс width/height у пилюли и шторки):
   цвет, тень и фон трогать нельзя — это paint на каждом кадре.
*/

import { useEffect, useRef, useState } from 'react'

const hasWin = typeof window !== 'undefined' && typeof document !== 'undefined'
const mqReduce = hasWin && typeof window.matchMedia === 'function'
  ? window.matchMedia('(prefers-reduced-motion: reduce)')
  : null

/* Классы, которыми настройки гасят движение (prefs.apply вешает .no-motion на <html>) */
const QUIET = ['no-motion', 'no-anim']

/** Движение выключено? Тогда всё, что ниже, ставит конечное состояние сразу. */
export function motionOff() {
  if (!hasWin) return false
  const de = document.documentElement
  for (let i = 0; i < QUIET.length; i++) if (de.classList.contains(QUIET[i])) return true
  return !!(mqReduce && mqReduce.matches)
}

/* Кривые из index.css — те же значения, чтобы не было двух наборов */
export const EASE_OUT = 'cubic-bezier(.2,.8,.2,1)'
export const EASE_IO = 'cubic-bezier(.65,0,.35,1)'
export const EASE_SPRING = 'cubic-bezier(.34,1.56,.64,1)'

/** Пружина по умолчанию: жёсткость 340, демпфер 32 → ζ≈0.87 (почти критическое гашение). */
export const SPRING = { stiffness: 340, damping: 32, mass: 1 }

const clamp = (v, a, b) => (v < a ? a : v > b ? b : v)
const round3 = (v) => Math.round(v * 1000) / 1000
const now = () => (hasWin && performance ? performance.now() : 0)

/* ---------- поддержка linear()-easing ---------- */
let _linear = null
export function linearEasingOk() {
  if (_linear !== null) return _linear
  try { _linear = hasWin && typeof CSS !== 'undefined' && CSS.supports('transition-timing-function', 'linear(0, 0.5 50%, 1)') }
  catch { _linear = false }
  return _linear
}

/* ---------- пружина: физика → (duration, easing) ---------- */
/* Прогресс 0→1 считаем методом Эйлера (dt = 1/240) и прореживаем до ~25 стопов:
   easing получается точной формой пружины, а не «похожей на неё» кривой Безье.
   Если linear() не поддержан — отдаём ближайшую кривую из CSS (пружина с перелётом). */
export function springCurve({ stiffness = SPRING.stiffness, damping = SPRING.damping, mass = SPRING.mass, velocity = 0, stops = 25 } = {}) {
  const dt = 1 / 240
  const restD = 0.01, restV = 0.12
  const pts = [0]
  let x = 0, v = velocity, t = 0
  while (t < 1.6) {
    const a = (-stiffness * (x - 1) - damping * v) / mass
    v += a * dt
    x += v * dt
    t += dt
    pts.push(x)
    if (Math.abs(1 - x) < restD && Math.abs(v) < restV) break
  }
  const duration = Math.round(clamp(t, 0.12, 1.2) * 1000)
  if (!linearEasingOk()) return { duration, easing: EASE_SPRING, linear: false }
  const stride = Math.max(1, Math.ceil((pts.length - 1) / stops))
  const out = []
  for (let i = 0; i < pts.length; i += stride) out.push(round3(clamp(pts[i], -0.4, 1.8)))
  /* последняя точка — ровно цель: иначе easing заканчивается чуть «не доехав»
     (остаток после остановки интегратора может быть и выше единицы) */
  const tail = Math.abs(pts[pts.length - 1] - 1) <= restD ? 1 : round3(pts[pts.length - 1])
  if (out[out.length - 1] !== tail) out.push(tail)
  return { duration, easing: `linear(${out.join(',')})`, linear: true }
}

/* ---------- низкий уровень ---------- */
const noop = { cancel() {}, done: Promise.resolve(), anim: null, value: () => 0 }

/** Перенести кадр в инлайн-стиль — так выглядит «мгновенный переход» при motionOff(). */
export function commit(el, frame) {
  if (!el || !frame) return
  for (const k in frame) {
    const v = frame[k]
    if (v == null) continue
    const name = k.startsWith('--') ? k : k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)
    try { el.style.setProperty(name, typeof v === 'number' ? String(v) : String(v)) } catch {}
  }
}

/** Прямая обёртка над element.animate (нужен сам объект Animation). */
export function animate(el, frames, opts = {}) {
  if (!el || typeof el.animate !== 'function') return null
  if (motionOff()) { commit(el, frames[frames.length - 1]); return null }
  try { return el.animate(frames, opts) } catch { return null }
}

/** Анимация элемента с запасным путём: без движения / без WAAPI — сразу последний кадр. */
export function tween(el, frames, opts = {}) {
  if (!el || !frames || !frames.length) return noop
  const anim = animate(el, frames, opts)
  if (!anim) { commit(el, frames[frames.length - 1]); return noop }
  return {
    anim,
    cancel() { try { anim.cancel() } catch {} },
    done: anim.finished.catch(() => {}),
    value: () => 0,
  }
}

/* ---------- пружина ---------- */
/**
 * spring({ from, to, onUpdate, onComplete })      значение на каждый кадр (rAF, можно прервать)
 * spring({ el, prop, from, to, unit })            то же через WAAPI, кадры не нужны
 *
 * Ветка с элементом коммитит конечное значение в инлайн-стиль: после анимации элемент
 * остаётся в конечном состоянии и не «прыгает» обратно на auto/исходное значение.
 */
export function spring({
  from = 0, to = 1, unit = '', prop, el, delay = 0,
  stiffness, damping, mass, velocity = 0, onUpdate, onComplete,
} = {}) {
  const k = stiffness ?? SPRING.stiffness
  const c = damping ?? SPRING.damping
  const m = mass ?? SPRING.mass
  const finish = () => { try { onComplete?.(to) } catch {} }

  if (motionOff()) {
    if (onUpdate) { try { onUpdate(to, 1) } catch {} }
    if (el && prop) { try { el.style.setProperty(prop, `${to}${unit}`) } catch {} }
    finish()
    return noop
  }

  if (el && prop) {
    const curve = springCurve({ stiffness: k, damping: c, mass: m, velocity })
    let anim = null
    try {
      anim = el.animate(
        [{ [prop]: `${from}${unit}` }, { [prop]: `${to}${unit}` }],
        { duration: curve.duration, delay, easing: curve.easing, fill: 'backwards' },
      )
    } catch { anim = null }
    if (!anim) {
      if (onUpdate) { try { onUpdate(to, 1) } catch {} }
      try { el.style.setProperty(prop, `${to}${unit}`) } catch {}
      finish()
      return noop
    }
    const done = anim.finished.catch(() => {})
    done.then(() => {
      try { el.style.setProperty(prop, `${to}${unit}`) } catch {}
      try { anim.cancel() } catch {}
      finish()
    })
    return {
      cancel() { try { anim.cancel() } catch {} },
      done,
      anim,
      value: () => to,
    }
  }

  /* rAF-интегратор: значение надо читать и уметь прервать (пилюля, жест, число) */
  const h = 1 / 240
  let x = typeof from === 'number' ? from : 0
  let v = velocity
  let raf = 0
  let alive = true
  let last = 0
  let acc = -Math.max(0, delay)   // отрицательный остаток = «время ещё не пошло»
  let elapsed = 0
  let resolveDone
  const done = new Promise((res) => { resolveDone = res })

  const kick = () => { if (!raf && alive) raf = requestAnimationFrame(tick) }
  function tick(ts) {
    raf = 0
    if (!alive) return
    if (!last) { last = ts; kick(); return }
    acc += Math.min((ts - last) / 1000, 0.064)
    last = ts
    elapsed += 0.064
    if (acc >= 0) {
      while (acc >= h) {
        const a = (-k * (x - to) - c * v) / m
        v += a * h
        x += v * h
        acc -= h
      }
      const settled = (Math.abs(x - to) < 0.05 && Math.abs(v) < 0.4) || elapsed > 4
      if (settled) {
        alive = false
        try { onUpdate?.(to, 1) } catch {}
        resolveDone()
        finish()
        return
      }
      try { onUpdate?.(x, 0) } catch {}
    }
    kick()
  }
  kick()
  return {
    cancel() { if (!alive) return; alive = false; if (raf) cancelAnimationFrame(raf); raf = 0; resolveDone() },
    done,
    anim: null,
    value: () => x,
  }
}

/* ---------- появление ---------- */
/** fadeSlide: прозрачность + короткий сдвиг 8–12px. dir: 'up' | 'down' */
export function fadeSlide(el, { dy = 10, dx = 0, duration = 300, delay = 0, scale, dir = 'up' } = {}) {
  if (!el) return noop
  const shift = dir === 'down' ? -dy : dy
  const tail = scale ? ' scale(1)' : ''
  return tween(el, [
    { opacity: 0, transform: `translate3d(${dx}px, ${shift}px, 0)${scale ? ` scale(${scale})` : ''}` },
    { opacity: 1, transform: `translate3d(0px, 0px, 0)${tail}` },
  ], { duration, delay, easing: EASE_OUT, fill: 'backwards' })
}

/** Каскад по списку: шаг 40–60 мс между соседями. */
export function stagger(els, { step = 50, dy = 8, duration = 380, from = 0, max = 24 } = {}) {
  const list = [...els].slice(0, max)
  list.forEach((el, i) => fadeSlide(el, { dy, duration, delay: from + i * step }))
  return () => { for (const el of list) { try { el.getAnimations?.().forEach((a) => a.cancel()) } catch {} } }
}

/* ---------- числа ---------- */
/** Кривая докрута: expo-out. Одна на оба счётчика (элемент и значение в React). */
export const expoOut = (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p))

/**
 * rollTo({ from, to, duration, delay, onStart, onFrame, onDone }) — общий «докрут» шкалы.
 *
 * Значение нужно читать на каждом кадре, поэтому здесь rAF, а не WAAPI. Стартовое
 * значение отдаётся сразу (иначе на один кадр светилась бы старая цифра), дальше —
 * по expo-out. Движение выключено или шаг нулевой → конечное значение сразу.
 * Возвращает то же, что spring/countUp: { cancel, done, anim, value }.
 */
export function rollTo({ from = 0, to = 0, duration = 1400, delay = 0, onStart, onFrame, onDone } = {}) {
  if (motionOff() || duration <= 0 || from === to) {
    try { onFrame?.(to, 1); onDone?.(to) } catch {}
    return noop
  }
  let raf = 0
  const t0 = now() + Math.max(0, delay)
  try { onStart?.(from, to); onFrame?.(from, 0) } catch {}
  const tick = () => {
    const p = clamp((now() - t0) / duration, 0, 1)
    try { onFrame?.(p >= 1 ? to : from + (to - from) * expoOut(p), p) } catch {}
    if (p < 1) raf = requestAnimationFrame(tick)
    else { try { onDone?.(to) } catch {} }
  }
  raf = requestAnimationFrame(tick)
  return { cancel() { if (raf) cancelAnimationFrame(raf) }, done: Promise.resolve(), anim: null, value: () => to }
}

/** Число «докручивается» до значения; на элемент вешается .num — табличные цифры. */
export function countUp(el, { from = 0, to = 0, duration = 1400, delay = 0, format, tabular = true } = {}) {
  if (!el) return noop
  if (tabular) el.classList.add('num')
  return rollTo({
    from, to, duration, delay,
    onFrame: (v) => { el.textContent = format ? format(v) : String(Math.round(v)) },
  })
}

/**
 * useCountValue(to, { from, duration, delay, onStart, onDone }) — React-версия того же
 * докрута: значение в состоянии компонента, второй элемент массива — «докрутилось».
 *
 * Анимируется только смена to: `from` — либо число (всегда от него), либо функция от
 * предыдущего значения (как у счётчика, который катится от того, что уже показано).
 * onStart(begin, to) зовётся перед первым кадром, onDone(to) — в конце; оба есть у
 * CountUp, чтобы барабан чисел наезжал начиная с правильной строки.
 */
export function useCountValue(to, { from, duration = 1400, delay = 0, onStart, onDone } = {}) {
  const target = Number.isFinite(Number(to)) ? Number(to) : 0
  const [value, setValue] = useState(target)
  const [done, setDone] = useState(true)
  const was = useRef(target)
  /* точка старта и колбэки держим в ref: инлайновые стрелки не должны перезапускать докрут */
  const opts = useRef(null)
  opts.current = { from, onStart, onDone }

  useEffect(() => {
    const prev = was.current
    was.current = target
    const { from: f, onStart: start, onDone: fin } = opts.current
    const raw = typeof f === 'function' ? Number(f(prev)) : Number(f)
    const begin = Number.isFinite(raw) ? raw : 0
    const run = rollTo({
      from: begin, to: target, duration, delay,
      onStart: (a) => { setDone(false); try { start?.(a, target) } catch {} },
      onFrame: setValue,
      onDone: (v) => { setValue(v); setDone(true); try { fin?.(v) } catch {} },
    })
    return () => run.cancel()
  }, [target, duration, delay])

  return [value, done]
}

/* ---------- нажатие ---------- */
/**
 * press(el) — scale 0.97 под пальцем и пружинный возврат.
 * Здесь числовая пружина, а не WAAPI: нажатие прерывают (палец ушёл раньше), и тогда
 * надо стартовать с текущего значения — WAAPI такое не умеет, rAF-интегратор умеет.
 */
export function press(el, { scale = 0.97, downMs = 90, upStiffness = 380, upDamping = 30 } = {}) {
  if (!el) return () => {}
  let held = false
  let value = 1
  let anim = null
  let cur = null

  const apply = (v) => { try { el.style.transform = `scale(${v})` } catch {} }
  const stop = () => {
    if (cur) { cur.cancel(); cur = null }
    if (anim) { try { anim.cancel() } catch {}; anim = null }
  }
  const goTo = (target, duration) => {
    stop()
    if (motionOff()) { value = target; apply(target); return }
    if (target < 1) {
      value = target
      apply(target)
      anim = animate(el, [{ transform: `scale(${target})` }], { duration, easing: EASE_OUT, fill: 'forwards' })
      return
    }
    cur = spring({
      from: value, to: 1, stiffness: upStiffness, damping: upDamping,
      onUpdate: (v) => { value = v; apply(v) },
      onComplete: () => { value = 1; try { el.style.transform = '' } catch {} },
    })
  }
  const down = (e) => {
    if (e.button != null && e.button !== 0) return
    if (e.target?.closest?.('[data-no-press]')) return
    held = true
    goTo(scale, downMs)
  }
  const up = () => { if (!held) return; held = false; goTo(1) }
  el.addEventListener('pointerdown', down)
  el.addEventListener('pointerup', up)
  el.addEventListener('pointercancel', up)
  el.addEventListener('pointerleave', up)
  window.addEventListener('blur', up)
  return () => {
    el.removeEventListener('pointerdown', down)
    el.removeEventListener('pointerup', up)
    el.removeEventListener('pointercancel', up)
    el.removeEventListener('pointerleave', up)
    window.removeEventListener('blur', up)
    stop()
    try { el.style.transform = '' } catch {}
  }
}

/* ---------- переход между разделами ---------- */
/** Появление: сдвиг 8–12px + прозрачность. */
export function crossfadeIn(el, { shift = 10, duration = 280, delay = 0 } = {}) {
  if (!el) return noop
  return tween(el, [
    { opacity: 0, transform: `translate3d(0, ${shift}px, 0)` },
    { opacity: 1, transform: 'translate3d(0, 0, 0)' },
  ], { duration, delay, easing: EASE_OUT })
}

/** Уход: сдвиг в другую сторону + прозрачность. done — когда можно менять раздел. */
export function crossfadeOut(el, { shift = -6, duration = 130 } = {}, done) {
  if (!el) { try { done?.() } catch {} ; return noop }
  const h = tween(el, [
    { opacity: 1, transform: 'translate3d(0, 0, 0)' },
    { opacity: 0, transform: `translate3d(0, ${shift}px, 0)` },
  ], { duration, easing: EASE_IO, fill: 'both' })
  let fired = false
  const fire = () => { if (fired) return; fired = true; try { done?.() } catch {} }
  h.done.then(fire)
  const cancel = h.cancel
  return { anim: h.anim, cancel() { cancel(); fire() }, done: h.done, value: () => 0 }
}

/**
 * View Transitions API для перехода между разделами. Браузер не умеет — тихо
 * возвращаем used:false, и вызывающий сам делает crossfade: анимация всегда одна.
 */
export function viewTransition(update, { } = {}) {
  const run = typeof update === 'function' ? update : () => {}
  const vt = hasWin ? document.startViewTransition : null
  if (motionOff() || typeof vt !== 'function') {
    return { used: false, done: Promise.resolve().then(() => run()) }
  }
  try {
    const t = vt.call(document, run)
    return { used: true, done: Promise.resolve(t.finished).catch(() => {}) }
  } catch {
    return { used: false, done: Promise.resolve().then(() => run()) }
  }
}

/* ---------- viewport ---------- */
/** Подписка на media query: один хук на всю оболочку (телефон/десктоп, палец/мышь). */
export function useMedia(query) {
  const [on, setOn] = useState(() => {
    if (!hasWin || typeof window.matchMedia !== 'function') return false
    try { return window.matchMedia(query).matches } catch { return false }
  })
  useEffect(() => {
    if (!hasWin || typeof window.matchMedia !== 'function') return
    let mq
    try { mq = window.matchMedia(query) } catch { return }
    const h = () => setOn(mq.matches)
    h()
    if (mq.addEventListener) mq.addEventListener('change', h)
    return () => { if (mq.removeEventListener) mq.removeEventListener('change', h) }
  }, [query])
  return on
}

/** Телефонная раскладка оболочки: сайдбар прячется, снизу dock (тот же порог, что и в CSS). */
export const usePhone = () => useMedia('(max-width: 820px)')
/** Указатель грубый (палец) — там вместо :hover работает :active. */
export const useCoarse = () => useMedia('(pointer: coarse)')