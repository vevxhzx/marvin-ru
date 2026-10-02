/* lib/gestures.js — жесты пальцем на Pointer Events (без touch-событий и без библиотек).

   Три вещи, которые нужны оболочке:
   • useSheetDrag   — свайп за «ручку» шторки: тянем вниз — уезжает и закрывается, причём
                      по скорости, а не только по расстоянию; шаг между точками прилипания.
                      Работает с любым числом снапов (см. SHEET_SNAPS), единственная
                      реализация этого жеста во всём приложении: её использует шторка
                      из components/ui.jsx (через компонент-обёртку SheetHost).
   • usePullToRefresh — потянуть страницу вниз от самого верха; вооружение только когда
                      страница уже на нуле, поэтому жест не борется с вертикальным скроллом.
   • velocityOf    — скорость жеста в px/мс по последним точкам (решение «флик или нет»).

   Общие правила: работаем через Pointer Events, `pointercancel` отменяет жест без
   последствий (с элемент возвращается пружиной/переходом), а `touch-action: none`
   ставим только на саму ручку — вертикальный скролл контейнера остаётся родным.

   Геометрия (сколько пикселей в каждой точке прилипания) — не здесь: её считает
   компонент шторки, у которого есть размеры окна и зум. Здесь только механика. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { motionOff, spring, useMedia, useCoarse } from './motion'

const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now())
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v)
const EMPTY = []

/* Telegram Mini App сама закрывает приложение свайпом вниз (и мы зовём
   app.disableVerticalSwipes) — там шторку за ручку не тянем. */
const inTelegram = () => typeof document !== 'undefined'
  && document.documentElement.classList.contains('in-telegram')

/** Скорость жеста в px/мс по окну последних точек. > 0 — вниз, < 0 — вверх. */
export function velocityOf(samples, windowMs = 110) {
  if (!samples || samples.length < 2) return 0
  const last = samples[samples.length - 1]
  let first = samples[0]
  for (let i = samples.length - 1; i >= 0; i--) {
    if (last.at - samples[i].at > windowMs) break
    first = samples[i]
  }
  const dt = last.at - first.at
  if (dt <= 0) return 0
  return (last.y - first.y) / dt
}

/* ---------------------------------------------------------------------------
   Свайп за ручку шторки
   --------------------------------------------------------------------------- */
/** Точки прилипания снизу вверх. Геометрию каждой считает шторка (ui.jsx#Sheet). */
export const SHEET_SNAPS = ['peek', 'half', 'full']

/** Доля доступной высоты, которую занимает каждая точка прилипания. */
export const SNAP_RATIO = { peek: 0.28, half: 0.52, full: 0.92 }

/* Пороги жеста: флик важнее расстояния — короткий быстрый свайп тоже считается. */
const FLICK = 0.5        // px/мс — шаг по точкам и закрытие с самой верхней точки
const FLICK_CLOSE = 0.45 // чуть мягче для свёрнутого состояния: там и так короткий ход
const CLOSE_DY = 56      // в свёрнутом состоянии столько достаточно для закрытия
const STEP_DY = 72       // столько нужно, чтобы шагнуть на соседнюю точку
const TRAVEL_MAX = 340   // резина вниз: ниже не едет

/**
 * useSheetDrag({ open, onClose, snaps, snap, setSnap, height, phone, enabled })
 *
 * Единственная реализация свайпа шторки — Pointer Events, без touchmove и без
 * preventDefault: `touch-action: none` на ручке сам по себе не даёт контейнеру начать
 * скролл, а прокрутка содержимого шторки (overscroll-behavior: contain) остаётся родной.
 *
 *   snaps    — высоты точек прилипания в px, снизу вверх (см. SHEET_SNAPS);
 *   snap     — индекс текущей точки (высота и transform ставит компонент шторки);
 *   setSnap  — шаг на соседнюю точку: вниз по вверх, вниз до закрытия;
 *   height   — текущая высота шторки в px (для порога «прошёл четверть экрана»);
 *   phone    — телефонная раскладка; по умолчанию (max-width: 639px).
 *
 * Возвращает { dy, dragging, grip }: dy — на сколько пикселей шторка уехала за пальцем
 * (элемент шторки сам превращает это в transform), grip — пропсы на «ручку».
 * Отпустили без флика — сдвиг снимается и элемент возвращается переходом из CSS;
 * pointercancel отменяет жест целиком, ничего не меняя по снапам.
 */
export function useSheetDrag({ open, onClose, snaps, snap = 0, setSnap, height, phone, enabled } = {}) {
  const narrow = useMedia('(max-width: 639px)')
  const isPhone = phone == null ? narrow : phone
  const live = enabled == null ? !!(open && isPhone) : !!enabled

  const list = snaps || EMPTY
  const last = Math.max(0, list.length - 1)
  const [dy, setDy] = useState(0)
  const [dragging, setDragging] = useState(false)
  const st = useRef(null)
  const dyRef = useRef(0)
  /* актуальные снап и высота на момент кадра: обработчики не должны «замыкаться» */
  const cur = useRef({ snap, height })
  cur.current = { snap, height }

  const setDyV = useCallback((v) => { dyRef.current = v; setDy(v) }, [])

  /* сброс при закрытии: ни сдвига, ни незакрытого жеста */
  useEffect(() => {
    if (open) return
    setDyV(0); setDragging(false); st.current = null
  }, [open, setDyV])

  /* Резина: вниз едем до упора, вверх — только настолько, насколько ещё есть запаса
     до самой высокой точки (иначе шторка уехала бы выше экрана). */
  const rubber = useCallback((d) => {
    if (d >= 0) return Math.min(d, TRAVEL_MAX)
    const room = Math.max(72, (list[last] || 0) - (cur.current.height || 0) + (last - cur.current.snap) * 48)
    return -Math.min(-d, room)
  }, [last, list])

  const onDown = useCallback((e) => {
    if (!live || inTelegram()) return
    if (e.button != null && e.button !== 0) return
    if (e.target !== e.currentTarget) return          // тянем только за саму ручку
    st.current = {
      y: e.clientY,
      snap: Math.min(Math.max(cur.current.snap, 0), last),
      samples: [{ y: e.clientY, at: now() }],
      moved: 0,
    }
    setDragging(true)
    try { e.currentTarget.setPointerCapture?.(e.pointerId) } catch {}
  }, [last, live])

  const onMove = useCallback((e) => {
    const s = st.current
    if (!s) return
    s.samples.push({ y: e.clientY, at: now() })
    if (s.samples.length > 6) s.samples.shift()
    const d = rubber(e.clientY - s.y)
    s.moved = Math.max(s.moved, Math.abs(d))
    setDyV(d)
  }, [rubber, setDyV])

  const onUp = useCallback((e, cancelled) => {
    const s = st.current
    st.current = null
    setDragging(false)
    if (!s) { setDyV(0); return }
    try { e.currentTarget.releasePointerCapture?.(e.pointerId) } catch {}
    const d = dyRef.current
    const v = velocityOf(s.samples)          // > 0 — вниз
    const from = s.snap
    const go = (i) => { try { setSnap?.(Math.max(0, Math.min(last, i))) } catch {} }
    setDyV(0)
    if (cancelled) return                    // отмена жеста: просто на место

    if (d > 0 && from >= last) {             // уже на самой высокой точке — вниз это «закрыть»
      if (d > 110 || v > FLICK) onClose?.()
      return
    }
    if (d > 0) {
      if (from === 0 && (d > CLOSE_DY || v > FLICK_CLOSE)) { onClose?.(); return }
      if (d > Math.max(STEP_DY, (height || 240) * 0.22) || v > FLICK) go(from - 1)
      return
    }
    /* вверх: растягиваться выше верхней точки некуда, поэтому только соседний снап */
    if (d < 0 && (-d > 64 || v < -FLICK)) go(from + 1)
  }, [height, last, onClose, setDyV, setSnap])

  /* Тап по ручке без перетаскивания — развернуть на шаг, а с верхней точки — свернуть. */
  const onTap = useCallback(() => {
    if (last <= 0) return
    const from = Math.min(Math.max(cur.current.snap, 0), last)
    try { setSnap?.(from >= last ? from - 1 : from + 1) } catch {}
  }, [last, setSnap])

  const grip = {
    onPointerDown: onDown,
    onPointerMove: onMove,
    onPointerUp: (e) => { const s = st.current; onUp(e, false); if (s && s.moved < 6) onTap() },
    onPointerCancel: (e) => onUp(e, true),
    style: { touchAction: 'none' },
  }

  return { dy, dragging, grip }
}

/* ---------------------------------------------------------------------------
   Потянуть-обновить
   --------------------------------------------------------------------------- */
/**
 * usePullToRefresh({ onRefresh, threshold, max, enabled })
 *
 * bind — пропсы для прокручиваемой области. Вооружение только когда страница уже
 * наверху (window.scrollY ≤ 2): ниже по экрану жест просто не начинается, поэтому
 * вертикальный скролл контейнера никогда не перехватывается. Ничего не отменяем
 * через preventDefault — нативная прокрутка остаётся нетронутой, а индикатор едет
 * за пальцем сам.
 *
 * Отдаёт { pull, progress, busy, style, ring, bind, threshold }: pull — сколько сейчас
 * тянем (px), progress — 0…1 до порога, busy — идёт onRefresh (повторный жест не
 * начинается), style/ring — готовые transform для простого индикатора (брендовый
 * индикатор в components/Refresh.jsx рисует свой, опираясь на те же pull/progress/busy).
 */
export function usePullToRefresh({ onRefresh, threshold = 72, max = 132, enabled } = {}) {
  const coarse = useCoarse()
  const live = enabled == null ? coarse : !!enabled      // мышью не тянем
  const [pull, setPull] = useState(0)
  const [busy, setBusy] = useState(false)
  const pullRef = useRef(0)
  const st = useRef(null)
  const animRef = useRef(null)
  const busyRef = useRef(false)
  const setPullV = useCallback((v) => { pullRef.current = v; setPull(v) }, [])

  const settle = useCallback((to = 0) => {
    animRef.current?.cancel?.()
    if (motionOff() || !pullRef.current) { setPullV(to); return }
    animRef.current = spring({
      from: pullRef.current, to, stiffness: 340, damping: 34,
      onUpdate: (v) => setPullV(v),
      onComplete: () => setPullV(to),
    })
  }, [setPullV])

  const bind = {
    onPointerDown: (e) => {
      if (!live || busyRef.current) return
      if (e.pointerType === 'mouse') return                 // мышью не тянем
      if (typeof window !== 'undefined' && window.scrollY > 2) return
      st.current = { y: e.clientY, samples: [{ y: e.clientY, at: now() }] }
    },
    onPointerMove: (e) => {
      const s = st.current
      if (!s) return
      s.samples.push({ y: e.clientY, at: now() })
      if (s.samples.length > 6) s.samples.shift()
      const raw = e.clientY - s.y
      const d = raw > 0 ? Math.min(max, raw * 0.55) : 0      // резина
      if (raw < 0) { settle(0); st.current = null; return }
      setPullV(d)
    },
    onPointerUp: (e) => {
      const s = st.current
      st.current = null
      if (!s) return
      const v = velocityOf(s.samples)
      const d = pullRef.current
      if (d > threshold || (v > 0.45 && d > 24)) {
        busyRef.current = true
        setBusy(true)
        setPullV(Math.max(d, threshold * 0.9))
        try {
          const p = onRefresh?.()
          Promise.resolve(p).catch(() => {}).then(() => {
            busyRef.current = false; setBusy(false); settle(0)
          })
        } catch { busyRef.current = false; setBusy(false); settle(0) }
      } else settle(0)
    },
    onPointerCancel: () => { st.current = null; settle(0) },
  }

  useEffect(() => () => animRef.current?.cancel?.(), [])

  /* Индикатор: transform + opacity и ничего больше. */
  const progress = clamp(pull / threshold, 0, 1)
  const style = {
    transform: `translate3d(0, ${(pull * 0.6 - 8).toFixed(1)}px, 0) scale(${(0.86 + 0.14 * progress).toFixed(3)})`,
    opacity: clamp(progress * 1.4, 0, 1),
    pointerEvents: 'none',
    willChange: 'transform, opacity',
  }
  const ring = { transform: `rotate(${(progress * 270).toFixed(1)}deg)` }

  return { pull, progress, busy, style, ring, bind, threshold }
}
