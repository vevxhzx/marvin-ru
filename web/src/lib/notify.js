import { name } from './name'
import { t } from './i18n'
// Браузерные уведомления: напоминания и действия из Telegram приходят через SSE (/api/events/stream).
// Включаются на странице настроек. На iPhone работают после «Добавить на экран Домой» (PWA).
export const notifySupported = () => typeof window !== 'undefined' && 'Notification' in window
export const notifyState = () => (notifySupported() ? Notification.permission : 'unsupported')
export const notifyEnabled = () => notifyState() === 'granted' && localStorage.getItem('notify') !== 'off'

export async function enableNotifications() {
  if (!notifySupported()) return 'unsupported'
  const p = await Notification.requestPermission()
  if (p === 'granted') { localStorage.setItem('notify', 'on'); show(t('notify.enabled'), t('notify.enabled_hint')) }
  return p
}
export const disableNotifications = () => localStorage.setItem('notify', 'off')

const RECENT = new Map()
export function show(title, body, tag) {
  if (!notifyEnabled()) return
  const key = tag || title + body
  if (RECENT.get(key) > Date.now() - 60_000) return
  RECENT.set(key, Date.now())
  try {
    const n = new Notification(title, { body, tag: key, icon: '/icon-192.png', badge: '/icon-192.png', silent: false })
    n.onclick = () => { window.focus(); n.close() }
  } catch {}
}

// Что показывать по событиям SSE. Действия с самого сайта (channel=web) не дублируем.
export function notifyFromEvent(ev) {
  if (!ev || !notifyEnabled()) return
  if (document.visibilityState === 'visible' && ev.kind !== 'reminder') return
  if (ev.kind === 'reminder') return show(t('notify.reminder'), ev.text || t('notify.reminder'), 'rem-' + (ev.id || Date.now()))
  if (ev.kind === 'chat' && ev.channel && ev.channel !== 'web' && ev.actions?.length) {
    const map = { add_event: 'act_add_event', add_task: 'act_add_task', add_expense: 'act_add_expense', add_income: 'act_add_income', add_note: 'act_add_note', add_link: 'act_add_link', add_debt: 'act_add_debt', update_event: 'act_update_event', undo: 'common.undo' }
    const what = ev.actions.map((a) => map[a] && t(map[a])).filter(Boolean)[0]
    if (what) show(name(), t('notify.added_from_tg', { what }), 'chat-' + Date.now())
  }
}
