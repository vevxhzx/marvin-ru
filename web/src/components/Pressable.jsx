import { forwardRef, useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { motionOff, press } from '../lib/motion'

/* Pressable — базовый интерактивный элемент приложения: scale(0.97) под пальцем и
   пружинный возврат.

   Отклик берётся из `lib/motion.js` (`press`): это одна пружина на всё приложение,
   там же гашение движения — `prefers-reduced-motion` и настройка «меньше движения»
   (классы `.no-motion` / `.no-anim` на <html>, их ставит prefs.apply). Никакого
   `transition` в инлайн-стиле: у `.btn` и `.btn-icon` свои переходы по фону и тени,
   и перебивать их нельзя — анимация идёт через Web Animations API поверх.

   Тактильный отклик только визуальный: `navigator.vibrate` на iOS/Safari не работает,
   поэтому «отклик» = масштаб, а не вибрация.

   Поля ввода и слайдеры отклик не сжимают: у press есть opt-out `[data-no-press]`. */

export const PRESS_SCALE = 0.97

/* ----------------------------------------------------------- подписка на движение */
/* motionOff() из motion.js — источник истины, а здесь только реактивная обёртка:
   настройка «меньше движения» меняет класс на <html>, и компоненты должны перерисоваться. */
const hasDoc = typeof document !== 'undefined'
const _mq = typeof window !== 'undefined' && window.matchMedia
  ? window.matchMedia('(prefers-reduced-motion: reduce)')
  : null
const _subs = new Set()
let _mo = null

const _snapshot = () => !motionOff()

function _subscribe(cb) {
  _subs.add(cb)
  if (_subs.size === 1 && hasDoc) {
    const onMq = () => _subs.forEach((f) => f())
    _mq?.addEventListener?.('change', onMq)
    _mo = new MutationObserver(onMq)
    _mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    window.addEventListener('pageshow', onMq)
    _subs._off = () => {
      _mq?.removeEventListener?.('change', onMq)
      window.removeEventListener('pageshow', onMq)
      _mo?.disconnect(); _mo = null
    }
  }
  return () => {
    _subs.delete(cb)
    if (!_subs.size && _subs._off) { _subs._off(); _subs._off = null }
  }
}

/** true, когда анимации разрешены (не prefers-reduced-motion и не «меньше движения») */
export function useMotionOK() {
  return useSyncExternalStore(_subscribe, _snapshot, () => true)
}

/** то же самое вне React */
export const motionOK = () => !motionOff()

/* --------------------------------------------------------------------- хук */
/** Вешает пружинный отклик на элемент. Возвращает ref и bind для data-pressed. */
export function usePress({ scale = PRESS_SCALE, disabled = false } = {}) {
  const [pressed, setPressed] = useState(false)
  const elRef = useRef(null)

  useEffect(() => {
    const el = elRef.current
    if (!el || disabled) return undefined
    return press(el, { scale })
  }, [scale, disabled])

  // data-pressed — для CSS и для тестов; само нажатие живёт в motion.press
  const on = pressed ? '' : undefined
  useEffect(() => {
    const el = elRef.current
    if (!el || disabled) return undefined
    const down = (e) => { if (e.button == null || e.button === 0) setPressed(true) }
    const up = () => setPressed(false)
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
      setPressed(false)
    }
  }, [disabled])

  return { pressed, bind: { 'data-pressed': on }, elRef }
}

/* -------------------------------------------------------------- компонент */
/**
 * <Pressable className="btn" onClick={…}>Отправить</Pressable>
 * <Pressable as="div" role="link" …>  — не-<button> получают role/tabIndex
 * Дополнительно: scale, disabled, as, остальное уходит в DOM как обычно.
 */
export const Pressable = forwardRef(function Pressable(props, ref) {
  const {
    as: Tag = 'button', type, scale, disabled = false, className = '', style,
    onPointerDown, onPointerUp, onPointerCancel, onPointerLeave, onBlur, onKeyDown, onKeyUp,
    children, ...rest
  } = props
  const { bind, elRef } = usePress({ scale, disabled })

  const setRef = useCallback((node) => {
    elRef.current = node
    if (typeof ref === 'function') ref(node)
    else if (ref && typeof ref === 'object') ref.current = node
  }, [elRef, ref])

  const isButton = Tag === 'button'
  const p = { ...rest, ...bind, ref: setRef, className, style }
  // чужие обработчики не переписываем и не создаём лишних: их может не быть
  const own = { onPointerDown, onPointerUp, onPointerCancel, onPointerLeave, onBlur, onKeyDown, onKeyUp }
  for (const k in own) if (own[k]) p[k] = own[k]
  if (isButton) p.type = type || 'button'
  else if (!p.role) { p.role = 'button'; if (p.tabIndex == null) p.tabIndex = disabled ? -1 : 0 }
  if (disabled) { if (isButton) p.disabled = true; else p['aria-disabled'] = true }
  return <Tag {...p}>{children}</Tag>
})

/* ------------------------------------------------------------- вспомогательное */
/** Кнопка, которая на секунду гаснет: [вкл, flash] — как useDoneFlash, но c гашением. */
export function useFlash(ms = 1100) {
  const [on, setOn] = useState(false)
  const timer = useRef(0)
  const flash = useCallback(() => {
    setOn(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setOn(false), ms)
  }, [ms])
  useEffect(() => () => clearTimeout(timer.current), [])
  return [on, flash]
}