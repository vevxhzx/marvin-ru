// Тесты HTTP-контрактов server.ts (Node-демо).
// Запуск: npm test  →  node --test tests/server_api.test.mjs
//
// Зачем: фронт (src/) рассчитывает на определённую форму ответов. Если сервер отвечает
// «как попало», страница не падает с ошибкой, а молча показывает выдуманные цифры —
// поэтому форма здесь проверяется явно.
import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const PORT = 3999
const BASE = `http://127.0.0.1:${PORT}`
const STATE = path.join(ROOT, 'data', 'server-state.json')
const STATE_BAK = STATE + '.testbak'

let child = null
let log = ''

/** GET/POST c JSON-телом; возвращает {status, body} */
async function call(method, url, body) {
  const res = await fetch(BASE + url, {
    method,
    headers: { 'content-type': 'application/json', origin: BASE },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let parsed = null
  try { parsed = await res.json() } catch { /* не JSON — это тоже ответ */ }
  return { status: res.status, body: parsed, res }
}

before(async () => {
  // Тесты пишут состояние — убираем файл пользователя в сторону и возвращаем после.
  if (fs.existsSync(STATE)) fs.renameSync(STATE, STATE_BAK)

  child = spawn(process.execPath, ['--import', 'tsx', path.join(ROOT, 'server.ts')], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(PORT), HOST: '127.0.0.1', NODE_ENV: 'test' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  child.stdout.on('data', (d) => { log += d })
  child.stderr.on('data', (d) => { log += d })

  const deadline = Date.now() + 30_000
  for (;;) {
    if (child.exitCode !== null) throw new Error(`сервер не поднялся (exit ${child.exitCode}):\n${log}`)
    try {
      const r = await fetch(`${BASE}/api/status`)
      if (r.ok) break
    } catch { /* ещё не слушает */ }
    if (Date.now() > deadline) throw new Error(`сервер не поднялся за 30 с:\n${log}`)
    await new Promise((r) => setTimeout(r, 250))
  }
})

after(async () => {
  if (child && child.exitCode === null) {
    child.kill()
    await new Promise((r) => setTimeout(r, 800))   // даём серверу дописать состояние
  }
  if (fs.existsSync(STATE_BAK)) fs.renameSync(STATE_BAK, STATE)
})

test('/api/status отдаёт форму, которую рисует Settings.jsx', async () => {
  const { status, body: s } = await call('GET', '/api/status')
  assert.equal(status, 200)
  assert.equal(typeof s.ollama.ok, 'boolean', 'status.ollama.ok')
  assert.equal(typeof s.db.size, 'number', 'status.db.size')
  assert.equal(typeof s.db.tasks, 'number', 'status.db.tasks')
  assert.ok(Array.isArray(s.errors), 'status.errors — массив')
  assert.equal(typeof s.version, 'string')
  assert.equal(typeof s.game_mode, 'boolean')
  assert.ok(s.gemini && typeof s.gemini.providers === 'object')
  assert.equal(typeof s.backup.count, 'number')
})

test('/api/status/* отвечает честно, а не {ok:true}', async () => {
  for (const ep of ['/api/status/small', '/api/status/gemini']) {
    const { body } = await call('POST', ep, {})
    assert.equal(body.ok, false, ep)
    assert.equal(typeof body.detail, 'string', ep)
  }
})

test('PUT /api/settings возвращает {changed, restart}', async () => {
  const { status, body } = await call('PUT', '/api/settings', {})
  assert.equal(status, 200)
  assert.ok(Array.isArray(body.changed), 'changed — массив, фронт делает r.changed.length')
  assert.equal(typeof body.restart, 'boolean')
})

test('/api/facts: {items, stats}, а стиль «как вы пишете» переживает перезагрузку', async () => {
  const { body: first } = await call('GET', '/api/facts')
  assert.ok(Array.isArray(first.items))
  assert.equal(typeof first.stats.long, 'number')
  assert.equal(typeof first.stats.style, 'string')
  assert.ok('style_at' in first.stats)

  const put = await call('PUT', '/api/facts/style', { text: 'Пишу коротко' })
  assert.equal(put.body.style, 'Пишу коротко')
  const { body: again } = await call('GET', '/api/facts')
  assert.equal(again.stats.style, 'Пишу коротко', 'правка не должна теряться')

  const bad = await call('PUT', '/api/facts/style', { text: 42 })
  assert.equal(bad.status, 400, 'не-строка должна отклоняться, а не молча сохраняться')
})

test('пересборка памяти без LLM — честный 501, а не ложный успех', async () => {
  for (const ep of ['/api/facts/portrait', '/api/facts/nightly', '/api/facts/style']) {
    const { status, body } = await call('POST', ep, {})
    assert.equal(status, 501, ep)
    assert.equal(typeof body.detail, 'string', ep)
  }
})

test('/api/graph отдаёт {nodes, edges} — иначе страница графа падает', async () => {
  const { status, body } = await call('GET', '/api/graph')
  assert.equal(status, 200)
  assert.ok(Array.isArray(body.nodes), 'nodes')
  assert.ok(Array.isArray(body.edges), 'edges — фронт читает body.edges')
  // Graph.jsx фильтрует связи по {source, target}
  for (const e of body.edges) {
    assert.ok(body.nodes.some((n) => n.id === e.source), `битая ссылка source=${e.source}`)
    assert.ok(body.nodes.some((n) => n.id === e.target), `битая ссылка target=${e.target}`)
  }
  assert.equal(typeof body.stats.edges, 'number')
  assert.equal(typeof body.stats.lonely, 'number', 'stats.lonely для подписи «без связей»')
})

test('/api/search/semantic отдаёт {items} (фронт читает r.items)', async () => {
  const { body } = await call('GET', '/api/search/semantic?q=github')
  assert.ok(Array.isArray(body.items), 'items')
  assert.equal(typeof body.total, 'number')
  const { body: links } = await call('GET', '/api/search/semantic?q=новост')
  assert.ok(links.items.some((x) => x.kind === 'link'), 'ссылки тоже ищутся')
  assert.equal(typeof links.items.find((x) => x.kind === 'link').url, 'string')
})

test('/api/ui-prefs зеркалит оформление между устройствами', async () => {
  const { body: beforePut } = await call('GET', '/api/ui-prefs')
  assert.ok(beforePut.prefs && typeof beforePut.prefs === 'object')
  await call('PUT', '/api/ui-prefs', { prefs: { theme: 'dark' } })
  const { body: afterPut } = await call('GET', '/api/ui-prefs')
  assert.equal(afterPut.prefs.theme, 'dark')
  const bad = await call('PUT', '/api/ui-prefs', { theme: 'dark' })
  assert.equal(bad.status, 400, 'без обёртки {prefs} — 400, а не тихое игнорирование')
})

test('/api/finance/techniques совпадает по форме с Python-ядром', async () => {
  const { body } = await call('GET', '/api/finance/techniques')
  for (const key of ['buckets', 'compare', 'annual', 'payments', 'runway']) {
    assert.ok(key in body, `нет ключа ${key}`)
  }
  assert.ok(body.buckets.base > 0, 'buckets.base — число')
  assert.ok(Array.isArray(body.buckets.buckets))
  for (const b of body.buckets.buckets) {
    assert.ok(['over', 'ok', 'low'].includes(b.status), `статус ${b.status}`)
  }
  assert.equal(typeof body.runway.runway_days, 'number')
  assert.equal(typeof body.payments.short, 'number')
})

test('/api/dashboard считает производные сам, а не рисует их', async () => {
  const { body } = await call('GET', '/api/dashboard')
  assert.equal(body.finance.weekday.length, 7, 'столбики «траты» по дням недели')
  assert.equal(body.finance.month_days.length, 7, 'столбики по дням месяца')
  assert.equal(typeof body.finance.avg_daily, 'number')
  assert.equal(typeof body.pc.alive, 'boolean', 'ПК не должен быть «жив» навсегда')
  assert.equal(typeof body.orders.expected, 'number')
  for (const b of body.birthdays) assert.equal(typeof b.days_left, 'number', b.name)
})

test('экспорт: CSV с BOM (Excel читает кириллицу), JSON — со всеми разделами', async () => {
  const csv = await fetch(BASE + '/api/export/tasks.csv')
  assert.match(csv.headers.get('content-type'), /text\/csv/)
  const bytes = new Uint8Array(await csv.arrayBuffer())
  assert.deepEqual([...bytes.slice(0, 3)], [0xef, 0xbb, 0xbf], 'BOM')

  const all = await fetch(BASE + '/api/export/all.json')
  const json = await all.json()
  for (const key of ['tasks', 'events', 'notes', 'transactions']) {
    assert.ok(key in json, `нет раздела ${key}`)
  }
})

test('категории людей реально удаляются (раньше — молча игнорировались)', async () => {
  const { body: kinds } = await call('GET', '/api/people/kinds')
  assert.ok(Array.isArray(kinds) && kinds.length > 0)
  const victim = kinds[kinds.length - 1]
  assert.equal((await call('DELETE', `/api/people/kinds/${encodeURIComponent(victim)}`)).status, 200)
  const { body: after } = await call('GET', '/api/people/kinds')
  assert.ok(!after.includes(victim))
  assert.equal((await call('DELETE', `/api/people/kinds/${encodeURIComponent(victim)}`)).status, 404, 'повтор — 404')
})

test('уроков в этом стеке нет — честная пустота и 404', async () => {
  const { body } = await call('GET', '/api/lessons')
  assert.deepEqual(body, [])
  assert.equal((await call('DELETE', '/api/lessons/1')).status, 404)
})

test('/api/tg/login без ключа не выдаёт ложную сессию', async () => {
  const { status, body } = await call('POST', '/api/tg/login', { code: '12345' })
  assert.ok([401, 501].includes(status), `статус ${status}`)
  assert.equal(typeof body.detail, 'string')
})

test('неизвестный /api/* — JSON-404, а не HTML-страница SPA', async () => {
  const { status, body } = await call('GET', '/api/nope')
  assert.equal(status, 404)
  assert.equal(typeof body.detail, 'string')
  assert.equal((await call('POST', '/api/nope', {})).status, 404)
})

test('/api/chat отклоняет не-строку и жив после ошибки', async () => {
  assert.equal((await call('POST', '/api/chat', { text: 123 })).status, 400)
  assert.equal((await call('POST', '/api/chat', { text: 'привет' })).status, 200)
})

test('чужой Origin не получает CORS-заголовка', async () => {
  const res = await fetch(`${BASE}/api/status`, { headers: { origin: 'http://evil.example' } })
  assert.equal(res.headers.get('access-control-allow-origin'), null)
  const own = await fetch(`${BASE}/api/status`, { headers: { origin: BASE } })
  assert.equal(own.headers.get('access-control-allow-origin'), BASE)
})
