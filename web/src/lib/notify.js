import { name } from './name'
// Браузерные уведомления: напоминания и действия из Telegram приходят через SSE (/api/events/stream).
// Включаются на странице настроек. На iPhone работают после «Добавить на экран Домой» (PWA).
export const notifySupported = () => typeof window !== 'undefined' && 'Notification' in window
export const notifyState = () => (notifySupported() ? Notification.permission : 'unsupported')
export const notifyEnabled = () => notifyState() === 'granted' && localStorage.getItem('notify') !== 'off'

export async function enableNotifications() {
  if (!notifySupported()) return 'unsupported'
  const p = await Notification.requestPermission()
  if (p === 'granted') { localStorage.setItem('notify', 'on'); show('Уведомления включены', 'Буду напоминать прямо здесь, сэр.') }
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
  if (ev.kind === 'reminder') return show('Напоминание', ev.text || 'Напоминание', 'rem-' + (ev.id || Date.now()))
  if (ev.kind === 'chat' && ev.channel && ev.channel !== 'web' && ev.actions?.length) {
    const map = { add_event: 'событие в календарь', add_task: 'задачу', add_expense: 'трату', add_income: 'доход', add_note: 'заметку', add_link: 'ссылку', add_debt: 'долг', update_event: 'изменение в календаре', undo: 'откат' }
    const what = ev.actions.map((a) => map[a]).filter(Boolean)[0]
    if (what) show(name(), `Добавил ${what} из Telegram`, 'chat-' + Date.now())
  }
}
