/* components/Refresh.jsx — «потяни вниз» как в настоящем приложении.

   Механика жеста целиком в lib/gestures.js (usePullToRefresh): порог, сопротивление,
   закрытие по скорости флика, pointercancel и состояние «идёт обновление». Здесь только
   разметка и индикатор — поэтому «потянуть-обновить» в приложении одна, а страница,
   которая захочет свою разметку индикатора, может взять сам хук.

   Значок — фирменный знак проекта (тот же, что в web/index.html: скруглённый квадрат
   со звездой), нарисован инлайном, чтобы не тянуть отдельный ассет; цвет — `--accent`.
   Индикатор живёт над контентом и не сдвигает страницу: страница не «резинится»
   (overscroll-behavior в index.css), контейнер едет ровно на столько, на сколько тянут. */

import { useEffect, useRef } from 'react'
import { RefreshCw } from 'lucide-react'
import { useI18n } from '../lib/i18n'
import { useMotionOK } from './Pressable'
import { usePullToRefresh } from '../lib/gestures'

const TRIGGER = 72        // сколько тянуть до запуска
const MAX = 128           // дальше тянется с сопротивлением

function BrandMark({ spin }) {
  return (
    <span className="ptr-mark" style={{
      display: 'grid', placeItems: 'center', width: 34, height: 34, flex: 'none',
      borderRadius: 11, background: 'var(--sf2)', color: 'var(--accent)',
      boxShadow: 'inset 0 0 0 1px var(--line)',
    }}>
      <svg width="18" height="18" viewBox="0 0 32 32" aria-hidden="true" style={{
        display: 'block', transform: spin ? 'rotate(360deg)' : 'none',
        transition: 'transform var(--t-slow, .5s) var(--ease-out, cubic-bezier(.2,.8,.2,1))',
      }}>
        <path
          d="M16 7v18M7 16h18M9.6 9.6l12.8 12.8M22.4 9.6L9.6 22.4"
          stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" fill="none"
        />
      </svg>
    </span>
  )
}

/**
 * <PullToRefresh onRefresh={…}>{контент}</PullToRefresh>
 *
 * Жест — Pointer Events (никаких touch-событий и preventDefault): вооружается только
 * когда страница уже на самом верху, поэтому вертикальный скролл не перехватывается.
 *   refreshing   — внешнее «страница сама обновляет данные»: индикатор крутится и жест
 *                 не начинается, пока флаг не снимется;
 *   onStateChange('armed' | 'refreshing' | 'idle') — для страницы, которой нужно знать
 *                 о намерении пользователя;
 *   label        — своя подпись вместо refresh.* (по умолчанию они и есть).
 */
export function PullToRefresh({
  onRefresh, children, disabled = false, threshold = TRIGGER, className = '',
  label, refreshing = false, onStateChange,
}) {
  const { t } = useI18n()
  const ok = useMotionOK()
  /* enabled: undefined → хук сам решает (палец, не мышь); false → жест выключен */
  const ptr = usePullToRefresh({ onRefresh, threshold, max: MAX, enabled: disabled || refreshing ? false : undefined })
  const busy = ptr.busy || refreshing

  /* подписи состояния для вызывающего: «вооружились» → ждём отпускания, потом «обновляем» */
  const tell = useRef(onStateChange)
  tell.current = onStateChange
  const armed = useRef(false)
  const wasBusy = useRef(false)
  useEffect(() => {
    const say = (s) => { try { tell.current?.(s) } catch {} }
    if (busy && !wasBusy.current) say('refreshing')
    else if (!busy && wasBusy.current) say('idle')
    wasBusy.current = busy
  }, [busy])
  useEffect(() => {
    if (busy || !ptr.pull) { armed.current = false; return }
    if (ptr.pull < threshold || armed.current) return
    armed.current = true
    try { tell.current?.('armed') } catch {}
  }, [ptr.pull, threshold, busy])

  const pull = ptr.pull
  const p = ptr.progress
  const hint = busy ? t('refresh.refreshing') : pull >= threshold ? t('refresh.release') : t('refresh.pull')
  const still = !ok

  return (
    <div
      className={`ptr ${busy ? 'is-refreshing' : ''} ${className}`}
      style={{ position: 'relative', overflowAnchor: 'none' }}
      aria-busy={busy || undefined}
      {...ptr.bind}
    >
      {/* индикатор: только визуальный (aria-hidden), состояние объявляет aria-busy выше */}
      <div
        className="ptr-head"
        aria-hidden="true"
        style={{
          position: 'absolute', left: 0, right: 0, top: 0, display: 'flex',
          justifyContent: 'center', alignItems: 'center', gap: 8,
          pointerEvents: 'none',
          transform: `translateY(${Math.max(0, pull - 40)}px)`,
          opacity: pull > 4 || busy ? 1 : 0,
        }}
      >
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '5px 10px 5px 6px', borderRadius: 999,
          background: 'var(--sf)', boxShadow: 'inset 0 0 0 1px var(--line)',
          color: pull >= threshold || busy ? 'var(--accent)' : 'var(--ink-3)',
          fontSize: 'var(--fs-xs)', fontWeight: 500, whiteSpace: 'nowrap',
        }}>
          <BrandMark spin={busy} />
          {busy ? <RefreshCw size={13} className={ok ? 'animate-spin' : ''} /> : (
            <span style={{
              display: 'grid', placeItems: 'center', width: 22, height: 22,
              transform: `rotate(${(1 - p) * 140}deg)`, opacity: 0.45 + p * 0.55,
              transition: still ? 'none' : 'transform var(--t-fast) var(--ease-out), opacity var(--t-fast) linear',
            }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <path d="M20 12a8 8 0 1 1-2.6-5.9" /><path d="M20 4v5h-5" />
              </svg>
            </span>
          )}
          {label || hint}
        </span>
      </div>
      {/* Контент едет за пальцем и возвращается на место пружиной хука (lib/gestures.js):
          пока тянут, значение приходит каждый кадр, поэтому CSS-переход тут только мешал бы. */}
      <div
        className="ptr-body"
        style={{
          transform: pull ? `translateY(${pull}px)` : 'none',
          willChange: pull ? 'transform' : 'auto',
        }}
      >
        {children}
      </div>
    </div>
  )
}

export default PullToRefresh
