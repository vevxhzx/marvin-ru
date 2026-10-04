const BASE = ''
import { getLang, localeOf, t, fmtDate, fmtNumber, fmtMoney, pluralIndex } from './i18n'
import { tg } from './tg'

async function req(method, path, body, timeoutMs = 30000) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  let r
  try {
    r = await fetch(BASE + path, {
      method,
      headers: body ? { 'content-type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    })
  } catch (err) {
    if (err?.name === 'AbortError') {
      const e = new Error(t('api.no_response', { method, path, sec: Math.round(timeoutMs / 1000) }))
      e.status = 0
      throw e
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
  if (r.status === 401) {
    const msg = tg.active
      ? (tg.error ? t('api.tg_denied', { err: tg.error }) : t('api.tg_session_expired'))
      : t('api.no_access_device')
    const e = new Error(msg); e.status = 401
    window.dispatchEvent(new CustomEvent('assistant:denied', { detail: { msg, tg: tg.active, tgError: tg.error } }))
    throw e
  }
  if (!r.ok) {
    let msg = `${method} ${path} → ${r.status}`
    try { const j = await r.json(); if (j?.detail) msg = typeof j.detail === 'string' ? j.detail : (j.detail[0]?.msg || msg) } catch {}
    const e = new Error(msg); e.status = r.status; throw e
  }
  const ct = r.headers.get('content-type') || ''
  return ct.includes('json') ? r.json() : r.text()
}

export const api = {
  get: (p) => req('GET', p),
  post: (p, b) => req('POST', p, b),
  put: (p, b) => req('PUT', p, b),
  del: (p) => req('DELETE', p),

  health: () => req('GET', '/api/health'),
  dashboard: () => req('GET', '/api/dashboard'),
  missed: () => req('GET', '/api/missed'),
  chat: (text) => req('POST', '/api/chat', { text, channel: 'web' }, 120000),   // ответ ядра (LLM) может идти долго
  chatHistory: (limit = 40) => req('GET', `/api/chat/history?limit=${limit}`),

  events: (start, end, tasksToo = false) => req('GET', `/api/events?${start ? `start=${start}` : ''}${end ? `&end=${end}` : ''}${tasksToo ? '&tasks_too=true' : ''}`),
  addEvent: (e) => req('POST', '/api/events', e),
  updateEvent: (id, e) => req('PUT', `/api/events/${id}`, e),
  delEvent: (id) => req('DELETE', `/api/events/${id}`),

  tasks: (all = false, eventsToo = false) => req('GET', `/api/tasks?all=${all}${eventsToo ? '&events_too=true' : ''}`),
  doneEvent: (id, done = true, date = null) => req('POST', `/api/events/${id}/done`, { done, date }),
  addTask: (t) => req('POST', '/api/tasks', t),
  doneTask: (id) => req('POST', `/api/tasks/${id}/done`),
  undoneTask: (id) => req('POST', `/api/tasks/${id}/undone`),
  delTask: (id) => req('DELETE', `/api/tasks/${id}`),

  finSummary: (days = 30) => req('GET', `/api/finance/summary?days=${days}`),
  finForecast: (days = 30) => req('GET', `/api/finance/forecast?days=${days}`),
  txs: (days = 30) => req('GET', `/api/finance/transactions?days=${days}`),
  addTx: (t) => req('POST', '/api/finance/transactions', t),
  updateTx: (id, t) => req('PUT', `/api/finance/transactions/${id}`, t),
  delTx: (id) => req('DELETE', `/api/finance/transactions/${id}`),
  categories: () => req('GET', '/api/finance/categories'),
  accounts: () => req('GET', '/api/finance/accounts'),
  addAccount: (a) => req('POST', '/api/finance/accounts', a),
  updateAccount: (id, a) => req('PUT', `/api/finance/accounts/${id}`, a),
  delAccount: (id) => req('DELETE', `/api/finance/accounts/${id}`),
  debts: () => req('GET', '/api/finance/debts'),
  addDebt: (d) => req('POST', '/api/finance/debts', d),
  payDebt: (id, amount, extra = {}) => req('POST', `/api/finance/debts/${id}/pay`, { amount, ...extra }),
  updateDebt: (id, d) => req('PUT', `/api/finance/debts/${id}`, d),
  delDebt: (id) => req('DELETE', `/api/finance/debts/${id}`),
  // all=true — вместе с паузами: иначе «Зарплата»/«Аренда» на паузе невидимы и не редактируются
  recurring: (all = false) => req('GET', `/api/finance/recurring${all ? '?all=true' : ''}`),
  addRecurring: (r) => req('POST', '/api/finance/recurring', r),
  updateRecurring: (id, r) => req('PUT', `/api/finance/recurring/${id}`, r),
  delRecurring: (id) => req('DELETE', `/api/finance/recurring/${id}`),

  notes: (q) => req('GET', `/api/notes${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  addNote: (text, tags = []) => req('POST', '/api/notes', { text, tags }),
  addNotePhoto: async (file, text = '') => {
    const fd = new FormData(); fd.append('file', file); fd.append('text', text)
    const r = await fetch(BASE + '/api/notes/photo', { method: 'POST', body: fd })
    if (!r.ok) { let msg = t('api.photo_failed', { status: r.status }); try { const j = await r.json(); if (j?.detail) msg = j.detail } catch {} throw new Error(msg) }
    return r.json()
  },
  delNote: (id) => req('DELETE', `/api/notes/${id}`),
  editNote: (id, patch) => req('PUT', `/api/notes/${id}`, patch),
  links: (q) => req('GET', `/api/links${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  addLink: (url, comment) => req('POST', '/api/links', { url, comment }),
  delLink: (id) => req('DELETE', `/api/links/${id}`),
  editLink: (id, patch) => req('PUT', `/api/links/${id}`, patch),
  patchTask: (id, p) => req('PUT', `/api/tasks/${id}`, p),
  undo: () => req('POST', '/api/undo'),
  budgets: () => req('GET', '/api/finance/budgets'),
  updateCategory: (id, c) => req('PUT', `/api/finance/categories/${id}`, c),
  settings: () => req('GET', '/api/settings'),
  saveSettings: (changes) => req('PUT', '/api/settings', { changes }),
  status: () => req('GET', '/api/status'),
  backupNow: () => req('POST', '/api/backup'),
  backups: () => req('GET', '/api/backups'),
  restoreBackup: (name) => req('POST', '/api/backups/restore', { name }),
  semantic: (q, limit = 12) => req('GET', `/api/search/semantic?q=${encodeURIComponent(q)}&limit=${limit}`),
  reindex: () => req('POST', '/api/search/reindex'),
  // заказы / фриланс
  orders: (all = false) => req('GET', `/api/orders${all ? '?all=true' : ''}`),
  addOrder: (o) => req('POST', '/api/orders', o),
  ordersSuggest: (title, clientId) => req('GET', `/api/orders/suggest?title=${encodeURIComponent(title)}${clientId ? `&client_id=${clientId}` : ''}`),
  updateOrder: (id, p) => req('PUT', `/api/orders/${id}`, p),
  delOrder: (id) => req('DELETE', `/api/orders/${id}`),
  payOrder: (id, amount, extra = {}) => req('POST', `/api/orders/${id}/payments`, { amount, ...extra }),
  addOrderTime: (id, minutes, extra = {}) => req('POST', `/api/orders/${id}/time`, { minutes, ...extra }),
  organizePreview: () => req('GET', '/api/pc/organize/preview'),
  orderStats: (months = 6) => req('GET', `/api/orders/stats?months=${months}`),
  // люди и граф связей
  people: () => req('GET', '/api/people'),
  updatePerson: (id, p) => req('PUT', `/api/people/${id}`, p),
  clients: () => req('GET', '/api/orders/clients'),
  timer: () => req('GET', '/api/orders/timer'),
  startTimer: (order_id = null, minutes = null, kind = 'focus') => req('POST', '/api/orders/timer', { order_id, minutes, kind }),   // minutes=null → из настроек помодоро
  pomodoro: () => req('GET', '/api/orders/pomodoro'),
  freelance: () => req('GET', '/api/orders/freelance'),
  saveFreelance: (p) => req('PUT', '/api/orders/freelance', p),
  pulse: () => req('GET', '/api/orders/pulse'),
  savePomodoro: (p) => req('PUT', '/api/orders/pomodoro', p),
  stopTimer: () => req('DELETE', '/api/orders/timer'),
  // CRM (фаза 4) — только новые пути /api/crm/*
  crmOrderCard: (id) => req('GET', `/api/crm/orders/${id}/card`),
  crmSetStage: (id, stage, lost_reason = null) => req('PUT', `/api/crm/orders/${id}/stage`, { stage, lost_reason }),
  crmComment: (id, text, client_id = null, author = null) => req('POST', `/api/crm/orders/${id}/comments`, { text, client_id, author }),
  crmAddCheck: (id, title) => req('POST', `/api/crm/orders/${id}/checklist`, { title }),
  crmToggleCheck: (cid, done = null) => req('PATCH', `/api/crm/checklist/${cid}`, { done }),
  crmDelCheck: (cid) => req('DELETE', `/api/crm/checklist/${cid}`),
  crmClientCard: (id) => req('GET', `/api/crm/clients/${id}/card`),
  crmUpdateClient: (id, p) => req('PUT', `/api/crm/clients/${id}`, p),
  crmFollowups: (all = false) => req('GET', `/api/crm/followups${all ? '?all=true' : ''}`),
  crmScanFollowups: () => req('POST', '/api/crm/followups/scan'),
  crmAnalytics: (months = 6) => req('GET', `/api/crm/analytics?months=${months}`),
  // цели / техники
  goals: (all = false) => req('GET', `/api/finance/goals${all ? '?all=true' : ''}`),
  addGoal: (g) => req('POST', '/api/finance/goals', g),
  updateGoal: (id, p) => req('PUT', `/api/finance/goals/${id}`, p),
  delGoal: (id) => req('DELETE', `/api/finance/goals/${id}`),
  putGoal: (id, amount, extra = {}) => req('POST', `/api/finance/goals/${id}/put`, { amount, ...extra }),
  techniques: () => req('GET', '/api/finance/techniques'),
  facts: (layer) => req('GET', `/api/facts${layer ? `?layer=${layer}` : ''}`),
  addFact: (b) => req('POST', '/api/facts', b),
  updateFact: (id, b) => req('PUT', `/api/facts/${id}`, b),
  forgetFact: (id) => req('POST', `/api/facts/${id}/forget`),
  restoreFact: (id) => req('POST', `/api/facts/${id}/restore`),
  rebuildPortrait: () => req('POST', '/api/facts/portrait'),
  memoryTidy: () => req('POST', '/api/facts/nightly'),
  rebuildStyle: () => req('POST', '/api/facts/style'),
  setStyle: (text) => req('PUT', '/api/facts/style', { text }),
  lessons: () => req('GET', '/api/lessons'),
  delLesson: (id) => req('DELETE', `/api/lessons/${id}`),
  memory: (days = 30, kind, q) => req('GET', `/api/memory?days=${days}${kind ? `&kind=${kind}` : ''}${q ? `&q=${encodeURIComponent(q)}` : ''}`),
}

// потоковый чат: onToken(piece) по мере генерации, resolve({text, actions, via}) в конце
export async function chatStream(text, onToken) {
  const r = await fetch('/api/chat/stream', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text, channel: 'web' }) })
  if (!r.ok || !r.body) throw new Error('stream failed')
  const reader = r.body.getReader(); const dec = new TextDecoder()
  let buf = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2)
      const ev = /^event: (\w+)/m.exec(chunk)?.[1]
      const data = /^data: (.*)$/m.exec(chunk)?.[1]
      if (!ev || data == null) continue
      const parsed = JSON.parse(data)
      if (ev === 'token') onToken?.(parsed)
      else if (ev === 'done') return parsed
    }
  }
  throw new Error('stream ended')
}

export const REPEAT_LABELS = { '': 'repeat_none', daily: 'repeat_daily', weekly: 'repeat_weekly', monthly: 'repeat_monthly', yearly: 'repeat_yearly' }
/* Дни недели коротко: берём из Intl, чтобы в EN было «Mon», а в RU «пн» */
export const WD_SHORT_MON = Array.from({ length: 7 }, (_, i) => new Date(2024, 0, 1 + ((i + 6) % 7))
  .toLocaleDateString(localeOf(), { weekday: 'short' }))

// ---------- формат ----------
/* Деньги: «1 500 ₽» в RU и «₽1,500» в EN — знак минус тот же (U+2212), как был. */
export const money = (x, opts = {}) => fmtMoney(x, opts)
export const moneyShort = (x) => fmtMoney(x, { compact: true })

/* Базовые форматы остаются на месте (их импортируют десятки мест), но текст и разделители
   теперь берутся из текущего языка: RU — «2 октября 2026», EN — «Oct 2, 2026». */
export const d = (s) => (s instanceof Date ? s : new Date(s))
export const isSameDay = (a, b) => d(a).toDateString() === d(b).toDateString()
export const hhmm = (s) => d(s).toLocaleTimeString(localeOf(), { hour: '2-digit', minute: '2-digit' })
export const isAllDay = (s) => { const x = d(s); return x.getHours() === 23 && x.getMinutes() === 59 }   // задача «на день» хранится как 23:59
export const dayLabel = (s) => {
  const x = d(s), now = new Date()
  const tmw = new Date(now); tmw.setDate(now.getDate() + 1)
  if (isSameDay(x, now)) return t('common.today_caps')
  if (isSameDay(x, tmw)) return t('common.tomorrow_caps')
  const diff = (new Date(x.toDateString()) - new Date(now.toDateString())) / 864e5
  if (diff > 0 && diff < 7) return x.toLocaleDateString(localeOf(), { weekday: 'long' })
  return fmtDate(x)
}
export const shortDate = (s) => {
  const x = d(s)
  return `${x.toLocaleDateString(localeOf(), { weekday: 'short' })} ${x.getDate()} ${x.toLocaleDateString(localeOf(), { month: 'short' }).replace(/\.$/, '')}`
}
export const fullDate = (s) => fmtDate(s)
export const toLocalISO = (date) => {
  const x = d(date); const p = (n) => String(n).padStart(2, '0')
  return `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}T${p(x.getHours())}:${p(x.getMinutes())}`
}
export const relTime = (s) => {
  const diff = (Date.now() - d(s)) / 1000
  if (diff < 60) return t('time.just_now')
  if (diff < 3600) return t('time.min_ago', { n: Math.floor(diff / 60) })
  if (diff < 86400) return t('time.hour_ago', { n: Math.floor(diff / 3600) })
  if (diff < 172800) return t('common.yesterday')
  return shortDate(s)
}
/* Русская плюрализация (день/дня/дней) — одна реализация на всё приложение, в lib/i18n.js */
export const plural = (n, one, few, many) => [one, few, many][pluralIndex(n, getLang())]

// Теги из API приходят строкой ("а,б") — приводим к массиву, чтобы .map не падал.
export const listOf = (v) => {
  if (Array.isArray(v)) return v
  if (typeof v === 'string') return v.split(',').map((s) => s.trim().replace(/^#/, '')).filter(Boolean)
  return []
}

export const parseNum = (v) => {
  if (v === '' || v == null) return NaN
  const n = Number(String(v).replace(/\s|\u00a0/g, '').replace(',', '.'))
  return Number.isFinite(n) ? n : NaN
}
export const fmtInput = (n) => (n == null || n === '' || Number.isNaN(Number(n)) ? '' : fmtNumber(Math.round(Number(n) * 100) / 100, { maximumFractionDigits: 2 }))

/* Месяцы через Intl: RU — «октября» (родительный), EN — «October» */
export const MONTHS = Array.from({ length: 12 }, (_, i) => new Date(2024, i, 1).toLocaleDateString(localeOf(), { month: 'long' }))
export const MONTHS_NOM = Array.from({ length: 12 }, (_, i) => new Date(2024, i, 1).toLocaleDateString(localeOf(), { month: 'long' }))

/* Цвета и иконки категорий: ключи — как в базе (русские), подпись для интерфейса переводит
   словарь t.cat_* в i18n.js (см. catLabel). */
export const CAT_COLORS = {
  'Еда': '#ff9f0a', 'Транспорт': '#0a84ff', 'Жильё': '#5e5ce6', 'Подписки': '#bf5af2', 'Здоровье': '#30d158',
  'Развлечения': '#ff375f', 'Одежда': '#64d2ff', 'Техника': '#ffd60a', 'Долги': '#ff453a', 'Другое': '#8e8e93',
  'Зарплата': '#30d158', 'Фриланс': '#64d2ff', 'Прочий доход': '#30d158',
}
export const catColor = (c) => CAT_COLORS[c] || '#8e8e93'
export const CAT_ICONS = { 'Еда': '🍔', 'Транспорт': '🚕', 'Жильё': '🏠', 'Подписки': '📱', 'Здоровье': '💊', 'Развлечения': '🎮', 'Одежда': '👕', 'Техника': '💻', 'Долги': '💳', 'Другое': '📦', 'Зарплата': '💰', 'Фриланс': '🧑‍💻', 'Прочий доход': '🎁' }
export const catIcon = (c) => CAT_ICONS[c] || '•'
/* Подпись категории для показа: EN переводит только «штучные» названия из БД,
   всё что ввёл сам пользователь — остаётся как есть. */
export const CAT_LABEL_KEYS = {
  'Еда': 'cat_food', 'Транспорт': 'cat_transport', 'Жильё': 'cat_housing', 'Подписки': 'cat_subscriptions',
  'Здоровье': 'cat_health', 'Развлечения': 'cat_fun', 'Одежда': 'cat_clothes', 'Техника': 'cat_tech',
  'Долги': 'cat_debts', 'Зарплата': 'cat_salary', 'Фриланс': 'cat_freelance', 'Прочий доход': 'cat_other_income',
}
export const catLabel = (c) => (CAT_LABEL_KEYS[c] ? t(CAT_LABEL_KEYS[c]) : c)

/* Подписи горячих клавиш под платформу: на маке ⌘/⌥, на Windows/Linux — Ctrl/Alt */
export const isMac = /Mac|iPhone|iPad|iPod/.test(navigator.platform || '') || /Mac OS X/.test(navigator.userAgent || '')
export const kb = (k) => (isMac ? `⌘${k}` : `Ctrl+${k}`)
export const kbAlt = (k) => (isMac ? `⌥${k}` : `Alt+${k}`)
export const kbShiftEnter = isMac ? '⇧↵' : 'Shift+↵'
