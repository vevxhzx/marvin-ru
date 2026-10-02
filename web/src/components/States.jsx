import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, Check, WifiOff } from 'lucide-react'
import { useI18n } from '../lib/i18n'
import { Pressable, useMotionOK } from './Pressable'
import { PullToRefresh } from './Refresh'

/* Готовые состояния, которых раньше не было отдельными примитивами: ошибка, офлайн и
   короткое подтверждение. Все три — на одних токенах (--sf2/--fill/--line + смысловой
   цвет через .tint-*), с зоной нажатия не меньше --tap-sm, подписью и aria, и уважают
   «меньше движения». PullToRefresh переэкспортирован отсюда, чтобы страницам хватало
   одного входа в примитивы состояний. */

export { PullToRefresh }

const ICON = 34
const TONE_COLOR = { ok: 'pos', warn: 'warn', neg: 'neg', ai: 'ai' }

function Frame({ tone = '', glyph, children, compact, className = '', style, ...rest }) {
  return (
    <div
      className={`state ${tone ? `tint-${tone}` : ''} ${className}`}
      style={{
        display: 'flex', gap: 12, alignItems: 'flex-start',
        padding: compact ? '12px 14px' : '14px 16px',
        borderRadius: 'var(--r-md)',
        ...style,
      }}
      {...rest}
    >
      <span aria-hidden="true" style={{
        display: 'grid', placeItems: 'center', flex: 'none',
        width: ICON, height: ICON, borderRadius: 11,
        background: 'var(--fill)', color: `var(--${TONE_COLOR[tone] || 'ink-2'})`,
      }}>{glyph}</span>
      <div style={{ minWidth: 0, flex: 1 }}>{children}</div>
    </div>
  )
}

/* зону нажатия не задаём inline: в index.css для .btn-sm на тач-экранах уже стоит
   min-height: var(--tap), и inline-стиль его бы перебил в меньшую сторону */
function Retry({ onRetry, children }) {
  const { t } = useI18n()
  return (
    <Pressable className="btn-soft btn-sm" onClick={() => onRetry?.()} style={{ marginTop: 10 }}>
      {children || t('common.retry')}
    </Pressable>
  )
}

/* ------------------------------------------------------------------ ошибка */
/**
 * Что-то не загрузилось: коротко — что случилось, подробности — мелким моно,
 * и кнопка «проверить снова». Кнопка обязательна: состояние без действия — тупик.
 * onRetry без аргументов (onRetry(err)), чтобы страница могла сам решить, что перезагружать.
 */
export function ErrorState({
  title, sub, detail, onRetry, retryLabel, compact, className, style, onClose,
}) {
  const { t } = useI18n()
  const err = detail instanceof Error || (detail && typeof detail === 'object')
    ? (detail?.message || detail?.statusText || '')
    : (typeof detail === 'string' ? detail : '')
  return (
    <Frame
      tone="neg"
      compact={compact}
      className={className}
      style={style}
      role="alert"
      glyph={<AlertTriangle size={17} strokeWidth={2.2} />}
    >
      <div className="h4" style={{ fontSize: 'var(--fs-base)' }}>{title || t('state.error_title')}</div>
      {(sub || err) && (
        <div className="muted" style={{ marginTop: 3, fontSize: 'var(--fs-md)', lineHeight: 'var(--lh-snug)' }}>
          {sub || err}
        </div>
      )}
      {sub && err && (
        <div className="mono" style={{
          marginTop: 6, fontSize: 'var(--fs-xs)', color: 'var(--ink-3)',
          overflowWrap: 'anywhere', maxHeight: 72, overflow: 'hidden',
        }}>{err}</div>
      )}
      {onRetry && <Retry onRetry={onRetry}>{retryLabel}</Retry>}
      {onClose && (
        <Pressable className="btn-ghost btn-sm" onClick={() => onClose()} style={{ marginTop: 10 }}>
          {t('common.close')}
        </Pressable>
      )}
    </Frame>
  )
}

/* ----------------------------------------------------------------- офлайн */
/**
 * Сети нет: когда последний раз была синхронизация (fmtAgo) и что всё равно доступно —
 * чтобы не выглядело, что данные исчезли. offline можно задать вручную (знает страница),
 * иначе берётся navigator.onLine и слушаются online/offline.
 */
export function OfflineState({ lastSync, onRetry, compact, className, style, offline, children }) {
  const { t, fmtAgo } = useI18n()
  const [down, setDown] = useState(() => (typeof navigator !== 'undefined' && navigator.onLine === false))
  const [, tick] = useState(0)

  useEffect(() => {
    if (offline != null) { setDown(!!offline); return undefined }
    const up = () => { setDown(false); tick((x) => x + 1) }
    const go = () => setDown(true)
    window.addEventListener('online', up)
    window.addEventListener('offline', go)
    return () => { window.removeEventListener('online', up); window.removeEventListener('offline', go) }
  }, [offline])

  const since = useMemo(() => {
    if (!lastSync) return null
    const d = lastSync instanceof Date ? lastSync : new Date(lastSync)
    return Number.isNaN(d.getTime()) ? null : fmtAgo(d)
  }, [lastSync, fmtAgo])

  return (
    <Frame
      tone="warn"
      compact={compact}
      className={className}
      style={style}
      role="status"
      data-offline={down ? '' : undefined}
      glyph={<WifiOff size={17} strokeWidth={2.2} />}
    >
      <div className="h4" style={{ fontSize: 'var(--fs-base)' }}>{t('state.offline_title')}</div>
      <div className="muted" style={{ marginTop: 3, fontSize: 'var(--fs-md)', lineHeight: 'var(--lh-snug)' }}>
        {t('state.offline_sub')}
      </div>
      {since && (
        <div className="mono" style={{ marginTop: 6, fontSize: 'var(--fs-xs)', color: 'var(--ink-3)' }}>
          {`${t('state.offline_sync')} · ${since}`}
        </div>
      )}
      <div className="muted" style={{ marginTop: 6, fontSize: 'var(--fs-xs)', lineHeight: 'var(--lh-body)' }}>
        {t('state.offline_available')}
      </div>
      {children}
      {onRetry && <Retry onRetry={onRetry} />}
    </Frame>
  )
}

/* ----------------------------------------------------------------- успех */
/**
 * Короткая подтверждающая плашка: «сохранено» — и тишина. Сама прячется через ms
 * (ms = 0 — не прятать), onDone зовётся в момент исчезновения (в ref, чтобы
 * инлайновая функция родителя не перезапускала таймер на каждом рендере).
 */
export function SuccessState({ text, sub, ms = 1800, onDone, compact, className, style, glyph, children }) {
  const { t } = useI18n()
  const ok = useMotionOK()
  const [gone, setGone] = useState(false)
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  useEffect(() => {
    if (!ms) return undefined
    const timer = setTimeout(() => { setGone(true); doneRef.current?.() }, ms)
    return () => clearTimeout(timer)
  }, [ms])

  if (gone) return null
  return (
    <Frame
      tone="ok"
      compact
      className={`state-ok ${className}`}
      style={{ ...style, animation: ok ? 'toastIn .4s var(--ease-spring) both' : 'none' }}
      role="status"
      glyph={glyph || <Check size={17} strokeWidth={2.6} />}
    >
      <div style={{ minWidth: 0 }}>
        <div className="h4" style={{ fontSize: 'var(--fs-md)' }}>{text || t('state.success_done')}</div>
        {sub && <div className="muted" style={{ marginTop: 2, fontSize: 'var(--fs-xs)', lineHeight: 'var(--lh-snug)' }}>{sub}</div>}
        {children}
      </div>
    </Frame>
  )
}