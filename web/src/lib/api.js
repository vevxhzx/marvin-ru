const BASE = ''

async function req(method, path, body) {
  const r = await fetch(BASE + path, {
    method,
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
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
  chat: (text) => req('POST', '/api/chat', { text, channel: 'web' }),
  chatHistory: (limit = 40) => req('GET', `/api/chat/history?limit=${limit}`),

  events: (start, end) => req('GET', `/api/events?${start ? `start=${start}` : ''}${end ? `&end=${end}` : ''}`),
  addEvent: (e) => req('POST', '/api/events', e),
  updateEvent: (id, e) => req('PUT', `/api/events/${id}`, e),
  delEvent: (id) => req('DELETE', `/api/events/${id}`),

  tasks: (all = false) => req('GET', `/api/tasks?all=${all}`),
  addTask: (t) => req('POST', '/api/tasks', t),
  doneTask: (id) => req('POST', `/api/tasks/${id}/done`),
  undoneTask: (id) => req('POST', `/api/tasks/${id}/undone`),
  delTask: (id) => req('DELETE', `/api/tasks/${id}`),

  finSummary: (days = 30) => req('GET', `/api/finance/summary?days=${days}`),
  finDaily: (days = 30) => req('GET', `/api/finance/daily?days=${days}`),
  txs: (days = 30) => req('GET', `/api/finance/transactions?days=${days}`),
  addTx: (t) => req('POST', '/api/finance/transactions', t),
  updateTx: (id, t) => req('PUT', `/api/finance/transactions/${id}`, t),
  delTx: (id) => req('DELETE', `/api/finance/transactions/${id}`),
  categories: () => req('GET', '/api/finance/categories'),
  accounts: () => req('GET', '/api/finance/accounts'),
  setBalance: (name, balance) => req('POST', '/api/finance/accounts/balance', { name, balance }),
  addAccount: (a) => req('POST', '/api/finance/accounts', a),
  updateAccount: (id, a) => req('PUT', `/api/finance/accounts/${id}`, a),
  delAccount: (id) => req('DELETE', `/api/finance/accounts/${id}`),
  debts: () => req('GET', '/api/finance/debts'),
  addDebt: (d) => req('POST', '/api/finance/debts', d),
  payDebt: (id, amount, extra = {}) => req('POST', `/api/finance/debts/${id}/pay`, { amount, ...extra }),
  debtPayments: (id) => req('GET', `/api/finance/debts/${id}/payments`),
  updateDebt: (id, d) => req('PUT', `/api/finance/debts/${id}`, d),
  delDebt: (id) => req('DELETE', `/api/finance/debts/${id}`),
  recurring: () => req('GET', '/api/finance/recurring'),
  addRecurring: (r) => req('POST', '/api/finance/recurring', r),
  updateRecurring: (id, r) => req('PUT', `/api/finance/recurring/${id}`, r),
  delRecurring: (id) => req('DELETE', `/api/finance/recurring/${id}`),

  notes: (q) => req('GET', `/api/notes${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  addNote: (text, tags = []) => req('POST', '/api/notes', { text, tags }),
  addNotePhoto: async (file, text = '') => {
    const fd = new FormData(); fd.append('file', file); fd.append('text', text)
    const r = await fetch(BASE + '/api/notes/photo', { method: 'POST', body: fd })
    if (!r.ok) { let msg = `фото → ${r.status}`; try { const j = await r.json(); if (j?.detail) msg = j.detail } catch {} throw new Error(msg) }
    return r.json()
  },
  delNote: (id) => req('DELETE', `/api/notes/${id}`),
  links: (q) => req('GET', `/api/links${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  addLink: (url, comment) => req('POST', '/api/links', { url, comment }),
  delLink: (id) => req('DELETE', `/api/links/${id}`),
  patchTask: (id, p) => req('PUT', `/api/tasks/${id}`, p),
  skipEvent: (id, date) => req('POST', `/api/events/${id}/skip`, { date }),
  undo: () => req('POST', '/api/undo'),
  budgets: () => req('GET', '/api/finance/budgets'),
  addCategory: (c) => req('POST', '/api/finance/categories', c),
  updateCategory: (id, c) => req('PUT', `/api/finance/categories/${id}`, c),
  delCategory: (id) => req('DELETE', `/api/finance/categories/${id}`),
  settings: () => req('GET', '/api/settings'),
  saveSettings: (changes) => req('PUT', '/api/settings', { changes }),
  status: () => req('GET', '/api/status'),
  backupNow: () => req('POST', '/api/backup'),
  semantic: (q, limit = 12) => req('GET', `/api/search/semantic?q=${encodeURIComponent(q)}&limit=${limit}`),
  reindex: () => req('POST', '/api/search/reindex'),
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

export const REPEAT_LABELS = { '': 'не повторять', daily: 'каждый день', weekly: 'каждую неделю', monthly: 'каждый месяц', yearly: 'каждый год' }
export const WD_SHORT_MON = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

// ---------- формат ----------
export const money = (x, opts = {}) => {
  const n = Math.round(Number(x) || 0)
  const s = Math.abs(n).toLocaleString('ru-RU')
  return `${n < 0 ? '−' : opts.plus && n > 0 ? '+' : ''}${s} ₽`
}
export const moneyShort = (x) => {
  const n = Number(x) || 0
  const a = Math.abs(n)
  const sign = n < 0 ? '−' : ''
  if (a >= 1_000_000) return `${sign}${(a / 1_000_000).toFixed(1).replace('.0', '')} млн`
  if (a >= 10_000) return `${sign}${Math.round(a / 1000)}к`
  if (a >= 1000) return `${sign}${(a / 1000).toFixed(1).replace('.0', '')}к`
  return `${sign}${a}`
}

const WD = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб']
const WD_FULL = ['Воскресенье', 'Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
export const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
export const MONTHS_NOM = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']

export const d = (s) => (s instanceof Date ? s : new Date(s))
export const isSameDay = (a, b) => d(a).toDateString() === d(b).toDateString()
export const hhmm = (s) => d(s).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
export const dayLabel = (s) => {
  const x = d(s), now = new Date()
  const t = new Date(now); t.setDate(now.getDate() + 1)
  if (isSameDay(x, now)) return 'Сегодня'
  if (isSameDay(x, t)) return 'Завтра'
  const diff = (new Date(x.toDateString()) - new Date(now.toDateString())) / 864e5
  if (diff > 0 && diff < 7) return `${WD_FULL[x.getDay()]}`
  return `${x.getDate()} ${MONTHS[x.getMonth()]}`
}
export const shortDate = (s) => { const x = d(s); return `${WD[x.getDay()]} ${x.getDate()} ${MONTHS[x.getMonth()].slice(0, 3)}` }
export const fullDate = (s) => { const x = d(s); return `${x.getDate()} ${MONTHS[x.getMonth()]} ${x.getFullYear()}` }
export const toLocalISO = (date) => {
  const x = d(date); const p = (n) => String(n).padStart(2, '0')
  return `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}T${p(x.getHours())}:${p(x.getMinutes())}`
}
export const relTime = (s) => {
  const diff = (Date.now() - d(s)) / 1000
  if (diff < 60) return 'только что'
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`
  if (diff < 172800) return 'вчера'
  return shortDate(s)
}
export const plural = (n, one, few, many) => { const a = Math.abs(n) % 100, b = a % 10; if (a > 10 && a < 20) return many; if (b > 1 && b < 5) return few; if (b === 1) return one; return many }

export const parseNum = (v) => {
  if (v === '' || v == null) return NaN
  const n = Number(String(v).replace(/\s|\u00a0/g, '').replace(',', '.'))
  return Number.isFinite(n) ? n : NaN
}
export const fmtInput = (n) => (n == null || n === '' || Number.isNaN(Number(n)) ? '' : Math.round(Number(n) * 100) / 100).toLocaleString('ru-RU')

export const CAT_COLORS = {
  'Еда': '#ff9f0a', 'Транспорт': '#0a84ff', 'Жильё': '#5e5ce6', 'Подписки': '#bf5af2', 'Здоровье': '#30d158',
  'Развлечения': '#ff375f', 'Одежда': '#64d2ff', 'Техника': '#ffd60a', 'Долги': '#ff453a', 'Другое': '#8e8e93',
  'Зарплата': '#30d158', 'Фриланс': '#64d2ff', 'Прочий доход': '#30d158',
}
export const catColor = (c) => CAT_COLORS[c] || '#8e8e93'
export const CAT_ICONS = { 'Еда': '🍔', 'Транспорт': '🚕', 'Жильё': '🏠', 'Подписки': '📱', 'Здоровье': '💊', 'Развлечения': '🎮', 'Одежда': '👕', 'Техника': '💻', 'Долги': '💳', 'Другое': '📦', 'Зарплата': '💰', 'Фриланс': '🧑‍💻', 'Прочий доход': '🎁' }
export const catIcon = (c) => CAT_ICONS[c] || '•'
