import express from 'express'
import cors from 'cors'
import multer from 'multer'
import { createHmac, timingSafeEqual } from 'crypto'
import { createServer as createViteServer } from 'vite'
import path from 'path'
import fs from 'fs'
import os from 'os'
import { execFileSync } from 'child_process'
import qrcode from 'qrcode-generator'

const isProd = process.env.NODE_ENV === 'production'
const PORT = Number(process.env.PORT) || 3000
// по умолчанию сервер слушает только локально; открыть наружу — явно HOST=0.0.0.0
const HOST = process.env.HOST || '127.0.0.1'

// .env читаем вручную — новых зависимостей ради этого не заводим.
// Так подключаются LLM_API_KEY / LLM_URL / LLM_MODEL, TELEGRAM_BOT_TOKEN и прочие секреты.
try {
  const envFile = path.join(process.cwd(), '.env')
  if (fs.existsSync(envFile)) {
    for (const line of fs.readFileSync(envFile, 'utf8').split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/)
      if (!m || !m[2]) continue
      const val = m[2].replace(/^(["'])(.*)\1$/, '$2')
      if (process.env[m[1]] === undefined) process.env[m[1]] = val
    }
  }
} catch (e) {
  console.warn('[env] не смог прочитать .env:', (e as any)?.message || e)
}

// страховка: необработанный промис/исключение не должен ронять весь процесс —
// один HTTP-запрос с неожиданным телом убивал сервер (см. роуты /api/chat)
process.on('unhandledRejection', (reason) => {
  console.error('[server] unhandledRejection:', reason)
})
process.on('uncaughtException', (err) => {
  console.error('[server] uncaughtException:', err)
})

const app = express()
// CORS не безгранижен: свой веб-сервер отдаётся с того же origin, поэтому по умолчанию
// разрешены только localhost/127.0.0.1 (порт сервера и vite-dev), остальное — через ALLOWED_ORIGINS
const localOrigins = ['localhost', '127.0.0.1'].flatMap(h => [
  `http://${h}:${PORT}`, `https://${h}:${PORT}`, `http://${h}:5173`, `https://${h}:5173`,
])
const allowedOrigins = new Set([
  ...localOrigins,
  ...(process.env.ALLOWED_ORIGINS || '').split(',').map(s => s.trim()).filter(Boolean),
])
app.use(cors({
  origin: (origin, cb) => cb(null, !origin || allowedOrigins.has(origin)),
  credentials: false,
}))
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
const dayNow = () => new Date().toISOString().split('T')[0]
let todayStr = dayNow()
// «сегодня» должно считаться в рантайме: константа при старте устаревала после полуночи
// (UTC-срез — как и раньше, чтобы не менять поведение дат)
app.use((_req, _res, next) => { todayStr = dayNow(); next() })
setInterval(() => { todayStr = dayNow() }, 60_000).unref()

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
  ] as any[],
  events: [
    { id: 1, title: 'Синхронизация с командой', start: `${todayStr}T11:00:00`, end: `${todayStr}T12:00:00`, duration_min: 60, location: 'Google Meet', notes: 'План на следующую неделю', remind_minutes: 15, repeat: 'weekly', repeat_days: [1], done: 0 },
    { id: 2, title: 'Встреча с клиентом (ролик)', start: `${todayStr}T15:00:00`, end: `${todayStr}T16:00:00`, duration_min: 60, location: 'Zoom', notes: 'Обсуждение раскадровки и тайминга', remind_minutes: 30, repeat: '', repeat_days: [], done: 0, order_id: 1 },
  ] as any[],
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
  ] as any[],
  recurring: [
    { id: 1, title: 'Яндекс Плюс', amount: 299, kind: 'expense', period: 'monthly', day_of_month: 15, category: 'Подписки', account: 'Т-Банк Основной', active: true },
    { id: 2, title: 'Аренда жилья', amount: 40000, kind: 'expense', period: 'monthly', day_of_month: 25, category: 'Жильё', account: 'Т-Банк Основной', active: true },
  ],
  goals: [
    { id: 1, name: 'Финансовая подушка 500к', target: 500000, current: 350000, due_date: '2026-12-31', color: '#30d158', icon: '🛡️' },
    { id: 2, name: 'Новый ноутбук для монтажа', target: 180000, current: 95000, due_date: '2026-11-15', color: '#64d2ff', icon: '💻' },
  ] as any[],
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
  // зеркало оформления (localStorage) между устройствами — GET/PUT /api/ui-prefs
  uiPrefs: {} as Record<string, any>,
  // раньше категории людей были захардкожены в роуте — DELETE ничего не делал
  peopleKinds: ['клиент', 'коллега', 'друг', 'семья'],
  // «как вы пишете»: раньше PUT /api/facts/style отбрасывал текст, правка терялась при перезагрузке
  memoryStyle: { style: '', style_at: null as string | null },
  // последний отклик PC-клиента (ack/result) — по нему /api/pc/state считает alive
  pc: { alive: false, mode: 'idle', text: '', at: null as string | null },
}

let nextId = 100

// ----------------- PERSISTENCE -----------------
// Состояние жило только в памяти: любой рестарт терял все правки, хотя UI их отмечал
// как сохранённые. Пишем в data/server-state.json (файл в .gitignore), атомарно.
const STATE_FILE = path.resolve(process.cwd(), 'data', 'server-state.json')
let stateDirty = false

function saveState() {
  if (!stateDirty) return
  try {
    fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true })
    const tmp = STATE_FILE + '.tmp'
    fs.writeFileSync(tmp, JSON.stringify({ state, nextId }))
    fs.renameSync(tmp, STATE_FILE)
    stateDirty = false
  } catch (err) {
    console.error('[server] state save failed:', err)
  }
}

function loadState() {
  if (!fs.existsSync(STATE_FILE)) return
  try {
    const parsed = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'))
    if (parsed?.state && typeof parsed.state === 'object') {
      for (const [k, v] of Object.entries(parsed.state)) (state as any)[k] = v
      if (typeof parsed.nextId === 'number' && parsed.nextId > nextId) nextId = parsed.nextId
      console.log(`[server] state loaded: ${STATE_FILE}`)
    }
  } catch (err) {
    // битый файл не должен мешать старту — поднимемся на моках
    console.error('[server] state load failed, using defaults:', err)
  }
}
// заказы: сумма исторически лежала в `total`, а фронт читает `price` (как в Python) — держим оба поля одинаковыми
function orderMoney(o: any) {
  const p = Number(o.price ?? o.total) || 0
  o.price = p
  o.total = p
  o.paid = Number(o.paid) || 0
  o.left = Math.max(0, p - o.paid)
  return o
}
loadState()
for (const o of state.orders as any[]) orderMoney(o)

// грязный флаг ставим на любой мутирующий запрос; фоновая запись + запись при выходе
app.use((req, _res, next) => {
  if (req.method !== 'GET' && req.method !== 'HEAD') stateDirty = true
  next()
})
setInterval(saveState, 5_000).unref()
for (const sig of ['SIGINT', 'SIGTERM'] as const) {
  process.on(sig, () => { saveState(); process.exit(0) })
}
process.on('exit', saveState)

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

// По умолчанию — «Марвин»: репозиторий и сайт проекта marvin-ru. Издание «личное» — только по явному EDITION=jarvis.
let currentEdition = process.env.EDITION === 'marvin' ? 'marvin' : 'jarvis'

// Health
app.get('/api/health', (req, res) => {
  const isMarvin = currentEdition === 'marvin'
  res.json({
    ok: true,
    ollama: false,
    mode: 'local',
    time: new Date().toISOString(),
    version: PKG_VERSION,
    edition: currentEdition,
    name: 'Марвин',
    name_latin: 'Marvin',
  })
})

// Edition Management
app.get('/api/edition', (req, res) => {
  const isMarvin = currentEdition === 'marvin'
  res.json({
    edition: currentEdition,
    name: 'Марвин',
    name_latin: 'Marvin',
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
    name: 'Марвин',
    name_latin: 'Marvin',
    is_marvin: isMarvin,
    is_jarvis: !isMarvin,
  })
})

// Status & State
const PKG_VERSION = (() => {
  try { return JSON.parse(fs.readFileSync(path.resolve(process.cwd(), 'package.json'), 'utf8')).version || '0.0.0' }
  catch { return '0.0.0' }
})()

/** размер каталога данных для карточки «база» (с потолком, чтобы не гонять на каждом запросе) */
function dirSize(dir: string, limit = 500): number {
  let total = 0, files = 0
  const walk = (d: string) => {
    if (files >= limit) return
    let entries: fs.Dirent[] = []
    try { entries = fs.readdirSync(d, { withFileTypes: true }) } catch { return }
    for (const e of entries) {
      if (files >= limit) return
      const p = path.join(d, e.name)
      if (e.isDirectory()) walk(p)
      else { try { total += fs.statSync(p).size; files++ } catch {} }
    }
  }
  walk(dir)
  return total
}

// фронт (src/pages/Settings.jsx) рисует карточки по этой структуре — форма должна совпадать
// с Python /api/status, иначе страница падает на status.ollama.ok
app.get('/api/status', (_req, res) => {
  const dataDir = path.resolve(process.cwd(), 'data')
  res.json({
    ok: true,
    time: new Date().toISOString(),
    version: PKG_VERSION,
    uptime: process.uptime(),
    game_mode: false,
    vision: '—',
    pc: {
      alive: state.pc.at ? Date.now() - new Date(state.pc.at).getTime() < 5 * 60_000 : false,
      mode: state.pc.mode || 'idle',
    },
    ollama: {
      ok: false,
      model: '',
      url: '',
      diag: 'Node-демо не подключено к Ollama — мозг этого стека не используется, нужен Python (start.bat)',
      gpu: '',
      embed: false,
      embed_model: '',
      small_model: '',
      small_ok: false,
      small_keep_alive: '',
      small_last: null,
    },
    gemini: {
      enabled: false,
      provider: 'gemini',
      title: 'gemini',
      model: '',
      proxy: null,
      last_error: null,
      providers: {},
    },
    telegram: { configured: false, running: false, last_message: null },
    backup: { enabled: false, last: null, count: 0, dir: 'data/backups' },
    db: {
      path: dataDir,
      size: dirSize(dataDir),
      events: state.events.length,
      tasks: state.tasks.length,
      notes: state.notes.length,
      links: state.links.length,
      transactions: state.transactions.length,
    },
    errors: [] as { text: string }[],
  })
})

// кнопки «проверить» в настройках: Node-демо ничего не проверяет — отвечаем честно,
// а не молчаливым {ok:true}, как раньше
app.post('/api/status/small', (_req, res) => {
  res.json({ ok: false, detail: 'Малая модель не используется в Node-демо', hint: 'настройте мозг в Python-ядре (start.bat)' })
})
app.post('/api/status/gemini', (_req, res) => {
  res.json({ ok: false, detail: 'Ключ Gemini не задан для Node-демо', hint: 'задайте GEMINI_API_KEY в Python-ядре' })
})
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
  const fresh = state.pc.at && Date.now() - new Date(state.pc.at).getTime() < 5 * 60_000
  res.json({
    alive: !!fresh,
    mode: state.pc.mode || 'idle',
    text: state.pc.text || '',
  })
})
app.post('/api/pc/ack', (req, res) => {
  // клиент подтверждает получение команды — фиксируем, иначе статус ПК всегда «не запущен»
  state.pc = { ...state.pc, alive: true, at: new Date().toISOString(), text: String(req.body?.text || '') }
  broadcast('pc_state')
  res.json({ ok: true })
})
app.post('/api/pc/result', (req, res) => {
  state.pc = { ...state.pc, alive: true, at: new Date().toISOString(), text: String(req.body?.text || '') }
  broadcast('pc_state')
  res.json({ ok: true })
})
app.post('/api/pc/clipboard', (req, res) => res.json({ ok: true, text: 'Сохранено' }))

// Dashboard
/** сколько дней до ближайшего дня рождения (день рождения может быть в этом году уже прошёл) */
function daysUntilBirthday(iso: string): number {
  const b = new Date(`${String(iso).slice(0, 10)}T00:00:00`)
  if (Number.isNaN(b.getTime())) return 0
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  let next = new Date(today.getFullYear(), b.getMonth(), b.getDate())
  if (next.getTime() < today.getTime()) next = new Date(today.getFullYear() + 1, b.getMonth(), b.getDate())
  return Math.round((next.getTime() - today.getTime()) / 86_400_000)
}

app.get('/api/dashboard', (req, res) => {
  const balance = state.accounts.reduce((acc, a) => acc + (a.balance || 0), 0)
  const income_month = state.transactions.filter(t => t.amount > 0).reduce((acc, t) => acc + t.amount, 0)
  const expense_month = Math.abs(state.transactions.filter(t => t.amount < 0).reduce((acc, t) => acc + t.amount, 0))

  const finSummary = {
    balance,
    income_month,
    expense_month,
    cashflow: income_month - expense_month,
    // Today.jsx считает «к концу месяца» от этих двух чисел — без них страница подставляла выдуманные
    avg_daily: (() => {
      const day = new Date().getDate()
      const spent = state.transactions.filter(t => t.amount < 0 && (t.date || '').slice(0, 7) === new Date().toISOString().slice(0, 7))
      const total = spent.reduce((s, t) => s + Math.abs(t.amount), 0)
      return day > 0 ? Math.round(total / day) : 0
    })(),
    runway_days: (() => {
      const day = new Date().getDate()
      const spent = state.transactions.filter(t => t.amount < 0 && (t.date || '').slice(0, 7) === new Date().toISOString().slice(0, 7))
      const perDay = day > 0 ? spent.reduce((s, t) => s + Math.abs(t.amount), 0) / day : 0
      return perDay > 0 ? Math.floor(balance / perDay) : 180
    })(),
    // столбики на карточках «траты» и «свободно» — считаем из реальных операций, а не рисуем
    weekday: (() => {
      const n = new Date()
      const sums = [0, 0, 0, 0, 0, 0, 0]   // пн..вс
      for (const t of state.transactions) {
        if (t.amount >= 0) continue
        const d = new Date(t.date)
        if (Number.isNaN(d.getTime()) || d.getFullYear() !== n.getFullYear() || d.getMonth() !== n.getMonth()) continue
        sums[(d.getDay() + 6) % 7] += Math.abs(t.amount)
      }
      return sums
    })(),
    month_days: (() => {
      const n = new Date()
      const buckets = [0, 0, 0, 0, 0, 0, 0]   // 1-4, 5-9, 10-14, 15-19, 20-24, 25-29, 30-31
      const edges = [4, 9, 14, 19, 24, 29, 31]
      for (const t of state.transactions) {
        if (t.amount >= 0) continue
        const d = new Date(t.date)
        if (Number.isNaN(d.getTime()) || d.getFullYear() !== n.getFullYear() || d.getMonth() !== n.getMonth()) continue
        const dayN = d.getDate()
        const idx = edges.findIndex(e => dayN <= e)
        buckets[idx === -1 ? 6 : idx] += Math.abs(t.amount)
      }
      return buckets
    })(),
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
    birthdays: state.people.filter(p => p.birthday).map(p => ({ ...p, days_left: daysUntilBirthday(p.birthday) })),
    forecast,
    // состояние ПК — из последнего отклика клиента, а не захардкоженный true
    pc: { alive: !!(state.pc.at && Date.now() - new Date(state.pc.at).getTime() < 5 * 60_000), idle: state.pc.mode === 'idle' },
    timer: state.timer,
    orders: {
      open: openOrders.slice(0, 5),
      unpaid,
      expected: openOrders.reduce((s, o) => s + (o.total || 0), 0),
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

// Дедлайн заказа живёт в календаре такой же строкой, как встреча:
// галочка «сдать» в календаре переводит заказ в статус «сдан» (и обратно).
const ORDER_EVENT_OFFSET = 1_000_000
function orderAsEvent(o: any) {
  const closed = ['done', 'paid', 'cancelled'].includes(o.status)
  return {
    id: -(ORDER_EVENT_OFFSET + o.id),
    order_id: o.id,
    kind: 'order',
    title: `Сдать: ${o.title}`,
    start: o.deadline || o.created_at,
    end: o.deadline || o.created_at,
    duration_min: 0,
    all_day: true,
    location: o.client || null,
    notes: o.notes || null,
    repeat: '',
    status: o.status,
    done: closed,
  }
}

// Events (Calendar)
app.get('/api/events', (req, res) => {
  const { tasks_too, start, end } = req.query
  // календарь просит свой диапазон — без фильтра он получал все события всех месяцев сразу
  const from = start ? new Date(String(start)).getTime() - 86_400_000 : null
  const to = end ? new Date(String(end)).getTime() + 86_400_000 : null
  const inRange = (iso?: string) => {
    if (from == null && to == null) return true
    const t = iso ? new Date(iso).getTime() : NaN
    if (Number.isNaN(t)) return true   // дата без времени — не прячем
    return (from == null || t >= from) && (to == null || t <= to)
  }
  const list: any[] = []
  if (tasks_too === 'true') {
    list.push(...state.tasks.map(taskAsEvent).filter((e) => inRange(e.start)))
    list.push(...(state.orders as any[]).map(orderAsEvent).filter((e) => inRange(e.start)))
  }
  list.push(...state.events.filter((e) => inRange(e.start)))
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

/* Завершение события — каскад по связям (как в оригинальном Марвине: одно действие,
   а отражается оно и в задачах, и в заказах):
   - отрицательный id < -1_000_000 → это дедлайн заказа: галочка «сдал», обратно — «вернуть в работу»;
   - отрицательный id → это задача, показанная в календаре;
   - у обычной встречи может быть task_id/order_id — закрываем и их. */
app.post('/api/events/:id/done', (req, res) => {
  const id = Number(req.params.id)
  const done = req.body?.done === false ? 0 : 1
  const linked: string[] = []

  if (id <= -ORDER_EVENT_OFFSET) {
    const order = state.orders.find((o: any) => o.id === -(id + ORDER_EVENT_OFFSET)) as any
    if (!order) return res.status(404).json({ error: 'Order not found' })
    if (done && !['paid', 'cancelled'].includes(order.status)) {
      order.status = 'done'
      linked.push(`заказ «${order.title}» — сдан`)
    } else if (!done && order.status === 'done') {
      order.status = 'work'
      linked.push(`заказ «${order.title}» — снова в работе`)
    }
    broadcast('orders')
    broadcast('events')
    return res.json({ ok: true, linked })
  }

  if (id < 0) {
    const task = state.tasks.find((t) => t.id === -id)
    if (!task) return res.status(404).json({ error: 'Task not found' })
    task.done = done
    if (done) task.done_at = new Date().toISOString(); else delete task.done_at
    broadcast('tasks')
    broadcast('events')
    return res.json({ ok: true, linked })
  }

  const ev = state.events.find((e) => e.id === id)
  if (!ev) return res.status(404).json({ error: 'Event not found' })
  ev.done = done
  if (done) ev.done_at = new Date().toISOString(); else delete ev.done_at

  if (ev.task_id) {
    const task = state.tasks.find((t) => t.id === Number(ev.task_id))
    if (task) {
      task.done = done
      if (done) task.done_at = new Date().toISOString(); else delete task.done_at
      linked.push(`задача «${task.title}»`)
      broadcast('tasks')
    }
  }
  if (ev.order_id) {
    const order = state.orders.find((o: any) => o.id === Number(ev.order_id)) as any
    if (order) {
      if (done && !['paid', 'cancelled'].includes(order.status)) order.status = 'done'
      else if (!done && order.status === 'done') order.status = 'work'
      linked.push(`заказ «${order.title}»`)
      broadcast('orders')
    }
  }
  broadcast('events')
  res.json({ ok: true, linked })
})

app.post('/api/events/:id/skip', (req, res) => {
  res.json({ ok: true })
})

// Tasks
app.get('/api/tasks', (req, res) => {
  const { all, events_too } = req.query
  let list: any[] = all === 'true' ? [...state.tasks] : state.tasks.filter(t => !t.done)
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
    t.done_at = new Date().toISOString()
    broadcast('tasks')
  }
  res.json({ ok: true })
})

app.post('/api/tasks/:id/undone', (req, res) => {
  const id = Number(req.params.id)
  const t = state.tasks.find(x => x.id === id)
  if (t) {
    t.done = 0
    delete t.done_at
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
// Сколько дней считаем: 0/не указано — вся история (период «всё»).
const finDays = (q: any) => Math.max(0, Number(q) || 0)
const finSince = (days: number) => {
  if (!days) return null
  const d = new Date(); d.setDate(d.getDate() - days)
  return d
}
const inPeriod = (iso: any, since: Date | null) => (!since || !iso || new Date(iso).getTime() >= since.getTime())

/* Обязательные платежи в месяц: подписки и аренда нормируются к месяцу,
   чтобы «свободно в месяц» считалось от реальных сумм, а не выдуманных. */
const recurringMonthly = (kind: string) => (state.recurring as any[])
  .filter(r => r.active !== false && (kind ? r.kind === kind : true))
  .reduce((s, r) => {
    const a = Number(r.amount) || 0
    const p = String(r.period || 'monthly').toLowerCase()
    if (/year|annual|год/.test(p)) return s + a / 12
    if (/week|нед/.test(p)) return s + a * 365 / 12 / 7
    return s + a
  }, 0)

app.get('/api/finance/summary', (req, res) => {
  const days = finDays(req.query.days)
  const since = finSince(days)
  const tx = state.transactions.filter(t => inPeriod(t.date, since))
  const balance = state.accounts.reduce((acc, a) => acc + (Number(a.balance) || 0), 0)
  const spent = Math.abs(tx.filter(t => Number(t.amount) < 0).reduce((acc, t) => acc + Number(t.amount), 0))
  const earned = tx.filter(t => Number(t.amount) > 0).reduce((acc, t) => acc + Number(t.amount), 0)

  // денежный поток считаем на полных 30 дней — независимо от выбранного периода просмотра
  const monthTx = state.transactions.filter(t => inPeriod(t.date, finSince(30)))
  const income30 = monthTx.filter(t => Number(t.amount) > 0).reduce((a, t) => a + Number(t.amount), 0)
  const recurring = Math.round(recurringMonthly('expense'))
  const debtPayments = (state.debts as any[]).filter(d => d.kind !== 'them_me').reduce((s, d) => s + (Number(d.monthly_payment) || 0), 0)
  const income = Math.round(income30)
  // без ограничения нулём: если обязательные платежи больше дохода — это важный сигнал, а не «0»
  const free = income - recurring - debtPayments

  res.json({
    total_balance: balance,
    spent,
    earned,
    debts_total: (state.debts as any[]).reduce((s, d) => s + Math.max(0, (Number(d.total) || 0) - (Number(d.paid) || 0)), 0),
    cashflow: {
      income,
      income_is_estimate: income === 0,
      recurring,
      debt_payments: debtPayments,
      free,
    },
    // старое имя — чтобы ничего не отвалилось у других потребителей
    balance,
    income_month: income,
    expense_month: Math.abs(state.transactions.filter(t => Number(t.amount) < 0).reduce((a, t) => a + Number(t.amount), 0)),
    accounts: state.accounts,
  })
})

// Реальные дневные суммы за период (раньше тут были случайные числа — график врал)
app.get('/api/finance/daily', (req, res) => {
  const days = finDays(req.query.days) || 30
  const list = []
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    const ds = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    const dayTx = state.transactions.filter(t => (t.date || '').slice(0, 10) === ds)
    list.push({
      date: ds,
      expense: Math.round(Math.abs(dayTx.filter(t => Number(t.amount) < 0).reduce((a, t) => a + Number(t.amount), 0))),
      income: Math.round(dayTx.filter(t => Number(t.amount) > 0).reduce((a, t) => a + Number(t.amount), 0)),
    })
  }
  res.json(list)
})

/* Прогноз кассы: прошлое — пересчёт баланса по операциям вперёд, будущее — средний темп
   плюс известные регулярные списания. Именно это рисуется на графике «касса на N дней». */
app.get('/api/finance/forecast', (req, res) => {
  const horizon = Math.max(7, finDays(req.query.days) || 30)
  const hist = Math.max(30, Math.min(horizon, 90))
  const balance = state.accounts.reduce((s, a) => s + (Number(a.balance) || 0), 0)
  const nowD = new Date()
  const dayKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

  // баланс в начале каждого прошедшего дня: вычитаем всё, что произошло позже
  const since = new Date(); since.setDate(since.getDate() - hist)
  const pastTx = state.transactions
    .filter(t => t.date && new Date(t.date).getTime() >= since.getTime())
    .slice().sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())

  const points: any[] = []
  for (let i = hist; i >= 0; i--) {
    const d = new Date(nowD); d.setDate(d.getDate() - i)
    const key = dayKey(d)
    // баланс на конец дня = текущий баланс − всё, что списалось/поступило после этого дня
    const after = pastTx.filter(t => (t.date || '').slice(0, 10) > key).reduce((s, t) => s + Number(t.amount || 0), 0)
    points.push({ date: key, balance: Math.round(balance - after), kind: 'past' })
  }

  const avgDaySpent = pastTx.filter(t => Number(t.amount) < 0).reduce((s, t) => s + Math.abs(Number(t.amount)), 0) / hist
  const avgDayIncome = pastTx.filter(t => Number(t.amount) > 0).reduce((s, t) => s + Number(t.amount), 0) / hist

  // регулярные платежи вперёд по календарю (сколько уже наступило на i-й день вперёд)
  const upcoming = (dayIndex: number) => {
    let delta = 0
    const today0 = new Date(nowD.getFullYear(), nowD.getMonth(), nowD.getDate())
    for (const r of (state.recurring as any[]).filter(r => r.active !== false)) {
      const dom = Number(r.day_of_month || r.day) || null
      if (!dom) continue
      let target = new Date(nowD.getFullYear(), nowD.getMonth(), Math.min(dom, 28))
      if (target < today0) target = new Date(nowD.getFullYear(), nowD.getMonth() + 1, Math.min(dom, 28))
      const diffDays = Math.round((target.getTime() - today0.getTime()) / 86_400_000)
      // ровно в тот день, когда платёж наступает — иначе сумма считалась бы заново каждый день после
      if (diffDays === dayIndex) {
        const a = Number(r.amount) || 0
        delta += r.kind === 'income' ? a : -a
      }
    }
    return delta
  }

  let bal = balance
  const startDate = new Date(nowD.getFullYear(), nowD.getMonth(), nowD.getDate())
  let runwayDays: number | null = null
  let minBalance = balance
  let minDate: string | null = dayKey(nowD)
  for (let i = 1; i <= horizon; i++) {
    const d = new Date(startDate); d.setDate(d.getDate() + i)
    bal = bal + avgDayIncome - avgDaySpent + upcoming(i)
    points.push({ date: dayKey(d), balance: Math.round(bal), kind: 'future' })
    if (bal < minBalance) { minBalance = bal; minDate = dayKey(d) }
    if (runwayDays === null && bal <= 0) runwayDays = i
  }

  res.json({
    points,
    horizon_days: horizon,
    avg_day_spent: Math.round(avgDaySpent),
    avg_day_income: Math.round(avgDayIncome),
    runway_days: runwayDays,
    min_balance: Math.round(minBalance),
    min_date: minDate,
    balance: Math.round(balance),
  })
})

/* Бюджеты: лимит живёт в категории (budget), потрачено — из операций текущего месяца. */
app.get('/api/finance/budgets', (req, res) => {
  const month = String(req.query.month || todayStr).slice(0, 7)
  const spent: Record<string, number> = {}
  for (const t of state.transactions) {
    if ((t.date || '').slice(0, 7) !== month) continue
    if (Number(t.amount) >= 0) continue
    const c = t.category || 'Другое'
    spent[c] = (spent[c] || 0) + Math.abs(Number(t.amount))
  }
  const items = (state.categories as any[])
    .filter(c => Number(c.budget) > 0 && c.kind !== 'income')
    .map(c => {
      const s = Math.round(spent[c.name] || 0)
      const budget = Math.round(Number(c.budget))
      const left = budget - s
      const pct = budget ? Math.round((s / budget) * 100) : 0
      return {
        category: c.name,
        budget,
        spent: s,
        left,
        pct,
        status: pct >= 100 ? 'over' : pct >= 80 ? 'warn' : 'ok',
        color: c.color || null,
        icon: c.icon || null,
      }
    })
    .sort((a, b) => b.pct - a.pct)
  const unbudgeted = Object.entries(spent)
    .filter(([name]) => !(state.categories as any[]).some(c => c.name === name && Number(c.budget) > 0))
    .map(([name, v]) => ({ category: name, spent: Math.round(v) }))
    .sort((a, b) => b.spent - a.spent)
  res.json({ month, items, unbudgeted, total_budget: items.reduce((s, i) => s + i.budget, 0), total_spent: items.reduce((s, i) => s + i.spent, 0) })
})

app.get('/api/finance/transactions', (req, res) => {
  const since = finSince(finDays(req.query.days))
  const list = state.transactions.filter(t => inPeriod(t.date, since))
  res.json(list)
})

/* Операция двигает баланс счёта. При правке/удалении нужно вернуть прошлое движение,
   иначе сумма на счёте «уезжала» и баланс переставал сходиться с операциями. */
const accountByName = (name?: string) =>
  name ? (state.accounts as any[]).find(a => a.name === name) || null : null
function moveBalance(tx: any, sign: 1 | -1) {
  const acc = accountByName(tx?.account) || (state.accounts as any[])[0]
  if (acc) acc.balance = (Number(acc.balance) || 0) + sign * (Number(tx?.amount) || 0)
}

app.post('/api/finance/transactions', (req, res) => {
  const tx = { id: ++nextId, date: new Date().toISOString(), ...req.body }
  state.transactions.unshift(tx)
  moveBalance(tx, 1)
  broadcast('finance')
  res.json(tx)
})

app.put('/api/finance/transactions/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.transactions.findIndex(t => t.id === id)
  if (idx !== -1) {
    const old = state.transactions[idx]
    const next = { ...old, ...req.body }
    moveBalance(old, -1)      // вернуть прежнее движение
    moveBalance(next, 1)      // записать новое
    state.transactions[idx] = next
    broadcast('finance')
    return res.json(state.transactions[idx])
  }
  res.status(404).json({ error: 'Transaction not found' })
})

app.delete('/api/finance/transactions/:id', (req, res) => {
  const id = Number(req.params.id)
  const tx = state.transactions.find(t => t.id === id)
  if (tx) moveBalance(tx, -1)
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
  const amount = Number(req.body.amount || 0)
  if (d) {
    d.paid = (d.paid || 0) + amount
    // платёж уходит с реального счёта — иначе «внесли 5 000», а баланс не изменился
    if (amount > 0 && req.body.account !== 'none') {
      const tx = {
        id: ++nextId,
        date: new Date().toISOString(),
        amount: -amount,
        category: 'Долги',
        account: req.body.account || undefined,
        comment: `Платёж по долгу: ${d.name || d.title || ''}`.trim(),
      }
      state.transactions.unshift(tx)
      moveBalance(tx, 1)
    }
    broadcast('finance')
  }
  res.json({ ok: true })
})
app.get('/api/finance/debts/:id/payments', (req, res) => res.json([]))

// поля «название/день» в форме называются name/day, а в данных — title/day_of_month:
// держим оба, иначе правка регулярного платежа сохранялась, но расчёт шёл по старому дню
const recurringNormalize = (r: any) => {
  if (r.name && !r.title) r.title = r.name
  if (r.title && !r.name) r.name = r.title
  if (r.day != null && !r.day_of_month) r.day_of_month = Number(r.day) || 1
  if (r.day_of_month != null && !r.day) r.day = Number(r.day_of_month) || 1
  if (!r.period) r.period = 'monthly'
  if (!r.kind) r.kind = 'expense'
  return r
}
app.get('/api/finance/recurring', (req, res) => res.json(state.recurring))
app.post('/api/finance/recurring', (req, res) => {
  const r = recurringNormalize({ id: ++nextId, active: true, ...req.body })
  state.recurring.push(r)
  broadcast('finance')
  res.json(r)
})
app.put('/api/finance/recurring/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.recurring.findIndex(r => r.id === id)
  if (idx !== -1) {
    state.recurring[idx] = recurringNormalize({ ...state.recurring[idx], ...req.body })
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

// в форме цель называется title/deadline, в сиде — name/due_date: нормализуем, иначе правка «терялась»
const goalNormalize = (g: any) => {
  if (g.title && !g.name) g.name = g.title
  if (g.name && !g.title) g.title = g.name
  if (g.deadline && !g.due_date) g.due_date = g.deadline
  if (g.due_date && !g.deadline) g.deadline = g.due_date
  return g
}
app.get('/api/finance/goals', (req, res) => res.json(state.goals))
app.post('/api/finance/goals', (req, res) => {
  const g = goalNormalize({ id: ++nextId, current: 0, ...req.body })
  state.goals.push(g)
  broadcast('finance')
  res.json(g)
})
app.put('/api/finance/goals/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.goals.findIndex(g => g.id === id)
  if (idx !== -1) {
    state.goals[idx] = goalNormalize({ ...state.goals[idx], ...req.body })
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
  const amount = Number(req.body.amount || 0)
  if (g) {
    g.current = (g.current || 0) + amount
    // отложили на копилку — деньги списались со счёта, иначе итог не сходится
    if (amount > 0 && req.body.account !== 'none') {
      const tx = {
        id: ++nextId,
        date: new Date().toISOString(),
        amount: -amount,
        category: 'Накопления',
        account: req.body.account || undefined,
        comment: `Отложено на цель: ${g.title || g.name || ''}`.trim(),
      }
      state.transactions.unshift(tx)
      moveBalance(tx, 1)
    }
    broadcast('finance')
  }
  res.json({ ok: true })
})
// Форма ответа — как в Python-ядре {buckets, compare, annual, payments, runway} (см. core/api/app.py:1435),
// иначе вкладка «техники» получает чужой объект и показывает пустоту/выдуманные цифры.
const BUCKET_RULES: { bucket: 'need' | 'save'; label: string; norm: number; cats: string[] }[] = [
  { bucket: 'need', label: 'обязательное', norm: 0.5, cats: ['Жильё', 'Еда', 'Транспорт', 'Здоровье', 'Аптека', 'Коммунальные', 'Связь', 'Образование', 'Дети', 'Питомцы'] },
  { bucket: 'save', label: 'накопления', norm: 0.2, cats: ['Накопления', 'Инвестиции', 'Страховка', 'Взнос', 'Подушка'] },
]
const bucketOf = (category: string): 'need' | 'want' | 'save' =>
  (BUCKET_RULES.find(r => r.cats.includes(category))?.bucket as 'need' | 'save' | undefined) || 'want'

app.get('/api/finance/techniques', (_req, res) => {
  const nowD = new Date()
  const ym = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  const thisM = ym(nowD)
  const prevM = ym(new Date(nowD.getFullYear(), nowD.getMonth() - 1, 1))
  const day = nowD.getDate()

  const tx = state.transactions
  const inMonth = (m: string) => tx.filter(t => (t.date || '').slice(0, 7) === m)
  const spentOf = (list: typeof tx) => list.filter(t => t.amount < 0)
  const incomeOf = (list: typeof tx) => list.filter(t => t.amount > 0)
  const sumAbs = (list: typeof tx) => list.reduce((s, t) => s + Math.abs(t.amount), 0)

  const spentThis = spentOf(inMonth(thisM))
  const spentPrev = spentOf(inMonth(prevM))
  const incomeThis = incomeOf(inMonth(thisM))
  const incomePrev = incomeOf(inMonth(prevM))
  const base = sumAbs(spentThis)
  const income = sumAbs(incomeThis)

  // --- 50/30/20 ---
  let buckets: any = null
  if (base > 0) {
    const by: Record<string, number> = { need: 0, want: 0, save: 0 }
    for (const t of spentThis) by[bucketOf(t.category)] += Math.abs(t.amount)
    const wantRule = { bucket: 'want', label: 'хотелки', norm: 0.3 }
    buckets = {
      base,
      income,
      unassigned: 0,
      unassigned_cats: [],
      buckets: [...BUCKET_RULES, wantRule].map(r => {
        const amount = by[r.bucket] || 0
        const share = amount / base
        return {
          bucket: r.bucket,
          label: r.label,
          amount,
          share,
          norm: r.norm,
          status: share > r.norm * 1.15 ? 'over' : share < r.norm * 0.7 ? 'low' : 'ok',
        }
      }),
    }
  }

  // --- месяц к месяцу ---
  const perCat = (list: typeof tx) => {
    const m = new Map<string, number>()
    for (const t of list) m.set(t.category, (m.get(t.category) || 0) + Math.abs(t.amount))
    return m
  }
  const cur = perCat(spentThis), prev = perCat(spentPrev)
  const cats = [...new Set([...cur.keys(), ...prev.keys()])].map(name => {
    const current = cur.get(name) || 0
    const prev_same = prev.get(name) || 0
    return { category: name, current, prev_same, delta: current - prev_same, delta_pct: prev_same ? (current - prev_same) / prev_same : 0 }
  }).sort((a, b) => b.current - a.current)
  const compare = base || sumAbs(spentPrev) ? {
    day,
    spent: base,
    spent_prev_same: sumAbs(spentPrev),
    avg_check: spentThis.length ? Math.round(base / spentThis.length) : 0,
    avg_check_prev: spentPrev.length ? Math.round(sumAbs(spentPrev) / spentPrev.length) : 0,
    earned: income,
    earned_prev: sumAbs(incomePrev),
    categories: cats,
  } : null

  // --- на сколько хватит ---
  const balance = state.accounts.reduce((s, a) => s + (a.balance || 0), 0)
  const perDayAvg = day > 0 ? Math.round(base / day) : 0
  const freeRec = state.recurring.filter(r => r.active !== false && r.kind === 'expense')
  const free = balance - freeRec.reduce((s, r) => s + (r.amount || 0), 0)
  const daysLeftToIncome = 14   // в демо нет даты ближайшего дохода — честно считаем от горизонта
  const runway_days = perDayAvg > 0 ? Math.floor(balance / perDayAvg) : null
  const runway = {
    runway_days,
    ok: runway_days != null && runway_days >= daysLeftToIncome,
    days_left_to_income: daysLeftToIncome,
    safe_per_day: daysLeftToIncome > 0 ? Math.floor(balance / daysLeftToIncome) : balance,
    free: Math.max(0, free),
    per_day_avg: perDayAvg,
  }

  // --- годовые платежи ---
  const yearly = state.recurring.filter(r => r.active !== false && /year|annual|год/i.test(r.period || ''))
  const annual = {
    total_year: yearly.reduce((s, r) => s + (r.amount || 0), 0),
    per_month: Math.round(yearly.reduce((s, r) => s + (r.amount || 0), 0) / 12),
    items: yearly.map(r => ({
      title: r.title,
      amount: r.amount,
      next: new Date(nowD.getFullYear(), nowD.getMonth() + 1, r.day_of_month || 1).toISOString(),
      months: 1,
    })),
  }

  // --- хватит ли на платежи ---
  const horizon = 7
  const need = freeRec.filter(r => (r.day_of_month || 1) <= day + horizon).reduce((s, r) => s + (r.amount || 0), 0)
  const incoming = state.recurring.filter(r => r.active !== false && r.kind === 'income')
    .map(r => ({ amount: r.amount, title: r.title }))
  const payments = {
    days: horizon,
    need,
    balance,
    short: Math.max(0, need - balance),
    payments: freeRec.filter(r => (r.day_of_month || 1) <= day + horizon).map(r => ({ title: r.title })),
    incoming,
  }

  res.json({ buckets, compare, annual, payments, runway })
})

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
  const n = Math.min(24, Math.max(1, Number(req.query.months) || 6))
  const now = new Date()
  const since = new Date(now.getFullYear(), now.getMonth() - (n - 1), 1)
  const monthKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  const dayKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const OPEN = ['new', 'work', 'review']
  const UNPAID = ['work', 'review', 'done']
  const orders: any[] = state.orders as any[]

  // доход по месяцам — только деньги, записанные по заказам
  const byMonth: Record<string, number> = {}
  for (const o of orders) {
    const paid = Number(o.paid) || 0
    if (paid <= 0) continue
    const d = new Date(o.created_at || now)
    byMonth[isNaN(d.getTime()) ? monthKey(now) : monthKey(d)] = (byMonth[isNaN(d.getTime()) ? monthKey(now) : monthKey(d)] || 0) + paid
  }
  const months: { month: string; income: number }[] = []
  for (const cur = new Date(since); cur <= now; cur.setMonth(cur.getMonth() + 1)) {
    const k = monthKey(cur)
    months.push({ month: k, income: Math.round(byMonth[k] || 0) })
  }

  const weekAgo = now.getTime() - 7 * 86_400_000
  const byClient = new Map<string, any>()
  let totalHours = 0
  let weekHours = 0
  let totalPaid = 0
  for (const o of orders) {
    const name = o.client || 'без клиента'
    let b = byClient.get(name)
    if (!b) { b = { client: name, orders: 0, paid: 0, total: 0, hours: 0, open: 0, unpaid: 0 }; byClient.set(name, b) }
    const paid = Number(o.paid) || 0
    const price = Number(o.price ?? o.total) || 0
    let hours = 0
    for (const e of (o.time_entries || []) as any[]) {
      const min = Number(e.duration_min) || 0
      hours += min / 60
      const t = new Date(e.date || now).getTime()
      if (!Number.isNaN(t) && t >= weekAgo) weekHours += min / 60
    }
    if (!hours) hours = Number(o.hours) || 0
    b.orders += 1
    b.paid += paid
    if (o.status !== 'cancelled') b.total += price
    if (OPEN.includes(o.status)) b.open += 1
    if (UNPAID.includes(o.status)) b.unpaid += Math.max(0, price - paid)
    b.hours += hours
    totalHours += hours
    totalPaid += paid
  }
  const clients = [...byClient.values()]
    .map((b: any) => ({
      ...b,
      rate: b.hours >= 1 ? Math.round(b.paid / b.hours) : null,
      paid: Math.round(b.paid), total: Math.round(b.total), unpaid: Math.round(b.unpaid),
      hours: Math.round(b.hours * 10) / 10,
    }))
    .sort((a: any, b: any) => b.paid - a.paid)
    .slice(0, 12)

  const done = orders.filter(o => ['done', 'paid'].includes(o.status))
  const leads = done.map(o => Math.max(0, Math.round((now.getTime() - new Date(o.created_at || now).getTime()) / 86_400_000)))
  const focus_days: { date: string; min: number }[] = []
  for (let i = 13; i >= 0; i--) {
    const iso = dayKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() - i))
    let min = 0
    for (const o of orders) for (const e of (o.time_entries || []) as any[]) {
      if (dayKey(new Date(e.date || now)) === iso) min += Number(e.duration_min) || 0
    }
    focus_days.push({ date: iso, min: Math.round(min) })
  }

  res.json({
    months,
    clients,
    total_income: Math.round(totalPaid),
    total_hours: Math.round(totalHours * 10) / 10,
    rate: totalHours >= 1 ? Math.round(totalPaid / totalHours) : null,
    avg_check: done.length ? Math.round(done.reduce((s, o) => s + (Number(o.price ?? o.total) || 0), 0) / done.length) : null,
    avg_lead_days: leads.length ? Math.round((leads.reduce((a, b) => a + b, 0) / leads.length) * 10) / 10 : null,
    open: orders.filter(o => OPEN.includes(o.status)).length,
    unpaid: Math.round(orders.filter(o => UNPAID.includes(o.status)).reduce((s, o) => s + Math.max(0, (Number(o.price ?? o.total) || 0) - (Number(o.paid) || 0)), 0)),
    week_load_h: Math.round(weekHours * 10) / 10,
    focus_days,
  })
})
app.get('/api/orders/:id', (req, res) => {
  const id = Number(req.params.id)
  const o = state.orders.find(x => x.id === id)
  if (o) return res.json(o)
  res.status(404).json({ error: 'Order not found' })
})
app.post('/api/orders', (req, res) => {
  const body = { ...req.body }
  const price = Number(body.price ?? body.total) || 0
  delete body.price
  delete body.total
  const o: any = { id: ++nextId, created_at: new Date().toISOString(), status: 'new', ...body, price, total: price }
  orderMoney(o)
  state.orders.unshift(o)
  broadcast('orders')
  res.json(o)
})
app.put('/api/orders/:id', (req, res) => {
  const id = Number(req.params.id)
  const idx = state.orders.findIndex(o => o.id === id)
  if (idx !== -1) {
    const o: any = { ...state.orders[idx], ...req.body }
    orderMoney(o)
    state.orders[idx] = o
    broadcast('orders')
    broadcast('events')   // дедлайн заказа показан в календаре — статус должен обновиться там же
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
    app_name: 'Марвин',
    version: PKG_VERSION,
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
app.get('/api/people/kinds', (req, res) => res.json(state.peopleKinds))
app.delete('/api/people/kinds/:k', (req, res) => {
  const k = req.params.k
  const before = state.peopleKinds.length
  state.peopleKinds = state.peopleKinds.filter(x => x !== k)
  if (state.peopleKinds.length === before) return res.status(404).json({ detail: 'Категории нет' })
  // людей этой категории не трогаем (как в Python-ядре) — только убираем из списка
  broadcast('people')
  res.json({ ok: true })
})
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
  const ids = new Set(nodes.map(n => n.id))
  // фронт читает data.edges (см. src/components/Graph.jsx), а не links
  const edges = [
    { source: 'p_1', target: 'o_1' },
    { source: 'p_2', target: 'o_2' },
    { source: 'n_1', target: 'o_1' },
  ].filter(e => ids.has(e.source) && ids.has(e.target))
  res.json({
    nodes,
    edges,
    stats: {
      people: state.people.length,
      notes: state.notes.length,
      links: state.links.length,
      edges: edges.length,
      // Graph.jsx показывает «без связей: N» — считаем по тем же узлам
      lonely: nodes.filter(n => !edges.some(e => e.source === n.id || e.target === n.id)).length,
    },
  })
})
app.get('/api/graph/backlinks/:kind/:id', (req, res) => res.json({ links: [] }))

// Facts, Style & Memory
// фронт ждёт объект { items, stats, enabled, categories } (src/pages/Memory.jsx), а не массив
app.get('/api/facts', (req, res) => {
  const items = state.facts.map(f => ({
    core: false,
    updated_at: f.created_at,
    ...f,
    layer: f.active === false ? 'archive' : (['short', 'long', 'archive'].includes(f.layer) ? f.layer : 'long'),
  }))
  const count = (l: string) => items.filter(f => f.layer === l).length
  res.json({
    items,
    stats: {
      short: count('short'),
      long: count('long'),
      archive: count('archive'),
      style: state.memoryStyle.style,
      style_at: state.memoryStyle.style_at,
    },
    enabled: true,
    categories: [],
  })
})
app.post('/api/facts', (req, res) => {
  const f = { id: ++nextId, created_at: new Date().toISOString(), active: true, ...req.body }
  state.facts.push(f)
  res.json(f)
})
// «как вы пишете»: раньше PUT молча выбрасывал текст, правка терялась при перезагрузке.
// Важно: регистрируется ДО /api/facts/:id, иначе Express ловит «style» как id.
app.put('/api/facts/style', (req, res) => {
  const text = req.body?.text
  if (typeof text !== 'string') return res.status(400).json({ detail: 'text must be a string' })
  state.memoryStyle = { style: text, style_at: new Date().toISOString() }
  broadcast('settings')
  res.json({ ok: true, style: state.memoryStyle.style, style_at: state.memoryStyle.style_at })
})
// пересборка портрета/стиля и ночной разбор требуют LLM — их в Node-демо нет
app.post('/api/facts/portrait', (_req, res) => {
  res.status(501).json({ detail: 'Пересборка портрета работает только в Python-ядре (start.bat)' })
})
app.post('/api/facts/nightly', (_req, res) => {
  res.status(501).json({ detail: 'Ночной разбор памяти работает только в Python-ядре (start.bat)' })
})
app.post('/api/facts/style', (_req, res) => {
  res.status(501).json({ detail: 'Автосборка стиля работает только в Python-ядре (start.bat)' })
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
app.get('/api/lessons', (req, res) => res.json([]))
app.delete('/api/lessons/:id', (req, res) => res.status(404).json({ detail: 'Уроков в этом стеке нет' }))
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
// Каталог редактируемых ключей — зеркало EDITABLE из core/config.py. Страница настроек строит
// секции по префиксам ключа и ждёт у каждого пункта {key, type, label, secret, value, set}.
const SETTING_DEFS: Array<[string, 'str' | 'int' | 'bool', string, boolean]> = [
  ['assistant.name', 'str', 'Имя ассистента (так он представляется и откликается голосом)', false],
  ['assistant.name_latin', 'str', 'Имя латиницей (заголовки окон, логи)', false],
  ['assistant.aliases', 'str', 'Другие варианты имени через запятую', false],
  ['owner.name', 'str', 'Как к вам обращаться («сэр», «босс», имя; пусто — без обращения)', false],
  ['owner.city', 'str', 'Ваш город', false],
  ['owner.timezone', 'str', 'Часовой пояс (Europe/Moscow)', false],
  ['telegram.token', 'str', 'Токен Telegram-бота (от @BotFather)', true],
  ['telegram.owner_id', 'int', 'Ваш Telegram ID (от @userinfobot)', false],
  ['telegram.morning_digest', 'str', 'Утренний дайджест (ЧЧ:ММ, пусто — выключить)', false],
  ['telegram.proxy', 'str', 'Прокси для Telegram (если api.telegram.org недоступен)', false],
  ['telegram.webapp_url', 'str', 'Адрес сайта для приложения в Telegram (https://…ts.net из funnel.bat)', false],
  ['notifications.quiet_from', 'int', 'Тихие часы: с (час 0–23) — ночью ассистент сам не пишет', false],
  ['notifications.quiet_to', 'int', 'Тихие часы: до (час 0–23)', false],
  ['notifications.proactive_enabled', 'bool', 'Сам напоминает о том, что заметил (просрочка оплаты, дело без срока, самочувствие)', false],
  ['notifications.proactive_per_day', 'int', 'Не больше стольких инициативных сообщений в день (5)', false],
  ['notifications.proactive_vibe', 'bool', 'Просто написать днём (как дела / шутка), если тихо 5+ часов', false],
  ['brain.mode', 'str', 'Режим мозга: local / hybrid / cloud', false],
  ['brain.ollama.url', 'str', 'Адрес Ollama', false],
  ['brain.ollama.model', 'str', 'Модель Ollama', false],
  ['brain.ollama.embed_model', 'str', 'Модель эмбеддингов (смысловой поиск)', false],
  ['brain.ollama.small_model', 'str', 'Малая модель для мини-задач (судья «трата или заказ», уборка памяти): qwen2.5:1.5b — пусто = основная', false],
  ['brain.ollama.small_keep_alive', 'str', 'Сколько малая модель живёт в видеопамяти после задачи (5m; 0 — выгружать сразу)', false],
  ['brain.ollama.vision_model', 'str', 'Модель зрения (скриншоты, чеки): qwen2.5vl:3b / llava / moondream — пусто, если не ставили', false],
  ['brain.ollama.num_ctx', 'int', 'Размер контекста локальной модели', false],
  ['brain.ollama.keep_alive', 'str', 'Держать модель в памяти после ответа (2h / 0)', false],
  ['brain.vision.where', 'str', 'Где смотреть картинки: auto (ПК, при сбое — облако; чеки только ПК) / cloud (всегда облако, быстро) / local (только ПК)', false],
  ['brain.vision.allow_cloud', 'bool', 'Скриншоты «что на экране» можно отправлять в облако, если нет локальной модели зрения (чеки — никогда)', false],
  ['brain.cloud.provider', 'str', 'Провайдер облака', false],
  ['brain.cloud.api_key', 'str', 'Ключ облака', true],
  ['brain.cloud.model', 'str', 'Модель облака (пусто — по умолчанию у провайдера)', false],
  ['brain.cloud.base_url', 'str', 'Адрес API (только для custom)', false],
  ['brain.cloud.proxy', 'str', 'Прокси для облака (обычно не нужен)', false],
  ['brain.gemini.auto', 'bool', 'Разговор и общие вопросы — в облако (иначе только по слову «облако, …»)', false],
  ['brain.gemini.api_key', 'str', 'Ключ Google Gemini (только если провайдер gemini)', true],
  ['brain.gemini.model', 'str', 'Модель Google Gemini (auto)', false],
  ['brain.gemini.proxy', 'str', 'Прокси для Google Gemini', false],
  ['brain.gemini.anonymize', 'bool', 'Обезличивать текст перед отправкой в облако', false],
  ['brain.gemini.mark_source', 'bool', 'Помечать источник ответа (⚡/🧠/☁️)', false],
  ['brain.sorter.where', 'str', 'Кто разбирает сообщения-списки на записи: cloud (облако, надёжнее; текст уходит целиком) / local (только ПК) / auto (ПК, при сбое облако)', false],
  ['brain.sorter.confirm', 'bool', 'Списки: сначала показать, как понял, и ждать «да» (иначе записывать сразу — «отмени» откатит всю пачку)', false],
  ['brain.memory.enabled', 'bool', 'Память о вас: запоминать факты из разговора, подтягивать нужное в ответы, портрет', false],
  ['brain.memory.where', 'str', 'Кто извлекает и обобщает факты: cloud (облако, при сбое ПК) / auto (ПК, при сбое облако) / local (только ПК). Поиск по памяти — всегда ПК', false],
  ['brain.memory.short_days', 'int', 'Сколько дней факт живёт в «сейчас», прежде чем стать постоянным или уйти в архив', false],
  ['brain.judge.enabled', 'bool', 'Судья: спорную фразу («сайт 15000», «отдал Ване 2000») перед записью решает нейронка, а не шаблон', false],
  ['brain.judge.where', 'str', 'Кто судит: local (малая/основная модель на ПК; по умолчанию) / cloud (облако, при сбое ПК) / auto (ПК, при сбое облако)', false],
  ['brain.relations.enabled', 'bool', 'Связи между записями в Мозге («связано:» в карточке, смысловые линии в графе)', false],
  ['brain.relations.where', 'str', 'Кто решает, связаны ли записи: cloud (облако, при сбое ПК) / auto (ПК, при сбое облако) / local (только ПК). Кандидатов всегда отбирает ПК', false],
  ['voice.enabled', 'bool', 'Голосовые сообщения в Telegram распознавать', false],
  ['voice.stt.model', 'str', 'Модель распознавания Whisper: tiny / base / small / medium (точнее, но медленнее)', false],
  ['voice.stt.cloud', 'bool', 'Распознавать речь через Groq Whisper (~1 с, но голос уходит в облако; нужен провайдер groq)', false],
  ['voice.stt.device', 'str', 'Устройство Whisper: cpu / cuda', false],
  ['voice.tts.engine', 'str', 'Голос: silero (офлайн) / edge (онлайн, Microsoft) / off', false],
  ['voice.tts.speaker', 'str', 'Голос Silero: eugene / aidar (муж.), baya / kseniya / xenia (жен.)', false],
  ['voice.tts.edge_voice', 'str', 'Голос Microsoft (если engine = edge)', false],
  ['voice.tts.reply_in_telegram', 'str', 'Голосовые ответы в Telegram: never (только текст) / voice (голосом на голосовые) / always', false],
  ['voice.pc.hotkey', 'str', 'Голос на ПК: горячая клавиша «слушать» (voice.bat)', false],
  ['voice.pc.mic', 'str', 'Голос на ПК: микрофон (пусто — по умолчанию; номер из «voice.bat --mics»)', false],
  ['voice.pc.silence_sec', 'str', 'Голос на ПК: пауза в речи (сек), после которой команда считается сказанной. 0.8 — быстро, 1.5–2 — если обрывает на раздумьях', false],
  ['voice.pc.max_command_sec', 'int', 'Голос на ПК: максимальная длина одной команды, секунд', false],
  ['voice.pc.conversation_sec', 'int', 'Голос на ПК: сколько секунд после ответа можно говорить без имени ассистента (0 — только после его вопросов)', false],
  ['voice.pc.conversation_mode_sec', 'int', 'Голос на ПК: окно в «режиме беседы» («<имя>, режим беседы» / «хватит болтать»), секунд', false],
  ['voice.pc.morning_report', 'bool', 'Голос на ПК: утренний доклад вслух, когда впервые сели за компьютер', false],
  ['voice.pc.night_from', 'int', 'Ночной режим с (час): тише и без лишних напоминаний вслух', false],
  ['voice.pc.night_to', 'int', 'Ночной режим до (час)', false],
  ['voice.pc.filler_sec', 'str', 'Через сколько секунд молчания мозга сказать «Секунду…» (0 — никогда)', false],
  ['voice.pc.screen_time.enabled', 'bool', 'Экранное время: сколько и где вы за ПК — карточка на «Сегодня», «сколько сидел за компом», строка в вечернем итоге. Только имя программы и сайт, всё локально. Нужен перезапуск voice.bat', false],
  ['voice.pc.screen_time.idle_min', 'int', 'Экранное время: минут без мыши/клавиатуры = «отошёл» (5)', false],
  ['voice.pc.screen_time.nudges', 'bool', 'Экранное время: редкие подколы по факту (YouTube час подряд при дедлайне, игра в рабочее время, 6 ч без перерыва)', false],
  ['voice.pc.screen_time.keep_days', 'int', 'Экранное время: сколько дней хранить подробности (90)', false],
  ['voice.pc.tidy_downloads_days', 'int', 'Ночная уборка «Загрузок» (voice.bat): файлы старше N дней — в Загрузки/Разобрано; 0 — выключено. Рабочий стол — только по команде', false],
  ['voice.pc.games', 'str', 'Свои игры для авто-игрового режима: имена exe через запятую (популярные знаю сам)', false],
  ['google.enabled', 'bool', 'Отправлять события в Google Календарь (только ассистент → Google)', false],
  ['google.client_id', 'str', 'Google OAuth Client ID (…apps.googleusercontent.com) — см. README «Google Календарь»', false],
  ['google.client_secret', 'str', 'Google OAuth Client secret', true],
  ['google.calendar_id', 'str', 'ID календаря в Google (пусто — основной)', false],
  ['google.proxy', 'str', 'Прокси для Google (пусто — берётся прокси Telegram, если задан)', false],
  ['backup.enabled', 'bool', 'Ежедневный бэкап базы', false],
  ['backup.dir', 'str', 'Папка бэкапов', false],
  ['backup.extra_dir', 'str', 'Вторая копия (другой диск / папка Яндекс.Диска)', false],
  ['backup.keep_days', 'int', 'Хранить бэкапы, дней', false],
  ['finance.main_account', 'str', 'Основной счёт', false],
  ['persona.style', 'str', 'Характер: swag (с юмором) / neutral (по делу)', false],
  ['persona.humor_level', 'int', 'Уровень юмора 0–10 (0–2 без шуток, 6–8 сарказм по делу, 9–10 жёстко)', false],
  ['persona.nicknames', 'str', 'Как ещё вас звать, через запятую («шеф, босс»)', false],
  ['persona.where', 'str', 'Кто формулирует инициативные фразы: cloud / auto / local', false],
  ['persona.voice_accents', 'bool', 'Итог дня и подколы иногда голосовым (не чаще раза в день)', false],
  ['server.port', 'int', 'Порт сайта (нужен перезапуск)', false],
  ['setup.done', 'bool', 'Мастер первого запуска пройден', false],
  // демо-ключи, которые раньше лежали прямо в state.settings
  ['currency', 'str', 'Знак валюты', false],
  ['freelance.hourly_rate', 'int', 'Ставка в час', false],
  ['pomodoro.focus_min', 'int', 'Помодоро: фокус, минут', false],
  ['pomodoro.short_break_min', 'int', 'Помодоро: короткий перерыв, минут', false],
  ['pomodoro.long_break_min', 'int', 'Помодоро: длинный перерыв, минут', false],
]
const SETTING_BY_KEY: Record<string, { type: 'str' | 'int' | 'bool'; secret: boolean }> = {}
for (const [key, type, , secret] of SETTING_DEFS) SETTING_BY_KEY[key] = { type, secret }

// секрет маскируется при показе — иначе ключ лежал бы открытым в ответе API
function maskSecret(raw: any): string {
  const s = String(raw ?? '')
  if (!s) return ''
  return s.length > 8 ? s.slice(0, 4) + '…' + s.slice(-3) : '•••'
}

function settingsItems() {
  const stored = new Map<string, any>(state.settings.map(s => [s.key, s.value] as [string, any]))
  const known = new Set<string>()
  const items: any[] = SETTING_DEFS.map(([key, type, label, secret]) => {
    known.add(key)
    const set = stored.has(key) && !!stored.get(key)
    const raw = stored.has(key) ? stored.get(key) : (type === 'str' ? '' : type === 'int' ? 0 : false)
    return { key, type, label, secret, value: secret ? maskSecret(raw) : raw, set }
  })
  // ключи из сохранённого состояния, которых нет в каталоге — отдаём как есть, чтобы не терять
  for (const s of state.settings) {
    if (known.has(s.key)) continue
    const t = typeof s.value === 'number' ? 'int' : typeof s.value === 'boolean' ? 'bool' : 'str'
    items.push({ key: s.key, type: t, label: s.key, secret: false, value: s.value, set: true })
  }
  return items
}

app.get('/api/settings', (_req, res) => {
  res.json({ items: settingsItems() })
})
app.put('/api/settings', (req, res) => {
  const changes = req.body?.changes
  // без changes — пустой сейв (фронт шлёт {changes}); 400 только если changes есть, но не объект
  if (changes !== undefined && (changes === null || typeof changes !== 'object' || Array.isArray(changes))) {
    return res.status(400).json({ detail: 'changes must be an object' })
  }
  const list: Record<string, any> = changes || {}
  const changed: string[] = []
  for (const [key, value] of Object.entries(list)) {
    const def = SETTING_BY_KEY[key]
    if (def?.secret) {
      // маска или пустое поле — секрет не трогаем (так же, как core/config.write_settings)
      const s = String(value ?? '')
      if (!s || s.includes('…') || s === '•••') continue
    }
    let v: any = value
    if (def?.type === 'int') {
      const n = parseInt(String(value ?? '').trim(), 10)
      if (Number.isNaN(n)) continue
      v = n
    } else if (def?.type === 'bool') {
      v = ['1', 'true', 'yes', 'on', 'да'].includes(String(value ?? '').toLowerCase())
    } else if (def?.type === 'str') {
      v = value == null ? '' : String(value)
    }
    const existing = state.settings.find(s => s.key === key)
    if (existing) existing.value = v
    else state.settings.push({ key, value: v })
    changed.push(key)
  }
  broadcast('settings')
  // фронт читает r.changed.length (src/pages/Settings.jsx)
  res.json({ changed, restart: false })
})

// ----------------- UI PREFS (зеркало localStorage между устройствами) -----------------
app.get('/api/ui-prefs', (_req, res) => {
  res.json({ prefs: state.uiPrefs || {} })
})
app.put('/api/ui-prefs', (req, res) => {
  const prefs = req.body?.prefs
  if (!prefs || typeof prefs !== 'object' || Array.isArray(prefs)) {
    return res.status(400).json({ detail: 'prefs must be an object' })
  }
  state.uiPrefs = { ...(state.uiPrefs || {}), ...prefs }
  broadcast('ui_prefs', { prefs: state.uiPrefs, origin: req.header('X-Client-Id') || '' })
  res.json({ ok: true })
})

// ----------------- EXPORT (раньше ссылки уходили в SPA-fallback и отдавали HTML) -----------------
function csvText(rows: any[], cols: string[]): string {
  const esc = (v: any) => {
    const s = v == null ? '' : Array.isArray(v) ? v.join('; ') : String(v)
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
  }
  return [cols.join(','), ...rows.map(r => cols.map(c => esc(r[c])).join(','))].join('\r\n')
}
function sendCsv(filename: string, getRows: () => any[], cols: string[]) {
  return (_req: express.Request, res: express.Response) => {
    res.setHeader('Content-Type', 'text/csv; charset=utf-8')
    res.setHeader('Content-Disposition', `attachment; filename="${filename}"`)
    res.send('﻿' + csvText(getRows(), cols))   // BOM — чтобы Excel читал кириллицу
  }
}
app.get('/api/export/transactions.csv', sendCsv('transactions.csv', () => state.transactions, ['date', 'amount', 'category', 'account', 'comment']))
app.get('/api/export/events.csv', sendCsv('events.csv', () => state.events, ['title', 'start', 'end', 'location', 'notes', 'repeat', 'done']))
app.get('/api/export/tasks.csv', sendCsv('tasks.csv', () => state.tasks, ['title', 'due', 'priority', 'done', 'category']))
app.get('/api/export/notes.csv', sendCsv('notes.csv', () => state.notes, ['text', 'tags', 'created_at']))
app.get('/api/export/all.json', (_req, res) => {
  res.setHeader('Content-Disposition', 'attachment; filename="marvin-export.json"')
  res.json(state)
})

// ----------------- BOARD ASSETS (картинки на досках) -----------------
// Раньше роута не было: FormData уходил в SPA-fallback и фронт получал HTML вместо JSON.
const ASSET_DIR = path.resolve(process.cwd(), 'data', 'board-assets')
const assetUpload = multer({
  storage: multer.diskStorage({
    destination: (_req, _file, cb) => { fs.mkdirSync(ASSET_DIR, { recursive: true }); cb(null, ASSET_DIR) },
    filename: (_req, file, cb) => {
      const ext = (path.extname(file.originalname) || '.png').toLowerCase().replace(/[^.a-z0-9]/g, '')
      cb(null, `${Date.now()}-${Math.random().toString(36).slice(2, 8)}${ext}`)
    },
  }),
  limits: { fileSize: 8 * 1024 * 1024 },
  fileFilter: (_req, file, cb) => cb(null, file.mimetype.startsWith('image/')),
})

/** Размеры картинки без сторонних библиотек: PNG (IHDR) и JPEG (SOF-маркеры). */
function imageSize(buf: Buffer): { w: number; h: number } | null {
  if (buf.length > 24 && buf.readUInt32BE(0) === 0x89504e47) {
    return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) }   // PNG
  }
  if (buf.length > 10 && buf[0] === 0xff && buf[1] === 0xd8) {     // JPEG
    let i = 2
    while (i + 9 < buf.length) {
      if (buf[i] !== 0xff) { i++; continue }
      const marker = buf[i + 1]
      if (marker === 0xd8 || marker === 0xd9 || (marker >= 0xd0 && marker <= 0xd7)) { i += 2; continue }
      if (buf[i + 2] === 0xff) { i += 2; continue }                // заполнитель
      const len = buf.readUInt16BE(i + 2)
      const isSOF = marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc
      if (isSOF) return { h: buf.readUInt16BE(i + 5), w: buf.readUInt16BE(i + 7) }
      i += 2 + len
    }
  }
  return null
}

app.post('/api/boards/:id/asset', assetUpload.single('file'), (req, res) => {
  const board = state.boards.find(b => b.id === Number(req.params.id))
  if (!board) return res.status(404).json({ detail: 'Доска не найдена' })
  if (!req.file) return res.status(400).json({ detail: 'Нужен файл-картинка (поле file)' })
  let dim: { w: number; h: number } | null = null
  try { dim = imageSize(fs.readFileSync(req.file.path)) } catch {}
  if (!dim) { try { fs.unlinkSync(req.file.path) } catch {} return res.status(400).json({ detail: 'Не удалось прочитать картинку' }) }
  res.json({ src: `/api/boards/${board.id}/asset/${req.file.filename}`, w: dim.w, h: dim.h })
})
app.get('/api/boards/:id/asset/:name', (req, res) => {
  const file = path.join(ASSET_DIR, path.basename(req.params.name))
  if (!fs.existsSync(file)) return res.status(404).json({ detail: 'Файл не найден' })
  res.sendFile(file)
})

// Telegram & Device Auth
const TG_TOKEN = process.env.TELEGRAM_BOT_TOKEN || process.env.ASSISTANT_TG_TOKEN || ''

/** Проверка подписи initData по документации Telegram (HMAC-SHA256, ключ «WebAppData»). */
function verifyTelegramInitData(initData: string, token: string): boolean {
  const params = new URLSearchParams(initData)
  const hash = params.get('hash')
  if (!hash) return false
  const authDate = Number(params.get('auth_date') || 0)
  if (authDate && Date.now() / 1000 - authDate > 86400) return false   // старше суток — не принимаем
  params.delete('hash')
  params.delete('signature')
  const check = [...params.entries()].map(([k, v]) => `${k}=${v}`).sort().join('\n')
  const secret = createHmac('sha256', 'WebAppData').update(token).digest()
  const calc = createHmac('sha256', secret).update(check).digest('hex')
  if (calc.length !== hash.length) return false
  return timingSafeEqual(Buffer.from(calc), Buffer.from(hash))
}

app.post('/api/tg/login', (req, res) => {
  if (!TG_TOKEN) {
    // честнее молчаливого «вы вошли»: без токена подпись проверить нечем
    return res.status(501).json({ detail: 'Telegram-вход не настроен: задайте TELEGRAM_BOT_TOKEN' })
  }
  const { init_data } = req.body ?? {}
  if (typeof init_data !== 'string' || !verifyTelegramInitData(init_data, TG_TOKEN)) {
    return res.status(401).json({ detail: 'Подпись Telegram не совпала — вход закрыт' })
  }
  let name = 'Владелец'
  try {
    const user = JSON.parse(new URLSearchParams(init_data).get('user') || '{}')
    if (user?.first_name) name = user.first_name
  } catch {}
  res.json({ ok: true, name })
})

// Phone access / Tailscale QR
/* QR-код для ссылки доступа: SVG в data-URI — тот же вид, что и в Python-версии (segno). */
function qrDataUri(url: string): string {
  try {
    const qr = qrcode(0, 'M')
    qr.addData(url)
    qr.make()
    const n = qr.getModuleCount()
    const quiet = 2
    const cell = 4
    const size = (n + quiet * 2) * cell
    let d = ''
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) {
        if (!qr.isDark(r, c)) continue
        const x = (c + quiet) * cell
        const y = (r + quiet) * cell
        d += `M${x} ${y}h${cell}v${cell}h${-cell}z`
      }
    }
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" shape-rendering="crispEdges"><rect width="${size}" height="${size}" fill="#ffffff"/><path d="${d}" fill="#1c1c1e"/></svg>`
    return `data:image/svg+xml;base64,${Buffer.from(svg, 'utf8').toString('base64')}`
  } catch {
    return ''
  }
}
/* IP компьютера: Tailscale — через их CLI, домашняя сеть — из сетевых интерфейсов. */
function tailscaleIp(): string | null {
  const exes = process.platform === 'win32'
    ? [path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Tailscale', 'tailscale.exe'), 'tailscale']
    : ['tailscale']
  for (const exe of exes) {
    try {
      const out = execFileSync(exe, ['ip', '-4'], { encoding: 'utf8', timeout: 4000 })
      const ip = String(out || '').split(/\r?\n/).map((s) => s.trim()).find(Boolean)
      if (ip && /^\d+\.\d+\.\d+\.\d+$/.test(ip)) return ip
    } catch {}
  }
  return null
}
function lanIp(): string | null {
  const nets = os.networkInterfaces()
  const found: string[] = []
  for (const list of Object.values(nets)) {
    for (const i of list || []) {
      const v4 = (i as any).family === 4 || (i as any).family === 'IPv4'
      if (v4 && !i.internal && i.address) found.push(i.address)
    }
  }
  return found.find((a) => a.startsWith('192.168.')) || found.find((a) => a.startsWith('10.')) || found[0] || null
}

app.get('/api/phone', (req, res) => {
  const host = os.hostname().toLowerCase()
  const ts = tailscaleIp()
  const lan = lanIp()
  const base = (ip: string) => `http://${ip}:${PORT}`
  const items = [
    ts && { kind: 'tailscale', title: 'Через Tailscale (из любой сети)', url: base(ts), alt: `http://${host}:${PORT}`, qr: qrDataUri(base(ts)) },
    lan && { kind: 'lan', title: 'Домашний Wi-Fi — телефон в той же сети', url: base(lan), qr: qrDataUri(base(lan)) },
  ].filter(Boolean) as any[]
  res.json({
    tailscale: !!ts,
    host,
    port: PORT,
    items,
    opened_from: String(req.headers.host || ''),
    is_windows: process.platform === 'win32',
    local_only: HOST === '127.0.0.1',
    can_rotate: false,
    note: 'В QR зашит адрес компьютера. Наведите камеру телефона — сайт откроется, дальше «Добавить на экран Домой».',
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
    ...state.links.filter(l => [l.title, l.url, l.domain, l.comment].some(v => (v || '').toLowerCase().includes(q)))
      .map(l => ({ kind: 'link', id: l.id, title: l.title, url: l.url, snippet: l.comment || l.domain || l.url })),
  ]
  // фронт читает r.items (src/pages/Mind.jsx, Palette.jsx) — форма как у Python /api/search/semantic
  res.json({ items: results, total: results.length })
})
app.post('/api/search/reindex', (req, res) => res.json({ ok: true, count: 42 }))
app.post('/api/backup', (req, res) => res.json({ ok: true, file: 'backup-current.zip' }))

// Chat
app.get('/api/chat/history', (req, res) => {
  res.json(state.chatHistory)
})

/* Реальные цифры для ответов чата: дайджест, итоги недели и «куда ушли деньги»
   считаются из операций, а не берутся из заготовленного текста — иначе ассистент
   отвечал бы про баланс и даты, которых давно нет. */
const RU_DAYS = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']
function isoBack(days: number) { return new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10) }
function spentByCategory(sinceIso: string) {
  const by = new Map<string, number>()
  let spent = 0
  let earned = 0
  for (const t of state.transactions as any[]) {
    if ((t.date || '') < sinceIso) continue
    const amount = Number(t.amount) || 0
    if (amount > 0) { earned += amount; continue }
    if (!amount) continue
    const v = -amount
    spent += v
    const cat = t.category || 'Другое'
    by.set(cat, (by.get(cat) || 0) + v)
  }
  return { spent, earned, cats: [...by.entries()].sort((a, b) => b[1] - a[1]) }
}
function categoriesLine(cats: [string, number][], spent: number, take = 5) {
  return cats.slice(0, take)
    .map(([c, v]) => `• ${c}: ${v.toLocaleString('ru-RU')} ₽ (${Math.round((v / Math.max(1, spent)) * 100)}%)`)
    .join('\n')
}

function processChatInput(text: string): { reply: string; actions: string[]; via: string; fallback?: boolean } {
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

  // 4. Events: "встреча ...", "событие ...", "календарь: ..."
  // Разбираем день (сегодня/завтра/в среду) и время (в 15 / в 15:30) — раньше всё
  // записывалось на сегодня в 17:00, а ответ всё равно говорил «сегодня».
  if (lower.startsWith('встреча') || lower.startsWith('событие') || lower.startsWith('календарь')) {
    const rest = text.replace(/^(?:встреча:?|событие:?|календарь:?)\s*/i, '').trim()
    const now = new Date()
    const when = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    // Важно: \b в JS работает только по латинице, поэтому границы слов ищем пробелами
    if (/послезавтра/.test(lower)) when.setDate(when.getDate() + 2)
    else if (/(?:^|\s)завтра(?:\s|$)/.test(lower)) when.setDate(when.getDate() + 1)
    else if (!/(?:^|\s)сегодня(?:\s|$)/.test(lower)) {
      const WD: [RegExp, number][] = [
        [/(?:в|во)\s+понедельник/, 1],
        [/(?:в|во)\s+вторник/, 2],
        [/(?:в|во)\s+сред/, 3],
        [/(?:в|во)\s+четверг/, 4],
        [/(?:в|во)\s+пятниц/, 5],
        [/(?:в|во)\s+суббот/, 6],
        [/(?:в|во)\s+воскресень/, 0],
      ]
      for (const [re, dow] of WD) {
        if (re.test(lower)) { when.setDate(when.getDate() + ((dow - now.getDay() + 7) % 7)); break }
      }
    }
    const tm = rest.match(/(?:^|\s)в\s*(\d{1,2})(?:[:.](\d{2}))?/i)
    const hh = tm ? Math.min(23, Number(tm[1])) : 17
    const mm = tm && tm[2] ? Math.min(59, Number(tm[2])) : 0
    const clean = rest
      .replace(/(?:сегодня|завтра|послезавтра)/gi, '')
      .replace(/(?:^|\s)в\s*\d{1,2}(?:[:.]\d{2})?/gi, '')
      .replace(/\s{2,}/g, ' ')
      .replace(/^[\s,.;]+|[\s,.;]+$/g, '')
    const kw = /^встреча/i.test(text) ? 'встреча' : /^событие/i.test(text) ? 'событие' : /^календарь/i.test(text) ? 'встреча' : ''
    const title = clean ? (/^встреча/i.test(clean) ? clean : `${kw} ${clean}`.trim()) : (kw || 'Встреча')
    const start = `${when.getFullYear()}-${String(when.getMonth() + 1).padStart(2, '0')}-${String(when.getDate()).padStart(2, '0')}T${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:00`
    const endD = new Date(when.getTime())
    endD.setHours(hh, mm + 60, 0, 0)
    const ev = {
      id: ++nextId,
      title,
      start,
      end: `${endD.getFullYear()}-${String(endD.getMonth() + 1).padStart(2, '0')}-${String(endD.getDate()).padStart(2, '0')}T${String(endD.getHours()).padStart(2, '0')}:${String(endD.getMinutes()).padStart(2, '0')}:00`,
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
    const shown = `${when.getDate()}.${when.getMonth() + 1}`
    const shownTime = `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
    return {
      reply: `Записал в календарь: «${ev.title}» — ${shown} в ${shownTime}. Откройте «календарь», если нужно поправить.`,
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
    const { spent, earned, cats } = spentByCategory(isoBack(7))
    const balance = state.accounts.reduce((acc, a) => acc + (Number(a.balance) || 0), 0)
    const closed = (state.tasks as any[]).filter((t) => t.done && t.done_at && t.done_at >= isoBack(7)).length
    const dt = new Date()
    const from = new Date(Date.now() - 7 * 86_400_000)
    const p = (d: Date) => `${d.getDate()}.${d.getMonth() + 1}`
    return {
      reply: [
        `📊 Итоги недели, ${p(from)} — ${p(dt)}.${dt.getFullYear()}`,
        `Потрачено: ${spent.toLocaleString('ru-RU')} ₽ · Заработано: ${earned.toLocaleString('ru-RU')} ₽`,
        '',
        cats.length ? `Куда ушло:\n${categoriesLine(cats, spent)}` : 'Операций за неделю не было.',
        '',
        `Закрыто задач: ${closed}. Баланс: ${balance.toLocaleString('ru-RU')} ₽.`,
      ].join('\n'),
      actions: ['summary'],
      via: 'rule',
    }
  }

  if (lower.includes('доброе утро') || lower.includes('утренний дайджест') || lower.includes('дайджест')) {
    const now = new Date()
    const balance = state.accounts.reduce((acc, a) => acc + (Number(a.balance) || 0), 0)
    const evs = (state.events as any[]).filter((e) => (e.start || '').slice(0, 10) === todayStr)
    const open = (state.tasks as any[]).filter((t) => !t.done)
    const { spent } = spentByCategory(todayStr)
    const date = `${now.getDate()}.${now.getMonth() + 1}.${now.getFullYear()}`
    return {
      reply: [
        `☀️ Доброе утро. ${RU_DAYS[now.getDay()]}, ${date}.`,
        evs.length
          ? `Встреч сегодня ${evs.length}: ${evs.slice(0, 3).map((e) => `${e.title} (${String(e.start).slice(11, 16)})`).join('; ')}${evs.length > 3 ? '…' : ''}.`
          : 'Сегодня встреч нет — день ваш.',
        open.length
          ? `Открытых задач: ${open.length}. Главная — «${open[0].title}».`
          : 'Задач нет. Подозрительно.',
        `Баланс: ${balance.toLocaleString('ru-RU')} ₽. Сегодня потрачено: ${spent.toLocaleString('ru-RU')} ₽.`,
      ].join('\n'),
      actions: ['digest'],
      via: 'rule',
    }
  }

  if (lower.includes('что на сегодня') || lower.includes('план на сегодня') || lower.includes('расписание')) {
    const evCount = (state.events as any[]).filter((e) => (e.start || '').slice(0, 10) === todayStr).length
    const taskCount = state.tasks.filter((t: any) => !t.done).length
    return {
      reply: `На сегодня запланировано ${evCount} встреч и ${taskCount} невыполненных задач. Главный приоритет — «${state.tasks.find(t => !t.done)?.title || 'отдых'}».`,
      actions: [],
      via: 'rule',
    }
  }

  // Куда ушли деньги: разбор реальных операций по категориям
  if (/(куда ушли|куда дел|во что ушли|сколько потрат|расход[аы]? за|трат[ыа] за|по категори)/.test(lower)) {
    const days = /недел|7\s*дн/.test(lower) ? 7 : 30
    const { spent, cats } = spentByCategory(isoBack(days))
    const balance = state.accounts.reduce((acc, a) => acc + (Number(a.balance) || 0), 0)
    if (!spent) {
      return {
        reply: `За последние ${days} дней расходов не было. На счетах ${balance.toLocaleString('ru-RU')} ₽.`,
        actions: ['finance'],
        via: 'rule',
      }
    }
    return {
      reply: `За ${days} дней потрачено ${spent.toLocaleString('ru-RU')} ₽:\n${categoriesLine(cats, spent)}\n\nБаланс: ${balance.toLocaleString('ru-RU')} ₽. Подробнее — в разделе «финансы».`,
      actions: ['finance'],
      via: 'rule',
    }
  }

  // Fallback assistant response (сюда уходят свободные вопросы — на них может ответить ИИ)
  return {
    reply: `Да, сэр. Я зафиксировал: «${text}». Могу записать трату («700 такси»), засечь время («таймер 25 мин»), напомнить о встрече или проверить статус заказов.`,
    actions: [],
    via: 'rule',
    fallback: true,
  }
}

/* ---------------- ИИ (по желанию) ----------------
   Никаких новых зависимостей: обычный fetch на любой совместимый с OpenAI эндпоинт.
   Задаётся в .env:  LLM_API_KEY=...   LLM_URL=https://.../chat/completions   LLM_MODEL=...
   Без ключа всё работает как раньше — правила и голосовые команды не меняются. */
const LLM_KEY = process.env.LLM_API_KEY || process.env.OPENAI_API_KEY || process.env.DASHSCOPE_API_KEY || ''
const LLM_URL = process.env.LLM_URL || (LLM_KEY ? 'https://api.openai.com/v1/chat/completions' : '')
const LLM_MODEL = process.env.LLM_MODEL || 'gpt-4o-mini'
const llmOn = () => Boolean(LLM_KEY && LLM_URL)

app.get('/api/llm', (req, res) => {
  res.json({ enabled: llmOn(), model: llmOn() ? LLM_MODEL : null })
})

/* Контекст: ассистенту нужно знать реальное состояние, а не выдумывать.
   Собираем компактно — задачи, встречи, заказы, деньги. */
function llmContext() {
  const now = new Date()
  const day = `${now.getDate()}.${now.getMonth() + 1}.${now.getFullYear()}`
  const balance = state.accounts.reduce((s, a) => s + (Number(a.balance) || 0), 0)
  const openTasks = (state.tasks as any[]).filter(t => !t.done).slice(0, 6)
  const dayEvents = (state.events as any[]).filter(e => (e.start || '').slice(0, 10) === todayStr)
  const openOrders = (state.orders as any[]).filter(o => ['new', 'work', 'review'].includes(o.status)).slice(0, 5)
  const lines = [
    `Сегодня ${day}.`,
    `Баланс по счетам: ${Math.round(balance).toLocaleString('ru-RU')} ₽.`,
    openTasks.length ? `Открытые задачи: ${openTasks.map(t => `«${t.title}»${t.due ? ` до ${String(t.due).slice(11, 16)}` : ''}`).join('; ')}.` : 'Открытых задач нет.',
    dayEvents.length ? `Встречи сегодня: ${dayEvents.map(e => `${e.title} (${String(e.start).slice(11, 16)})`).join('; ')}.` : 'Встреч сегодня нет.',
    openOrders.length ? `Заказы в работе: ${openOrders.map(o => `${o.title} — ${o.status}`).join('; ')}.` : 'Заказов в работе нет.',
  ]
  return lines.join('\n')
}

async function llmAnswer(text: string): Promise<string | null> {
  if (!llmOn()) return null
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 25000)
    const history = (state.chatHistory as any[])
      .slice(-6)
      .filter(m => m.text)
      .map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: String(m.text).slice(0, 500) }))
    const payload = {
      model: LLM_MODEL,
      temperature: 0.4,
      max_tokens: 600,
      messages: [
        {
          role: 'system',
          content:
            'Ты — Марвин, личный ассистент владельца. Отвечай коротко, по-русски, спокойно и по делу. ' +
            'Никогда не выдумывай суммы, даты и статусы — используй только данные ниже. ' +
            'Если вопрос про действия в приложении (записать трату, поставить задачу) — просто подскажи, как это сказать одной фразой.\n\n' +
            llmContext(),
        },
        ...history,
        { role: 'user', content: text },
      ],
    }
    const r = await fetch(LLM_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${LLM_KEY}` },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    })
    clearTimeout(timer)
    if (!r.ok) {
      console.warn(`[llm] ${r.status} ${r.statusText}`)
      return null
    }
    const j = await r.json()
    const out = j?.choices?.[0]?.message?.content
    return typeof out === 'string' && out.trim() ? out.trim() : null
  } catch (err) {
    console.warn('[llm] error:', (err as any)?.message || err)
    return null
  }
}

/* Правила сначала: команды («700 такси», «задача: …») должны срабатывать всегда и мгновенно.
   На свободный вопрос, если настроен ИИ, уходит в модель; ключа нет — остаёмся на правилах. */
async function reply(text: string): Promise<{ reply: string; actions: string[]; via: string }> {
  const base = processChatInput(text)
  if (base.fallback && llmOn()) {
    const ai = await llmAnswer(text)
    if (ai) return { reply: ai, actions: [], via: 'llm' }
  }
  return { reply: base.reply, actions: base.actions, via: base.via }
}

app.post('/api/chat', async (req, res, next) => {
  try {
    const { text } = req.body ?? {}
    if (typeof text !== 'string' || !text.trim()) {
      return res.status(400).json({ error: 'text must be a non-empty string' })
    }
    const result = await reply(text)

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
  } catch (err) {
    next(err)
  }
})

app.post('/api/chat/stream', async (req, res, next) => {
  try {
    const { text } = req.body ?? {}
    if (typeof text !== 'string' || !text.trim()) {
      return res.status(400).json({ error: 'text must be a non-empty string' })
    }
    const result = await reply(text)

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
  } catch (err) {
    next(err)
  }
})

// ----------------- VITE / STATIC SERVING -----------------

async function setupFrontend() {
  // неизвестный эндпоинт → честный 404 JSON, а не index.html из SPA-fallback
  app.use('/api', (_req, res) => {
    res.status(404).json({ detail: 'Неизвестный эндпоинт' })
  })

  if (!isProd) {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    })
    app.use(vite.middlewares)
  } else {
    // Единственный output — web/site (тот же dir, что раздаёт Python-ядро). Fallback на dist/ удалён.
    const distPath = path.resolve(process.cwd(), 'web', 'site')
    if (fs.existsSync(distPath)) {
      app.use(express.static(distPath))
      app.get('*', (req, res) => {
        res.sendFile(path.join(distPath, 'index.html'))
      })
    }
  }

  // последним: ошибка в любом роуте → ответ вместо падения процесса
  app.use((err: any, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
    console.error('[server] route error:', err)
    if (res.headersSent) return
    if (err?.name === 'MulterError') return res.status(400).json({ detail: err.message })
    res.status(500).json({ detail: 'Внутренняя ошибка сервера' })
  })

  app.listen(PORT, HOST, () => {
    console.log(`Assistant server running at http://${HOST}:${PORT} in ${isProd ? 'production' : 'development'} mode`)
  })
}

setupFrontend().catch(err => {
  console.error('Failed to start server:', err)
  process.exit(1)
})
