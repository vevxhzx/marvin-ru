import express from 'express'
import cors from 'cors'
import { createServer as createViteServer } from 'vite'
import path from 'path'
import fs from 'fs'

const isProd = process.env.NODE_ENV === 'production'
const PORT = Number(process.env.PORT) || 3000

const app = express()
app.use(cors())
app.use(express.json({ limit: '10mb' }))

// SSE connections
const sseClients: express.Response[] = []

function broadcast(kind: string, payload: Record<string, any> = {}) {
  const data = JSON.stringify({ kind, ...payload })
  for (const client of sseClients) {
    try {
      client.write(`data: ${data}\n\n`)
    } catch {}
  }
}

// In-Memory Database
const now = new Date()
const todayStr = now.toISOString().split('T')[0]

const state = {
  settings: [
    { key: 'owner.name', value: 'Сэр' },
    { key: 'owner.city', value: 'Москва' },
    { key: 'currency', value: '₽' },
    { key: 'freelance.hourly_rate', value: 2500 },
    { key: 'pomodoro.focus_min', value: 25 },
    { key: 'pomodoro.short_break_min', value: 5 },
    { key: 'pomodoro.long_break_min', value: 15 },
  ],
  tasks: [
    { id: 1, title: 'Подготовить отчёт за неделю', due: `${todayStr}T18:00:00`, priority: 2, done: 0, created_at: now.toISOString(), category: 'Работа' },
    { id: 2, title: 'Оплатить интернет и сервисы', due: `${todayStr}T23:59:00`, priority: 1, done: 0, created_at: now.toISOString(), category: 'Счета' },
    { id: 3, title: 'Забрать посылку из пункта выдачи', due: `${todayStr}T20:00:00`, priority: 0, done: 1, created_at: now.toISOString(), category: 'Личное' },
    { id: 4, title: 'Согласовать правки по сценарию ролика', due: `${todayStr}T16:30:00`, priority: 2, done: 0, created_at: now.toISOString(), category: 'Фриланс' },
  ],
  events: [
    { id: 1, title: 'Синхронизация с командой', start: `${todayStr}T11:00:00`, end: `${todayStr}T12:00:00`, duration_min: 60, location: 'Google Meet', notes: 'План на следующую неделю', remind_minutes: 15, repeat: 'weekly', repeat_days: [1], done: 0 },
    { id: 2, title: 'Встреча с клиентом (ролик)', start: `${todayStr}T15:00:00`, end: `${todayStr}T16:00:00`, duration_min: 60, location: 'Zoom', notes: 'Обсуждение раскадровки и тайминга', remind_minutes: 30, repeat: '', repeat_days: [], done: 0 },
  ],
  accounts: [
    { id: 1, name: 'Т-Банк Основной', balance: 142500, kind: 'card', currency: 'RUB' },
    { id: 2, name: 'Накопительный счёт', balance: 350000, kind: 'savings', currency: 'RUB' },
    { id: 3, name: 'Наличные', balance: 15000, kind: 'cash', currency: 'RUB' },
  ],
  categories: [
    { id: 1, name: 'Еда', kind: 'expense', icon: '🍔', budget: 35000, color: '#ff9f0a' },
    { id: 2, name: 'Транспорт', kind: 'expense', icon: '🚕', budget: 12000, color: '#0a84ff' },
    { id: 3, name: 'Жильё', kind: 'expense', icon: '🏠', budget: 45000, color: '#5e5ce6' },
    { id: 4, name: 'Подписки', kind: 'expense', icon: '📱', budget: 3000, color: '#bf5af2' },
    { id: 5, name: 'Зарплата', kind: 'income', icon: '💰', budget: 0, color: '#30d158' },
    { id: 6, name: 'Фриланс', kind: 'income', icon: '🧑‍💻', budget: 0, color: '#64d2ff' },
  ],
  transactions: [
    { id: 1, date: `${todayStr}T09:30:00`, amount: -450, category: 'Еда', account: 'Т-Банк Основной', comment: 'Кофе и круассан' },
    { id: 2, date: `${todayStr}T12:15:00`, amount: -780, category: 'Транспорт', account: 'Т-Банк Основной', comment: 'Такси до офиса' },
    { id: 3, date: `${todayStr}T14:00:00`, amount: 45000, category: 'Фриланс', account: 'Т-Банк Основной', comment: 'Аванс за ролик' },
    { id: 4, date: `${todayStr}T10:00:00`, amount: -2890, category: 'Еда', account: 'Т-Банк Основной', comment: 'Супермаркет' },
  ],
  debts: [
    { id: 1, name: 'Кредитная карта', total: 45000, paid: 15000, due_date: `${todayStr}`, monthly_payment: 10000, rate: 0, kind: 'owe_them' },
  ],
  recurring: [
    { id: 1, title: 'Яндекс Плюс', amount: 299, kind: 'expense', period: 'monthly', day_of_month: 15, category: 'Подписки', account: 'Т-Банк Основной', active: true },
    { id: 2, title: 'Аренда жилья', amount: 40000, kind: 'expense', period: 'monthly', day_of_month: 25, category: 'Жильё', account: 'Т-Банк Основной', active: true },
  ],
  goals: [
    { id: 1, name: 'Финансовая подушка 500к', target: 500000, current: 350000, due_date: '2026-12-31', color: '#30d158', icon: '🛡️' },
    { id: 2, name: 'Новый ноутбук для монтажа', target: 180000, current: 95000, due_date: '2026-11-15', color: '#64d2ff', icon: '💻' },
  ],
  orders: [
    {
      id: 1,
      title: 'Анимационный ролик 60с',
      client: 'ООО МедиаГрупп',
      status: 'work',
      total: 75000,
      paid: 45000,
      left: 30000,
      deadline: `${todayStr}T20:00:00`,
      created_at: now.toISOString(),
      notes: 'Готова раскадровка, делаем чистовой рендер. Обещали чистовой рендер к 20:00.',
      hourly_rate: 3000,
      hours: 5.7,
      estimate_h: 5.0,
      time_entries: [
        { id: 101, tool: 'Premiere Pro', duration_min: 200, note: 'Монтаж таймлайна и синхронизация звука', date: `${todayStr}T11:00:00` },
        { id: 102, tool: 'After Effects', duration_min: 72, note: 'Анимация титров и плашек', date: `${todayStr}T15:00:00` },
        { id: 103, tool: 'Правки вручную', duration_min: 40, note: 'Цветокоррекция и уровни', date: `${todayStr}T17:00:00` },
        { id: 104, tool: 'Созвон', duration_min: 30, note: 'Утверждение правок с арт-директором', date: `${todayStr}T14:30:00` },
      ],
    },
    {
      id: 2,
      title: 'Фирменный стиль и баннеры',
      client: 'Кофейня Уют',
      status: 'review',
      total: 35000,
      paid: 35000,
      left: 0,
      deadline: `${todayStr}T18:00:00`,
      created_at: now.toISOString(),
      notes: 'Ждём финального аппрува макетов',
      hourly_rate: 2500,
      hours: 12.0,
      estimate_h: 14.0,
      time_entries: [
        { id: 201, tool: 'Photoshop / Illustrator', duration_min: 360, note: 'Разработка логотипа и гайдлайна', date: `${todayStr}T10:00:00` },
        { id: 202, tool: 'Правки вручную', duration_min: 120, note: 'Подготовка к печати', date: `${todayStr}T16:00:00` },
      ],
    },
  ],
  clients: [
    { id: 1, name: 'ООО МедиаГрупп', email: 'media@group.ru', phone: '+7 999 123-45-67', telegram: '@mediagroup', note: 'Постоянный клиент, видеопроизводство', total_orders: 4, total_paid: 240000 },
    { id: 2, name: 'Кофейня Уют', email: 'info@cozy.ru', phone: '+7 999 876-54-32', telegram: '@cozy_coffee', note: 'Локальная сеть кофеен', total_orders: 2, total_paid: 65000 },
  ],
  timer: {
    active: false,
    order_id: null as number | null,
    order: null as string | null,
    kind: 'focus',
    focus_min: 25,
    planned_min: 25,
    start_time: null as string | null,
    ends_at: null as string | null,
    today_sessions: 3,
  },
  people: [
    { id: 1, name: 'кот прод', aliases: 'kotprod', kind: 'company', open: 2, unpaid: 10300, note: 'Студия видеопродакшна', contact: '@kotprod', tags: ['клиент', 'монтаж'], birthday: null, last_seen: now.toISOString() },
    { id: 2, name: 'илья (монтажер скаммерса)', aliases: '', kind: 'client', open: 1, unpaid: 500, note: 'Монтаж и анимация для YouTube', contact: '@ilya_scam', tags: ['фриланс'], birthday: null, last_seen: now.toISOString() },
    { id: 3, name: 'камилла', aliases: '', kind: 'friend', open: 0, unpaid: 0, note: 'Подруга', contact: '@kamilla', tags: ['дизайн', 'кофе'], birthday: '1998-04-12', last_seen: now.toISOString() },
    { id: 4, name: 'Кирилл', aliases: '', kind: 'person', open: 0, unpaid: 0, note: 'Арендатор / квартира', contact: '+7 999 555-44-33', tags: ['квартира', 'аренда'], birthday: null, last_seen: now.toISOString() },
    { id: 5, name: 'Мама', aliases: 'она же Наталия', kind: 'family', open: 0, unpaid: 0, note: 'День рождения 18 мая', contact: '+7 916 123-45-67', tags: ['семья'], birthday: '1972-05-18', last_seen: now.toISOString() },
    { id: 6, name: 'папа', aliases: 'он же андрей', kind: 'family', open: 0, unpaid: 0, note: 'День рождения 3 сентября', contact: '+7 916 765-43-21', tags: ['семья'], birthday: '1969-09-03', last_seen: now.toISOString() },
    { id: 7, name: 'Дмитрий Соколов', aliases: 'Дима', kind: 'colleague', open: 0, unpaid: 0, note: 'Арт-директор в агентстве', contact: '@sokolov_art', tags: ['коллега', '3d'], birthday: '1992-10-14', last_seen: now.toISOString() },
    { id: 8, name: 'Анна Васильева', aliases: '', kind: 'client', open: 0, unpaid: 0, note: 'Продюсер проектов', contact: '+7 900 111-22-33', tags: ['клиент', 'реклама'], birthday: '1995-05-20', last_seen: now.toISOString() },
  ],
  notes: [
    { id: 1, text: 'Идея для серии обучающих роликов по моушн-дизайну и автоматизации рутины', tags: ['идеи', 'ютуб', 'дизайн'], created_at: now.toISOString(), updated_at: now.toISOString() },
    { id: 2, text: 'Полезные горячие клавиши: Ctrl+K открывает палитру команд, Ctrl+J открывает чат ассистента', tags: ['советы', 'система'], created_at: now.toISOString(), updated_at: now.toISOString() },
  ],
  links: [
    { id: 1, url: 'https://news.ycombinator.com', title: 'Hacker News', domain: 'news.ycombinator.com', comment: 'Технологические новости', created_at: now.toISOString() },
    { id: 2, url: 'https://github.com', title: 'GitHub', domain: 'github.com', comment: 'Репозитории и код', created_at: now.toISOString() },
  ],
  facts: [
    { id: 1, text: 'Предпочитает работать интервалами помодоро по 25 минут', layer: 'work', created_at: now.toISOString(), active: true },
    { id: 2, text: 'Основной доход — видеопроизводство и моушн-дизайн', layer: 'finance', created_at: now.toISOString(), active: true },
  ],
  boards: [
    {
      id: 1,
      title: 'Раскадровка ролика 60с',
      kind: 'storyboard',
      archived: false,
      cover: null,
      order_id: 1,
      revision: 1,
      view: { x: 100, y: 100, k: 1 },
      items: [
        { id: 1, type: 'frame', x: 80, y: 100, w: 320, h: 234, z: 0, rot: 0, data: { n: 1, seconds: 5, label: 'Сцена 1: Вступление и общий план', ratio: '16:9' } },
        { id: 2, type: 'frame', x: 440, y: 100, w: 320, h: 234, z: 1, rot: 0, data: { n: 2, seconds: 8, label: 'Сцена 2: Появление главного персонажа', ratio: '16:9' } },
        { id: 3, type: 'sticky', x: 80, y: 380, w: 200, h: 200, z: 2, rot: 0, data: { text: 'Динамичный саундтрек с нарастанием', color: 'yellow' } },
      ],
    },
  ],
  chatHistory: [
    { id: 1, role: 'assistant', text: 'Добрый день, сэр. Я готов к работе. Что запланировано на сегодня?', timestamp: now.toISOString(), actions: [], via: 'rule' },
  ],
  pomodoroConfig: {
    focus_min: 25,
    short_break_min: 5,
    long_break_min: 15,
  },
  freelanceConfig: {
    enabled: true,
    hourly_rate: 2500,
    late_nudge: true,
  },
}

let nextId = 100

// Helper to convert task to event
function taskAsEvent(t: any) {
  const d = new Date(t.due)
  const allDay = d.getHours() === 23 && d.getMinutes() === 59
  const end = allDay ? t.due : new Date(d.getTime() + 30 * 60000).toISOString()
  return {
    id: -t.id,
    task_id: t.id,
    kind: 'task',
    title: t.title,
    start: t.due,
    end,
    duration_min: allDay ? 0 : 30,
    location: null,
    notes: null,
    repeat: '',
    repeat_label: '',
    repeat_anchor: t.due,
    done: Boolean(t.done),
    priority: t.priority || 0,
    all_day: allDay,
  }
}

// ----------------- API ROUTES -----------------

// Live SSE Stream
app.get('/api/events/stream', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')
  res.flushHeaders()

  sseClients.push(res)
  res.write('retry: 3000\n\n')

  const pingInterval = setInterval(() => {
    try {
      res.write(': ping\n\n')
    } catch {}
  }, 20000)

  req.on('close', () => {
    clearInterval(pingInterval)
    const idx = sseClients.indexOf(res)
    if (idx !== -1) sseClients.splice(idx, 1)
  })
})

let currentEdition = process.env.EDITION === 'marvin' ? 'marvin' : 'jarvis'

// Health
app.get('/api/health', (req, res) => {
  const isMarvin = currentEdition === 'marvin'
  res.json({
    ok: true,
    ollama: false,
    mode: 'local',
    time: new Date().toISOString(),
    version: '1.0.0',
    edition: currentEdition,
    name: isMarvin ? 'Марвин' : 'Джарвис',
    name_latin: isMarvin ? 'Marvin' : 'Jarvis',
  })
})

// Edition Management
app.get('/api/edition', (req, res) => {
  const isMarvin = currentEdition === 'marvin'
  res.json({
    edition: currentEdition,
    name: isMarvin ? 'Марвин' : 'Джарвис',
    name_latin: isMarvin ? 'Marvin' : 'Jarvis',
    is_marvin: isMarvin,
    is_jarvis: !isMarvin,
  })
})

app.post('/api/edition', (req, res) => {
  const { edition } = req.body
  if (edition === 'marvin' || edition === 'jarvis') {
    currentEdition = edition
    broadcast('state')
  }
  const isMarvin = currentEdition === 'marvin'
  res.json({
    edition: currentEdition,
    name: isMarvin ? 'Марвин' : 'Джарвис',
    name_latin: isMarvin ? 'Marvin' : 'Jarvis',
    is_marvin: isMarvin,
    is_jarvis: !isMarvin,
  })
})

// Status & State
app.get('/api/status', (req, res) => res.json({ ok: true, db: 'ok', uptime: process.uptime() }))
app.get('/api/state', (req, res) => {
  res.json({
    presence: 'active',
    presence_min: 25,
    session_min: 45,
    app: 'Браузер',
    cat: 'браузер',
    act_min: 15,
    budget_left: 5,
    deferred: 0,
    jobs: [],
  })
})
app.get('/api/pc/state', (req, res) => {
  res.json({
    alive: false,
    mode: 'idle',
    text: '',
  })
})
app.post('/api/pc/ack', (req, res) => res.json({ ok: true }))
app.post('/api/pc/result', (req, res) => res.json({ ok: true }))
app.post('/api/pc/clipboard', (req, res) => res.json({ ok: true, text: 'Сохранено' }))

// Dashboard
app.get('/api/dashboard', (req, res) => {
  const balance = state.accounts.reduce((acc, a) => acc + (a.balance || 0), 0)
  const income_month = state.transactions.filter(t => t.amount > 0).reduce((acc, t) => acc + t.amount, 0)
  const expense_month = Math.abs(state.transactions.filter(t => t.amount < 0).reduce((acc, t) => acc + t.amount, 0))

  const finSummary = {
    balance,
    income_month,
    expense_month,
    cashflow: income_month - expense_month,
    runway_days: 180,
    accounts: state.accounts,
  }

  const openOrders = state.orders.filter(o => ['new', 'work', 'review'].includes(o.status))
  const unpaid = state.orders.filter(o => o.status !== 'paid' && o.status !== 'cancelled').reduce((acc, o) => acc + o.left, 0)

  const heatmap = Array.from({ length: 26 }, (_, i) => ({
    week: i,
    count: Math.floor(Math.sin(i * 0.4) * 5 + 6),
  }))

  const forecast = Array.from({ length: 30 }, (_, i) => {
    const d = new Date()
    d.setDate(d.getDate() + i)
    return {
      date: d.toISOString().split('T')[0],
      balance: balance + i * 200 - (i % 7 === 0 ? 5000 : 0),
    }
  })

  res.json({
    today: state.events,
    week: state.events,
    tasks: state.tasks.filter(t => !t.done).slice(0, 10),
    finance: finSummary,
    debts: state.debts.map(d => ({ ...d, months_left: Math.ceil((d.total - d.paid) / (d.monthly_payment || 10000)) })),
    upcoming: state.recurring.slice(0, 5),
    memory: state.notes.slice(0, 6).map(n => ({ id: n.id, text: n.text, tags: n.tags, created_at: n.created_at })),
    digest: `Доброе утро, сэр. На сегодня запланировано ${state.events.length} событий и ${state.tasks.filter(t => !t.done).length} невыполненных задач. Баланс составляет ${balance.toLocaleString('ru-RU')} ₽.`,
    streak: { current: 14, max: 28, heatmap },
    birthdays: state.people.filter(p => p.birthday).map(p => ({ id: p.id, name: p.name, birthday: p.birthday, days_left: 12 })),
    forecast,
    pc: { alive: true, idle: false },
    timer: state.timer,
    orders: {
      open: openOrders.slice(0, 5),
      unpaid,
      expected: 75000,
      late: [],
    },
    freelance: state.freelanceConfig.enabled,
    screen_time: true,
    goals: state.goals.slice(0, 4),
    runway: 180,
    payments: [],
  })
})

// Focus
app.get('/api/focus', (req, res) => {
  res.json({
    aims: [
      { id: 1, title: 'Завершить ролик для клиента', done: false, target_date: todayStr },
      { id: 2, title: 'Пробежка 5 км', done: true, target_date: todayStr },
    ],
  })
})

// Events (Calendar)
app.get('/api/events', (req, res) => {
  const { tasks_too } = req.query
  let list = [...state.events]
  if (tasks_too === 'true') {
    const taskEvents = state.tasks.map(taskAsEvent)
    list = [...list, ...taskEvents]
  }
  res.json(list)
})

app.post('/api/events', (req, res) => {
  const ev = { id: ++nextId, ...req.body, done: 0 }
  state.events.push(ev)
  broadcast('events')
  res.json(ev)
})

app.put('/api/events/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.events.findIndex(e => e.id === id)
  if (idx !== -1) {
    state.events[idx] = { ...state.events[idx], ...req.body }
    broadcast('events')
    return res.json(state.events[idx])
  }
  res.status(404).json({ error: 'Event not found' })
})

app.delete('/api/events/:id', (req, res) => {
  const id = Number(req.params.id)
  state.events = state.events.filter(e => e.id !== id)
  broadcast('events')
  res.json({ ok: true })
})

app.post('/api/events/:id/done', (req, res) => {
  const id = Number(req.params.id)
  const ev = state.events.find(e => e.id === id)
  if (ev) {
    ev.done = req.body.done ? 1 : 0
    broadcast('events')
  }
  res.json({ ok: true })
})

app.post('/api/events/:id/skip', (req, res) => {
  res.json({ ok: true })
})

// Tasks
app.get('/api/tasks', (req, res) => {
  const { all, events_too } = req.query
  let list = all === 'true' ? [...state.tasks] : state.tasks.filter(t => !t.done)
  if (events_too === 'true') {
    const evTasks = state.events.map(e => ({
      id: -e.id,
      title: e.title,
      due: e.start,
      priority: 1,
      done: e.done,
      category: 'Календарь',
      kind: 'event',
    }))
    list = [...list, ...evTasks]
  }
  res.json(list)
})

app.get('/api/tasks/:id', (req, res) => {
  const id = Number(req.params.id)
  const t = state.tasks.find(x => x.id === id)
  if (t) return res.json(t)
  res.status(404).json({ error: 'Task not found' })
})

app.post('/api/tasks', (req, res) => {
  const t = { id: ++nextId, created_at: new Date().toISOString(), done: 0, priority: 0, ...req.body }
  state.tasks.push(t)
  broadcast('tasks')
  res.json(t)
})

app.put('/api/tasks/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.tasks.findIndex(t => t.id === id)
  if (idx !== -1) {
    state.tasks[idx] = { ...state.tasks[idx], ...req.body }
    broadcast('tasks')
    return res.json(state.tasks[idx])
  }
  res.status(404).json({ error: 'Task not found' })
})

app.post('/api/tasks/:id/done', (req, res) => {
  const id = Number(req.params.id)
  const t = state.tasks.find(x => x.id === id)
  if (t) {
    t.done = 1
    broadcast('tasks')
  }
  res.json({ ok: true })
})

app.post('/api/tasks/:id/undone', (req, res) => {
  const id = Number(req.params.id)
  const t = state.tasks.find(x => x.id === id)
  if (t) {
    t.done = 0
    broadcast('tasks')
  }
  res.json({ ok: true })
})

app.delete('/api/tasks/:id', (req, res) => {
  const id = Number(req.params.id)
  state.tasks = state.tasks.filter(t => t.id !== id)
  broadcast('tasks')
  res.json({ ok: true })
})

// Finance
app.get('/api/finance/summary', (req, res) => {
  const balance = state.accounts.reduce((acc, a) => acc + (a.balance || 0), 0)
  const income_month = state.transactions.filter(t => t.amount > 0).reduce((acc, t) => acc + t.amount, 0)
  const expense_month = Math.abs(state.transactions.filter(t => t.amount < 0).reduce((acc, t) => acc + t.amount, 0))
  res.json({
    balance,
    income_month,
    expense_month,
    cashflow: income_month - expense_month,
    runway_days: 180,
    accounts: state.accounts,
  })
})

app.get('/api/finance/daily', (req, res) => {
  const days = Number(req.query.days) || 30
  const list = []
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const ds = d.toISOString().split('T')[0]
    list.push({
      date: ds,
      expense: Math.floor(Math.random() * 2500 + 400),
      income: i === 5 || i === 20 ? 45000 : 0,
    })
  }
  res.json(list)
})

app.get('/api/finance/transactions', (req, res) => {
  res.json(state.transactions)
})

app.post('/api/finance/transactions', (req, res) => {
  const tx = { id: ++nextId, date: new Date().toISOString(), ...req.body }
  state.transactions.unshift(tx)
  // Update account balance
  const acc = state.accounts.find(a => a.name === tx.account) || state.accounts[0]
  if (acc) acc.balance = (acc.balance || 0) + Number(tx.amount)
  broadcast('finance')
  res.json(tx)
})

app.put('/api/finance/transactions/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.transactions.findIndex(t => t.id === id)
  if (idx !== -1) {
    state.transactions[idx] = { ...state.transactions[idx], ...req.body }
    broadcast('finance')
    return res.json(state.transactions[idx])
  }
  res.status(404).json({ error: 'Transaction not found' })
})

app.delete('/api/finance/transactions/:id', (req, res) => {
  const id = Number(req.params.id)
  state.transactions = state.transactions.filter(t => t.id !== id)
  broadcast('finance')
  res.json({ ok: true })
})

app.get('/api/finance/categories', (req, res) => res.json(state.categories))
app.post('/api/finance/categories', (req, res) => {
  const c = { id: ++nextId, ...req.body }
  state.categories.push(c)
  broadcast('finance')
  res.json(c)
})
app.put('/api/finance/categories/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.categories.findIndex(c => c.id === id)
  if (idx !== -1) {
    state.categories[idx] = { ...state.categories[idx], ...req.body }
    broadcast('finance')
    return res.json(state.categories[idx])
  }
  res.status(404).json({ error: 'Category not found' })
})
app.delete('/api/finance/categories/:id', (req, res) => {
  const id = Number(req.params.id)
  state.categories = state.categories.filter(c => c.id !== id)
  broadcast('finance')
  res.json({ ok: true })
})

app.get('/api/finance/accounts', (req, res) => res.json(state.accounts))
app.post('/api/finance/accounts', (req, res) => {
  const a = { id: ++nextId, ...req.body }
  state.accounts.push(a)
  broadcast('finance')
  res.json(a)
})
app.put('/api/finance/accounts/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.accounts.findIndex(a => a.id === id)
  if (idx !== -1) {
    state.accounts[idx] = { ...state.accounts[idx], ...req.body }
    broadcast('finance')
    return res.json(state.accounts[idx])
  }
  res.status(404).json({ error: 'Account not found' })
})
app.delete('/api/finance/accounts/:id', (req, res) => {
  const id = Number(req.params.id)
  state.accounts = state.accounts.filter(a => a.id !== id)
  broadcast('finance')
  res.json({ ok: true })
})
app.post('/api/finance/accounts/balance', (req, res) => {
  const { name, balance } = req.body
  const a = state.accounts.find(x => x.name === name)
  if (a) {
    a.balance = Number(balance)
    broadcast('finance')
  }
  res.json({ ok: true })
})

app.get('/api/finance/debts', (req, res) => res.json(state.debts))
app.post('/api/finance/debts', (req, res) => {
  const d = { id: ++nextId, paid: 0, ...req.body }
  state.debts.push(d)
  broadcast('finance')
  res.json(d)
})
app.put('/api/finance/debts/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.debts.findIndex(d => d.id === id)
  if (idx !== -1) {
    state.debts[idx] = { ...state.debts[idx], ...req.body }
    broadcast('finance')
    return res.json(state.debts[idx])
  }
  res.status(404).json({ error: 'Debt not found' })
})
app.delete('/api/finance/debts/:id', (req, res) => {
  const id = Number(req.params.id)
  state.debts = state.debts.filter(d => d.id !== id)
  broadcast('finance')
  res.json({ ok: true })
})
app.post('/api/finance/debts/:id/pay', (req, res) => {
  const id = Number(req.params.id)
  const d = state.debts.find(x => x.id === id)
  if (d) {
    d.paid = (d.paid || 0) + Number(req.body.amount || 0)
    broadcast('finance')
  }
  res.json({ ok: true })
})
app.get('/api/finance/debts/:id/payments', (req, res) => res.json([]))

app.get('/api/finance/recurring', (req, res) => res.json(state.recurring))
app.post('/api/finance/recurring', (req, res) => {
  const r = { id: ++nextId, active: true, ...req.body }
  state.recurring.push(r)
  broadcast('finance')
  res.json(r)
})
app.put('/api/finance/recurring/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.recurring.findIndex(r => r.id === id)
  if (idx !== -1) {
    state.recurring[idx] = { ...state.recurring[idx], ...req.body }
    broadcast('finance')
    return res.json(state.recurring[idx])
  }
  res.status(404).json({ error: 'Recurring not found' })
})
app.delete('/api/finance/recurring/:id', (req, res) => {
  const id = Number(req.params.id)
  state.recurring = state.recurring.filter(r => r.id !== id)
  broadcast('finance')
  res.json({ ok: true })
})

app.get('/api/finance/goals', (req, res) => res.json(state.goals))
app.post('/api/finance/goals', (req, res) => {
  const g = { id: ++nextId, current: 0, ...req.body }
  state.goals.push(g)
  broadcast('finance')
  res.json(g)
})
app.put('/api/finance/goals/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.goals.findIndex(g => g.id === id)
  if (idx !== -1) {
    state.goals[idx] = { ...state.goals[idx], ...req.body }
    broadcast('finance')
    return res.json(state.goals[idx])
  }
  res.status(404).json({ error: 'Goal not found' })
})
app.delete('/api/finance/goals/:id', (req, res) => {
  const id = Number(req.params.id)
  state.goals = state.goals.filter(g => g.id !== id)
  broadcast('finance')
  res.json({ ok: true })
})
app.post('/api/finance/goals/:id/put', (req, res) => {
  const id = Number(req.params.id)
  const g = state.goals.find(x => x.id === id)
  if (g) {
    g.current = (g.current || 0) + Number(req.body.amount || 0)
    broadcast('finance')
  }
  res.json({ ok: true })
})
app.get('/api/finance/budgets', (req, res) => res.json([]))
app.get('/api/finance/techniques', (req, res) => res.json({ '50_30_20': { needs: 50, wants: 30, savings: 20 } }))

// Notes & Links (Brain)
app.get('/api/notes', (req, res) => {
  const q = String(req.query.q || '').toLowerCase()
  if (!q) return res.json(state.notes)
  res.json(state.notes.filter(n => n.text.toLowerCase().includes(q) || n.tags?.some((t: string) => t.toLowerCase().includes(q))))
})
app.post('/api/notes', (req, res) => {
  const note = { id: ++nextId, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), tags: [], ...req.body }
  state.notes.unshift(note)
  broadcast('notes')
  res.json(note)
})
app.put('/api/notes/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.notes.findIndex(n => n.id === id)
  if (idx !== -1) {
    state.notes[idx] = { ...state.notes[idx], ...req.body, updated_at: new Date().toISOString() }
    broadcast('notes')
    return res.json(state.notes[idx])
  }
  res.status(404).json({ error: 'Note not found' })
})
app.delete('/api/notes/:id', (req, res) => {
  const id = Number(req.params.id)
  state.notes = state.notes.filter(n => n.id !== id)
  broadcast('notes')
  res.json({ ok: true })
})
app.post('/api/notes/photo', (req, res) => res.json({ ok: true, id: ++nextId }))

app.get('/api/links', (req, res) => {
  const q = String(req.query.q || '').toLowerCase()
  if (!q) return res.json(state.links)
  res.json(state.links.filter(l => l.title?.toLowerCase().includes(q) || l.url.toLowerCase().includes(q) || l.comment?.toLowerCase().includes(q)))
})
app.post('/api/links', (req, res) => {
  const url = req.body.url || ''
  let domain = ''
  try { domain = new URL(url).hostname } catch {}
  const link = { id: ++nextId, title: domain || url, domain, created_at: new Date().toISOString(), ...req.body }
  state.links.unshift(link)
  broadcast('links')
  res.json(link)
})
app.put('/api/links/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.links.findIndex(l => l.id === id)
  if (idx !== -1) {
    state.links[idx] = { ...state.links[idx], ...req.body }
    broadcast('links')
    return res.json(state.links[idx])
  }
  res.status(404).json({ error: 'Link not found' })
})
app.delete('/api/links/:id', (req, res) => {
  const id = Number(req.params.id)
  state.links = state.links.filter(l => l.id !== id)
  broadcast('links')
  res.json({ ok: true })
})

// Orders & Freelance
app.get('/api/orders', (req, res) => res.json(state.orders))
app.get('/api/orders/clients', (req, res) => res.json(state.clients))
app.put('/api/orders/clients/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.clients.findIndex(c => c.id === id)
  if (idx !== -1) {
    state.clients[idx] = { ...state.clients[idx], ...req.body }
    return res.json(state.clients[idx])
  }
  res.status(404).json({ error: 'Client not found' })
})
app.delete('/api/orders/clients/:id', (req, res) => {
  const id = Number(req.params.id)
  state.clients = state.clients.filter(c => c.id !== id)
  res.json({ ok: true })
})

app.get('/api/orders/timer', (req, res) => res.json(state.timer))
app.post('/api/orders/timer', (req, res) => {
  const { order_id, minutes, kind } = req.body
  const order = state.orders.find(o => o.id === order_id)?.title || null
  const planned = Number(minutes) || state.pomodoroConfig?.focus_min || 25
  const startTime = new Date()
  const endsAt = new Date(startTime.getTime() + planned * 60 * 1000)
  state.timer = {
    ...state.timer,
    active: true,
    order_id: order_id || null,
    order,
    kind: kind || 'focus',
    planned_min: planned,
    start_time: startTime.toISOString(),
    ends_at: endsAt.toISOString(),
  }
  broadcast('timer')
  res.json(state.timer)
})
app.delete('/api/orders/timer', (req, res) => {
  if (state.timer.active) state.timer.today_sessions++
  state.timer.active = false
  state.timer.ends_at = null
  state.timer.start_time = null
  broadcast('timer')
  res.json(state.timer)
})
app.get('/api/orders/pomodoro', (req, res) => res.json(state.pomodoroConfig))
app.put('/api/orders/pomodoro', (req, res) => {
  state.pomodoroConfig = { ...state.pomodoroConfig, ...req.body }
  res.json(state.pomodoroConfig)
})
app.get('/api/orders/freelance', (req, res) => res.json(state.freelanceConfig))
app.put('/api/orders/freelance', (req, res) => {
  state.freelanceConfig = { ...state.freelanceConfig, ...req.body }
  res.json(state.freelanceConfig)
})
app.get('/api/orders/pulse', (req, res) => res.json({ alive: true, active_hours: 4.8 }))
app.get('/api/orders/stats', (req, res) => {
  res.json({
    months: [
      { month: 'Июль', total: 65000 },
      { month: 'Август', total: 95000 },
      { month: 'Сентябрь', total: 80000 },
    ],
  })
})
app.get('/api/orders/:id', (req, res) => {
  const id = Number(req.params.id)
  const o = state.orders.find(x => x.id === id)
  if (o) return res.json(o)
  res.status(404).json({ error: 'Order not found' })
})
app.post('/api/orders', (req, res) => {
  const o = {
    id: ++nextId,
    created_at: new Date().toISOString(),
    status: 'new',
    paid: 0,
    left: Number(req.body.total || 0),
    ...req.body,
  }
  state.orders.unshift(o)
  broadcast('orders')
  res.json(o)
})
app.put('/api/orders/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.orders.findIndex(o => o.id === id)
  if (idx !== -1) {
    state.orders[idx] = { ...state.orders[idx], ...req.body }
    if (req.body.total != null || req.body.paid != null) {
      state.orders[idx].left = Math.max(0, state.orders[idx].total - (state.orders[idx].paid || 0))
    }
    broadcast('orders')
    return res.json(state.orders[idx])
  }
  res.status(404).json({ error: 'Order not found' })
})
app.delete('/api/orders/:id', (req, res) => {
  const id = Number(req.params.id)
  state.orders = state.orders.filter(o => o.id !== id)
  broadcast('orders')
  res.json({ ok: true })
})
app.post('/api/orders/:id/payments', (req, res) => {
  const id = Number(req.params.id)
  const o = state.orders.find(x => x.id === id)
  if (o) {
    const amt = Number(req.body.amount || 0)
    o.paid = (o.paid || 0) + amt
    o.left = Math.max(0, o.total - o.paid)
    if (o.left === 0) o.status = 'paid'
    // Log as transaction too
    state.transactions.unshift({
      id: ++nextId,
      date: new Date().toISOString(),
      amount: amt,
      category: 'Фриланс',
      account: 'Т-Банк Основной',
      comment: `Оплата по заказу «${o.title}»`,
    })
    broadcast('orders')
    broadcast('finance')
  }
  res.json({ ok: true })
})

// Orders Time Tracking & Sessions (Premiere Pro, After Effects, Manual)
app.get('/api/orders/:id/time', (req, res) => {
  const id = Number(req.params.id)
  const o = state.orders.find(x => x.id === id)
  if (!o) return res.status(404).json({ error: 'Order not found' })
  res.json(o.time_entries || [])
})

app.post('/api/orders/:id/time', (req, res) => {
  const id = Number(req.params.id)
  const o = state.orders.find(x => x.id === id)
  if (!o) return res.status(404).json({ error: 'Order not found' })

  const min = Number(req.body.minutes) || Number(req.body.duration_min) || 0
  if (min <= 0) return res.status(422).json({ error: 'Minutes must be greater than 0' })

  if (!o.time_entries) o.time_entries = []
  const entry = {
    id: ++nextId,
    tool: req.body.tool || 'Ручная работа',
    duration_min: min,
    note: req.body.note || '',
    date: req.body.date || new Date().toISOString(),
    status: 'confirmed',
    source: 'manual'
  }
  o.time_entries.unshift(entry)
  const totalMin = o.time_entries.reduce((acc: number, e: any) => acc + (Number(e.duration_min) || 0), 0)
  o.hours = Math.round((totalMin / 60) * 10) / 10
  broadcast('orders')
  res.json({ session: entry, order: o, ...entry })
})

app.post('/api/orders/:id/time/from-screen', (req, res) => {
  const id = Number(req.params.id)
  const o = state.orders.find(x => x.id === id)
  if (!o) return res.status(404).json({ error: 'Order not found' })

  const min = Number(req.body.minutes) || 30
  if (!o.time_entries) o.time_entries = []
  const entry = {
    id: ++nextId,
    tool: req.body.app || 'Premiere Pro',
    duration_min: min,
    note: req.body.project || 'Автоучёт за ПК',
    date: new Date().toISOString(),
    status: 'confirmed',
    source: 'screen'
  }
  o.time_entries.unshift(entry)
  const totalMin = o.time_entries.reduce((acc: number, e: any) => acc + (Number(e.duration_min) || 0), 0)
  o.hours = Math.round((totalMin / 60) * 10) / 10
  broadcast('orders')
  res.json({ session: entry, order: o, ...entry })
})

app.delete('/api/orders/:id/time/:timeId', (req, res) => {
  const id = Number(req.params.id)
  const timeId = Number(req.params.timeId)
  const o = state.orders.find(x => x.id === id)
  if (!o) return res.status(404).json({ error: 'Order not found' })

  o.time_entries = (o.time_entries || []).filter((e: any) => e.id !== timeId)
  const totalMin = (o.time_entries || []).reduce((acc: number, e: any) => acc + (Number(e.duration_min) || 0), 0)
  o.hours = Math.round((totalMin / 60) * 10) / 10
  broadcast('orders')
  res.json({ ok: true })
})

// Desktop Client Info
app.get('/api/client/info', (req, res) => {
  res.json({
    app_name: 'Джарвис',
    version: '1.0.0',
    platform: process.platform,
    mode: 'desktop_projection',
    single_instance: true,
    tray_enabled: true,
    webview2_ready: true,
    autostart: true,
    port: PORT,
  })
})

// Direct download of the full complete archive
app.get('/api/download/jarvis.zip', (req, res) => {
  const zipPath = path.resolve(process.cwd(), 'jarvis-complete.zip')
  if (fs.existsSync(zipPath)) {
    res.download(zipPath, 'jarvis-complete.zip')
  } else {
    res.status(404).send('Архив не найден')
  }
})

app.get('/api/download/marvin.zip', (req, res) => {
  const zipPath = path.resolve(process.cwd(), 'github-marvin.zip')
  if (fs.existsSync(zipPath)) {
    res.download(zipPath, 'github-marvin.zip')
  } else {
    res.status(404).send('Архив Марвина не найден')
  }
})

// People & Graph
app.get('/api/people', (req, res) => res.json(state.people))
app.get('/api/people/kinds', (req, res) => res.json(['клиент', 'коллега', 'друг', 'семья']))
app.delete('/api/people/kinds/:k', (req, res) => res.json({ ok: true }))
app.get('/api/people/today', (req, res) => res.json([]))
app.get('/api/people/:id', (req, res) => {
  const id = Number(req.params.id)
  const p = state.people.find(x => x.id === id)
  if (p) return res.json(p)
  res.status(404).json({ error: 'Person not found' })
})
app.post('/api/people', (req, res) => {
  const p = { id: ++nextId, last_seen: new Date().toISOString(), ...req.body }
  state.people.push(p)
  broadcast('people')
  res.json(p)
})
app.put('/api/people/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.people.findIndex(p => p.id === id)
  if (idx !== -1) {
    state.people[idx] = { ...state.people[idx], ...req.body }
    broadcast('people')
    return res.json(state.people[idx])
  }
  res.status(404).json({ error: 'Person not found' })
})
app.get('/api/graph', (req, res) => {
  const nodes = [
    ...state.people.map(p => ({ id: `p_${p.id}`, label: p.name, kind: 'person' })),
    ...state.notes.slice(0, 5).map(n => ({ id: `n_${n.id}`, label: n.text.slice(0, 30), kind: 'note' })),
    ...state.orders.map(o => ({ id: `o_${o.id}`, label: o.title, kind: 'order' })),
  ]
  const links = [
    { source: 'p_1', target: 'o_1' },
    { source: 'p_2', target: 'o_2' },
    { source: 'n_1', target: 'o_1' },
  ]
  res.json({ nodes, links })
})
app.get('/api/graph/backlinks/:kind/:id', (req, res) => res.json({ links: [] }))

// Facts, Style & Memory
app.get('/api/facts', (req, res) => res.json(state.facts))
app.post('/api/facts', (req, res) => {
  const f = { id: ++nextId, created_at: new Date().toISOString(), active: true, ...req.body }
  state.facts.push(f)
  res.json(f)
})
app.put('/api/facts/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.facts.findIndex(f => f.id === id)
  if (idx !== -1) {
    state.facts[idx] = { ...state.facts[idx], ...req.body }
    return res.json(state.facts[idx])
  }
  res.status(404).json({ error: 'Fact not found' })
})
app.post('/api/facts/:id/forget', (req, res) => {
  const id = Number(req.params.id)
  const f = state.facts.find(x => x.id === id)
  if (f) f.active = false
  res.json({ ok: true })
})
app.post('/api/facts/:id/restore', (req, res) => {
  const id = Number(req.params.id)
  const f = state.facts.find(x => x.id === id)
  if (f) f.active = true
  res.json({ ok: true })
})
app.post('/api/facts/portrait', (req, res) => res.json({ ok: true }))
app.post('/api/facts/nightly', (req, res) => res.json({ ok: true }))
app.post('/api/facts/style', (req, res) => res.json({ ok: true }))
app.put('/api/facts/style', (req, res) => res.json({ ok: true }))
app.get('/api/lessons', (req, res) => res.json([]))
app.delete('/api/lessons/:id', (req, res) => res.json({ ok: true }))
app.get('/api/memory', (req, res) => {
  res.json([
    ...state.notes.map(n => ({ kind: 'note', ...n })),
    ...state.links.map(l => ({ kind: 'link', ...l })),
  ])
})

// Boards (Canvas)
app.get('/api/boards', (req, res) => {
  const archived = req.query.archived === 'true'
  res.json(state.boards.filter(b => Boolean(b.archived) === archived))
})
app.post('/api/boards', (req, res) => {
  const b = {
    id: ++nextId,
    title: req.body.title || 'Новая доска',
    kind: req.body.kind || 'free',
    archived: false,
    cover: null,
    order_id: req.body.order_id || null,
    revision: 1,
    view: { x: 100, y: 100, k: 1 },
    items: [],
  }
  if (b.kind === 'storyboard') {
    const frames = Number(req.body.frames) || 6
    const ratio = req.body.ratio || '16:9'
    for (let i = 0; i < frames; i++) {
      b.items.push({
        id: ++nextId,
        type: 'frame',
        x: 80 + (i % 3) * 360,
        y: 100 + Math.floor(i / 3) * 300,
        w: 320,
        h: 234,
        z: i,
        rot: 0,
        data: { n: i + 1, seconds: 5, label: `Кадр ${i + 1}`, ratio },
      })
    }
  }
  state.boards.push(b)
  broadcast('boards')
  res.json(b)
})
app.get('/api/boards/:id', (req, res) => {
  const id = Number(req.params.id)
  const b = state.boards.find(x => x.id === id)
  if (b) return res.json(b)
  res.status(404).json({ error: 'Board not found' })
})
app.put('/api/boards/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.boards.findIndex(b => b.id === id)
  if (idx !== -1) {
    state.boards[idx] = { ...state.boards[idx], ...req.body }
    broadcast('boards')
    return res.json(state.boards[idx])
  }
  res.status(404).json({ error: 'Board not found' })
})
app.put('/api/boards/:id/sync', (req, res) => {
  const id = Number(req.params.id)
  const b = state.boards.find(x => x.id === id)
  if (!b) return res.status(404).json({ error: 'Board not found' })

  const clientRevision = req.body.revision || 0
  const items = req.body.items || []
  const id_map: Record<string, number> = {}

  b.items = items.map((it: any) => {
    let finalId = it.id
    if (finalId < 0) {
      finalId = ++nextId
      id_map[String(it.id)] = finalId
    }
    return { ...it, id: finalId }
  })
  b.revision = clientRevision + 1

  res.json({
    revision: b.revision,
    id_map,
  })
})
app.put('/api/boards/:id/view', (req, res) => {
  const id = Number(req.params.id)
  const b = state.boards.find(x => x.id === id)
  if (b) b.view = req.body
  res.json({ ok: true })
})
app.delete('/api/boards/:id', (req, res) => {
  const id = Number(req.params.id)
  state.boards = state.boards.filter(b => b.id !== id)
  broadcast('boards')
  res.json({ ok: true })
})

// Settings
app.get('/api/settings', (req, res) => {
  res.json({ items: state.settings })
})
app.put('/api/settings', (req, res) => {
  const changes = req.body.changes || {}
  for (const [key, value] of Object.entries(changes)) {
    const existing = state.settings.find(s => s.key === key)
    if (existing) existing.value = value as any
    else state.settings.push({ key, value: value as any })
  }
  broadcast('settings')
  res.json({ ok: true })
})

// Telegram & Device Auth
app.post('/api/tg/login', (req, res) => {
  res.json({ ok: true, name: 'Владелец' })
})

// Phone access / Tailscale QR
app.get('/api/phone', (req, res) => {
  res.json({
    tailscale: true,
    opened_from: 'localhost:3000',
    items: [
      {
        kind: 'tailscale',
        title: 'Через Tailscale (из любой сети)',
        url: 'http://desktop-jarvis.tailnet.ts.net:3000?t=sample-token-key-2026',
        qr: '',
      },
      {
        kind: 'lan',
        title: 'Домашний Wi-Fi',
        url: 'http://192.168.1.105:3000?t=sample-token-key-2026',
        qr: '',
      }
    ]
  })
})
app.post('/api/phone/rotate', (req, res) => {
  res.json({ ok: true })
})

// Screen Time / PC Activity API
app.get('/api/screen', (req, res) => {
  const days = Number(req.query.days) || 1
  const hours = [0, 0, 0, 0, 0, 0, 0, 0, 15, 45, 55, 60, 40, 50, 58, 42, 30, 0, 0, 0, 0, 0, 0, 0]
  const hour_cats: Record<number, string> = {
    8: 'общение',
    9: 'работа',
    10: 'работа',
    11: 'работа',
    12: 'браузер',
    13: 'работа',
    14: 'работа',
    15: 'работа',
    16: 'медиа',
  }
  res.json({
    recording: true,
    pc_alive: true,
    active_min: 342, // 5ч 42мин
    first: `${todayStr}T08:45:00`,
    sessions: [
      { start: `${todayStr}T08:45:00`, end: `${todayStr}T12:30:00`, min: 225 },
      { start: `${todayStr}T13:15:00`, end: `${todayStr}T16:40:00`, min: 205 },
    ],
    hours,
    hour_cats,
    apps: [
      ['Premiere Pro', 200, 'работа', 'Монтаж узбекам2'],
      ['After Effects', 72, 'работа', 'Анимация титров'],
      ['Telegram Desktop', 35, 'общение', 'Чат с клиентом'],
      ['Google Chrome', 25, 'браузер', 'YouTube референсы'],
      ['Figma', 10, 'работа', 'Превью макета'],
    ],
    projects: [
      { app: 'Premiere Pro', project: 'Монтаж узбекам2', minutes: 200, days },
      { app: 'After Effects', project: 'Анимация титров', minutes: 72, days },
    ]
  })
})

// PC File Organizer & Backups
app.get('/api/backups', (req, res) => {
  res.json([
    { name: 'backup-20260929-0300.db', at: '2026-09-29T03:00:00', size: 184320, pre_restore: false },
    { name: 'backup-20260928-0300.db', at: '2026-09-28T03:00:00', size: 178200, pre_restore: false },
    { name: 'backup-pre-restore-20260927-1420.db', at: '2026-09-27T14:20:00', size: 172000, pre_restore: true }
  ])
})

app.post('/api/backups/restore', (req, res) => {
  const name = req.body?.name || 'backup-current.db'
  res.json({ ok: true, restored: name, safety: 'backup-pre-restore-current.db', needs_restart: true })
})

app.get('/api/pc/organize/preview', (req, res) => {
  res.json({
    status: 'ready',
    root: 'D:\\Проекты\\Монтаж',
    total: 4,
    profile: 'sound',
    by_category: {
      '02_Исходники/Видео': 2,
      '05_Проекты': 1,
      '05_Шаги': 1,
    },
    cleanup_dirs: ['02_Исходники/Старое'],
    moves: [
      { src: 'clip.mov', dst: '02_Исходники/Видео/clip.mov' },
      { src: 'music.wav', dst: 'SFX/05_Шаги/music.wav' },
      { src: 'edit.prproj', dst: '05_Проекты/edit.prproj' }
    ]
  })
})

app.get('/api/pc/organize/log', (req, res) => {
  res.json([
    {
      at: '2026-09-29 11:20',
      kind: 'organize',
      text: 'Организована папка D:\\Проекты\\Монтаж (4 файла)',
      log: {
        moved: [
          { src: 'clip.mov', dst: '02_Исходники/Видео/clip.mov' },
          { src: 'music.wav', dst: 'SFX/05_Шаги/music.wav' },
          { src: 'edit.prproj', dst: '05_Проекты/edit.prproj' }
        ]
      }
    }
  ])
})

// Undo
app.post('/api/undo', (req, res) => {
  res.json({ ok: true, text: 'Последнее действие отменено' })
})

// Search
app.get('/api/search/semantic', (req, res) => {
  const q = String(req.query.q || '').toLowerCase()
  const results = [
    ...state.notes.filter(n => n.text.toLowerCase().includes(q)).map(n => ({ kind: 'note', id: n.id, title: n.text.slice(0, 40), snippet: n.text })),
    ...state.tasks.filter(t => t.title.toLowerCase().includes(q)).map(t => ({ kind: 'task', id: t.id, title: t.title, snippet: t.category })),
    ...state.events.filter(e => e.title.toLowerCase().includes(q)).map(e => ({ kind: 'event', id: e.id, title: e.title, snippet: e.start })),
  ]
  res.json(results)
})
app.post('/api/search/reindex', (req, res) => res.json({ ok: true, count: 42 }))
app.post('/api/backup', (req, res) => res.json({ ok: true, file: 'backup-current.zip' }))

// Chat
app.get('/api/chat/history', (req, res) => {
  res.json(state.chatHistory)
})

function processChatInput(text: string): { reply: string; actions: string[]; via: string } {
  const lower = text.toLowerCase().trim()

  // 1. Finance: Expense detection e.g. "700 такси", "трата 500 кофе", "1200 обед"
  const expenseMatch = lower.match(/^(?:трата|расход|потратил|купил)?\s*(\d+)\s*(?:₽|руб|р)?\s*(.+)$/i) ||
                       lower.match(/^(.+?)\s+(\d+)\s*(?:₽|руб|р)?$/i)
  if (expenseMatch && !lower.includes('напомни') && !lower.includes('задача') && !lower.includes('встреча')) {
    const isFirstNum = /^\d+/.test(expenseMatch[1])
    const amount = Number(isFirstNum ? expenseMatch[1] : expenseMatch[2])
    const comment = (isFirstNum ? expenseMatch[2] : expenseMatch[1]).trim()

    if (!isNaN(amount) && amount > 0 && comment) {
      let cat = 'Другое'
      if (/кофе|обед|еда|ужин|продукты|супермаркет|бургер/i.test(comment)) cat = 'Еда'
      else if (/такси|метро|автобус|бензин|парковка/i.test(comment)) cat = 'Транспорт'
      else if (/подписка|яндекс|telegram/i.test(comment)) cat = 'Подписки'
      else if (/аптека|врач|лекарств/i.test(comment)) cat = 'Здоровье'

      state.transactions.unshift({
        id: ++nextId,
        date: new Date().toISOString(),
        amount: -amount,
        category: cat,
        account: state.accounts[0].name,
        comment,
      })
      const acc = state.accounts[0]
      if (acc) acc.balance = (acc.balance || 0) - amount
      broadcast('finance')

      return {
        reply: `Записал расход: ${amount.toLocaleString('ru-RU')} ₽ на «${comment}» (${cat}). Баланс: ${acc.balance.toLocaleString('ru-RU')} ₽.`,
        actions: ['add_expense'],
        via: 'rule',
      }
    }
  }

  // 2. Finance: Income detection e.g. "зп 150000", "доход 45000 ролик"
  const incomeMatch = lower.match(/^(?:зп|зарплата|доход|пришло|аванс)\s*(\d+)\s*(?:₽|руб|р)?(?:\s+(.+))?$/i)
  if (incomeMatch) {
    const amount = Number(incomeMatch[1])
    const comment = incomeMatch[2]?.trim() || 'Доход'
    state.transactions.unshift({
      id: ++nextId,
      date: new Date().toISOString(),
      amount,
      category: /аванс|ролик|заказ|клиент/i.test(comment) ? 'Фриланс' : 'Зарплата',
      account: state.accounts[0].name,
      comment,
    })
    const acc = state.accounts[0]
    if (acc) acc.balance = (acc.balance || 0) + amount
    broadcast('finance')
    return {
      reply: `Зафиксировал доход: +${amount.toLocaleString('ru-RU')} ₽ (${comment}). Текущий баланс: ${acc.balance.toLocaleString('ru-RU')} ₽.`,
      actions: ['add_income'],
      via: 'rule',
    }
  }

  // 3. Tasks: "напомни сделать ...", "задача: ..."
  if (lower.startsWith('напомни') || lower.startsWith('задача')) {
    const title = text.replace(/^(?:напомни|задача:?)\s*/i, '').trim()
    const task = {
      id: ++nextId,
      title: title || 'Новая задача',
      due: `${todayStr}T21:00:00`,
      priority: 1,
      done: 0,
      created_at: new Date().toISOString(),
      category: 'Личное',
    }
    state.tasks.push(task)
    broadcast('tasks')
    return {
      reply: `Добавил в список задач: «${task.title}». Напоминание установлено на сегодня.`,
      actions: ['add_task'],
      via: 'rule',
    }
  }

  // 4. Events: "встреча ...", "календарь: ..."
  if (lower.startsWith('встреча') || lower.startsWith('событие')) {
    const title = text.replace(/^(?:встреча:?|событие:?)\s*/i, '').trim()
    const ev = {
      id: ++nextId,
      title: title || 'Встреча',
      start: `${todayStr}T17:00:00`,
      end: `${todayStr}T18:00:00`,
      duration_min: 60,
      location: null,
      notes: null,
      remind_minutes: 30,
      repeat: '',
      repeat_days: [],
      done: 0,
    }
    state.events.push(ev)
    broadcast('events')
    return {
      reply: `Записал в календарь: «${ev.title}» на ${todayStr} в 17:00.`,
      actions: ['add_event'],
      via: 'rule',
    }
  }

  // 5. Notes & Thoughts: "запомни ...", "мозг: ...", "запиши это как мысль"
  if (lower.startsWith('запомни') || lower.startsWith('мозг:') || lower.startsWith('мысль') || lower.includes('запиши это как мысль') || lower.includes('не превращай это в задачу')) {
    const noteText = text.replace(/^(?:запомни:?|мозг:?|мысль:?|запиши это как мысль:?)\s*/i, '').replace(/не превращай это в задачу/i, '').trim() || 'Важная мысль'
    const note = {
      id: ++nextId,
      text: noteText,
      tags: ['мысль', 'мозг'],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    state.notes.unshift(note)
    broadcast('notes')
    return {
      reply: `Записал в «Мозг»: «${noteText.slice(0, 80)}${noteText.length > 80 ? '…' : ''}». В задачи не превращал, оставил как мысль.`,
      actions: ['add_note'],
      via: 'rule',
    }
  }

  // 6. Day-to-day assistant queries from roadmap
  if (lower.includes('день рождения') || lower.includes('дни рождения')) {
    const todayBirthdays = state.people.filter(p => p.birthday && p.birthday.endsWith(todayStr.slice(5)))
    if (todayBirthdays.length > 0) {
      return {
        reply: `Сегодня день рождения у: ${todayBirthdays.map(p => p.name).join(', ')}!`,
        actions: [],
        via: 'rule',
      }
    }
    return {
      reply: 'Сегодня дней рождений нет. Ближайшие: Анна Васильева (20 мая) и Дмитрий Соколов (14 октября).',
      actions: [],
      via: 'rule',
    }
  }

  if (lower.includes('напомни мне про подарок') || lower.includes('напомни подарок') || lower.includes('подарок')) {
    if (lower.includes('идеи') || lower.includes('накидай')) {
      return {
        reply: 'Вот 4 практичных варианта с хорошим вкусом:\n1. Премиальные беспроводные наушники с шумоподавлением.\n2. Кожаный картхолдер или чехол ручной работы.\n3. Впечатление: билет на закрытый концерт или мастер-класс.\n4. Минималистичная настольная лампа тёплого рассеянного света.',
        actions: [],
        via: 'rule',
      }
    }
    const task = {
      id: ++nextId,
      title: 'Выбрать и заказать подарок',
      due: `${todayStr}T19:00:00`,
      priority: 1,
      done: 0,
      created_at: new Date().toISOString(),
      category: 'Личное',
    }
    state.tasks.push(task)
    broadcast('tasks')
    return {
      reply: 'Поставил задачу: «Выбрать и заказать подарок» на сегодня к 19:00. Напомню вовремя.',
      actions: ['add_task'],
      via: 'rule',
    }
  }

  if (lower.includes('сколько я сегодня работал') || lower.includes('сколько отработал') || lower.includes('мое время')) {
    return {
      reply: 'Сегодня зафиксировано 5 ч 42 мин:\n• Premiere Pro: 3 ч 20 мин (монтаж ролика)\n• After Effects: 1 ч 12 мин (анимация графики)\n• Правки вручную: 40 мин\n• Созвон: 30 мин\nПлан на день составлял 5 часов. Превышение: 42 минуты.',
      actions: [],
      via: 'rule',
    }
  }

  if (lower.includes('что я обещал клиенту') || lower.includes('что обещал')) {
    const active = state.orders.find(o => o.status === 'work')
    if (active) {
      return {
        reply: `По заказу «${active.title}» (${active.client}): вы обещали чистовой рендер и утверждение сцен к 20:00.`,
        actions: [],
        via: 'rule',
      }
    }
    return {
      reply: 'По текущим заказам срочных невыполненных обязательств нет.',
      actions: [],
      via: 'rule',
    }
  }

  if (lower.includes('я устал') || lower.includes('что можно перенести') || lower.includes('перенести')) {
    return {
      reply: 'Созвон в 15:00 и рендер ролика к 20:00 лучше закрыть сегодня. А бытовые дела — «Забрать посылку» и «Оплатить сервисы» — можно безболезненно сдвинуть на завтра.',
      actions: [],
      via: 'rule',
    }
  }

  if (lower.includes('что у меня сегодня важного') || lower.includes('что важного')) {
    const openOrders = state.orders.filter(o => ['work', 'review'].includes(o.status))
    const task = state.tasks.find(t => !t.done)
    return {
      reply: `Главное на сегодня:\n1. Дедлайн по заказу «${openOrders[0]?.title || 'Ролик'}» в 20:00.\n2. Встреча с клиентом в 15:00.\n3. Приоритетная задача: «${task?.title || 'Отдых'}».`,
      actions: [],
      via: 'rule',
    }
  }

  // 7. Status queries
  if (lower.includes('баланс') || lower.includes('сколько денег')) {
    const balance = state.accounts.reduce((acc, a) => acc + (a.balance || 0), 0)
    return {
      reply: `Общий баланс на счетах: ${balance.toLocaleString('ru-RU')} ₽. Доступно для распределения.`,
      actions: [],
      via: 'rule',
    }
  }

  if (lower.includes('итоги недели') || lower.includes('недельный отчёт') || lower.includes('отчёт за неделю')) {
    return {
      reply: '📊 Итоги недели, вовчик. 20.09 — 27.09.2026\nПотрачено: 6 589 ₽ (−5% к прошлому)\nЗаработано: 0 ₽\n\nКуда ушло:\n• Еда: 3 047 ₽\n• Другое: 2 638 ₽\n• Алкоголь: 605 ₽\n• Подписки: 299 ₽\n\nДела: 2 задачи закрыто, 1 заметка, 8 из 7 дней с записями.\nБаланс: 15 761 ₽, долги: 205 700 ₽.',
      actions: ['summary'],
      via: 'rule',
    }
  }

  if (lower.includes('доброе утро') || lower.includes('утренний дайджест') || lower.includes('дайджест')) {
    return {
      reply: '☀️ Доброе утро, вовчик. Воскресенье, 27.09\nСегодня встреч нет — день ваш.\nЗадач нет. Подозрительно.\nБаланс: 15 761 ₽. Можно тратить в день: 3 940 ₽.',
      actions: ['digest'],
      via: 'rule',
    }
  }

  if (lower.includes('что на сегодня') || lower.includes('план на сегодня') || lower.includes('расписание')) {
    const evCount = state.events.length
    const taskCount = state.tasks.filter(t => !t.done).length
    return {
      reply: `На сегодня запланировано ${evCount} встреч и ${taskCount} невыполненных задач. Главный приоритет — «${state.tasks.find(t => !t.done)?.title || 'отдых'}».`,
      actions: [],
      via: 'rule',
    }
  }

  // Fallback assistant response
  return {
    reply: `Да, сэр. Я зафиксировал: «${text}». Могу записать трату («700 такси»), засечь время («таймер 25 мин»), напомнить о встрече или проверить статус заказов.`,
    actions: [],
    via: 'rule',
  }
}

app.post('/api/chat', async (req, res) => {
  const { text } = req.body
  const result = processChatInput(text)

  state.chatHistory.push({
    id: ++nextId,
    role: 'user',
    text,
    timestamp: new Date().toISOString(),
    actions: [],
    via: 'user',
  })
  state.chatHistory.push({
    id: ++nextId,
    role: 'assistant',
    text: result.reply,
    timestamp: new Date().toISOString(),
    actions: result.actions,
    via: result.via,
  })

  res.json({ text: result.reply, actions: result.actions, via: result.via })
})

app.post('/api/chat/stream', async (req, res) => {
  const { text } = req.body
  const result = processChatInput(text)

  state.chatHistory.push({
    id: ++nextId,
    role: 'user',
    text,
    timestamp: new Date().toISOString(),
    actions: [],
    via: 'user',
  })
  state.chatHistory.push({
    id: ++nextId,
    role: 'assistant',
    text: result.reply,
    timestamp: new Date().toISOString(),
    actions: result.actions,
    via: result.via,
  })

  res.setHeader('Content-Type', 'text/event-stream')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')
  res.flushHeaders()

  // Stream in small word tokens for natural UI typing effect
  const words = result.reply.split(' ')
  for (let i = 0; i < words.length; i++) {
    const chunk = (i === 0 ? '' : ' ') + words[i]
    res.write(`event: token\ndata: ${JSON.stringify(chunk)}\n\n`)
    await new Promise(r => setTimeout(r, 25))
  }

  res.write(`event: done\ndata: ${JSON.stringify({ text: result.reply, actions: result.actions, via: result.via })}\n\n`)
  res.end()
})

// ----------------- VITE / STATIC SERVING -----------------

async function setupFrontend() {
  if (!isProd) {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    })
    app.use(vite.middlewares)
  } else {
    const distPath = path.resolve(process.cwd(), 'dist')
    if (fs.existsSync(distPath)) {
      app.use(express.static(distPath))
      app.get('*', (req, res) => {
        res.sendFile(path.join(distPath, 'index.html'))
      })
    }
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Assistant server running at http://0.0.0.0:${PORT} in ${isProd ? 'production' : 'development'} mode`)
  })
}

setupFrontend().catch(err => {
  console.error('Failed to start server:', err)
  process.exit(1)
})
