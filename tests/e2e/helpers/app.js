// Хелперы e2e-стенда: страницы, ожидания, ошибки, скриншоты.
// Импорт из тестов:  import { openPage, TABS, shot } from '../helpers/index.js'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const E2E_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export const SHOTS_DIR = path.join(E2E_DIR, 'screens')

// ---------------------------------------------------------------- вкладки приложения
/** Все вкладки сайта: путь + как называется в отчёте. Порядок = порядок обхода в smoke-тесте. */
export const TABS = [
  { key: 'today', path: '/', title: 'Сегодня' },
  { key: 'tasks', path: '/tasks', title: 'Задачи' },
  { key: 'calendar', path: '/calendar', title: 'Календарь' },
  { key: 'finance', path: '/finance', title: 'Финансы' },
  { key: 'orders', path: '/orders', title: 'Заказы' },
  { key: 'mind', path: '/mind', title: 'Мозг' },
  { key: 'board', path: '/board', title: 'Доска' },
  { key: 'people', path: '/people', title: 'Люди' },
  { key: 'memory', path: '/memory', title: 'Память' },
  { key: 'settings', path: '/settings', title: 'Настройки' },
]

// ---------------------------------------------------------------- сборщик ошибок
/**
 * Собирает ошибки страницы: исключения JS, console.error и ответы с кодом >= 400.
 * Возвращает объект, который живёт весь тест:  const diag = watch(page)
 * В конце теста:  await diag.expectClean({ ignore: [/\/api\/events\/stream/] })
 */
export function watch(page, { ignore = [] } = {}) {
  const errors = []
  const failed = []
  const isIgnored = (text) => ignore.some((re) => re.test(text))

  page.on('pageerror', (err) => errors.push(`[pageerror] ${err.message}`))
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
    const text = msg.text()
    // иконки шрифта и прочие 404 в консоли — шум, но только если это явно favicon/манифест
    if (isIgnored(text)) return
    errors.push(`[console] ${text}`)
  })
  page.on('requestfailed', (req) => {
    const text = `${req.method()} ${req.url()} — ${req.failure()?.errorText || 'не выполнен'}`
    if (isIgnored(text) || isIgnored(req.url())) return
    failed.push(text)
  })
  page.on('response', (res) => {
    if (res.status() < 400) return
    const url = res.url()
    if (isIgnored(url) || isIgnored(`${res.status()} ${url}`)) return
    failed.push(`${res.status()} ${res.request().method()} ${url}`)
  })

  return {
    errors,
    failed,
    /** мягкая проверка: вернуть список (для логов), ничего не падать */
    list() {
      return [...errors.map((e) => `ОШИБКА ${e}`), ...failed.map((f) => `СЕТЬ  ${f}`)]
    },
    /** жёсткая проверка: упасть с читаемым сообщением, если есть ошибки */
    async expectClean(note = '') {
      const all = this.list()
      if (all.length) {
        throw new Error(`Страница с ошибками${note ? ` (${note})` : ''}:\n  ` + all.join('\n  '))
      }
    },
    /** сбросить накопленное (между шагами одного теста) */
    clear() {
      errors.length = 0
      failed.length = 0
    },
  }
}

// ---------------------------------------------------------------- скриншоты
/**
 * Скриншот в tests/e2e/screens/<проект>-<имя>.png (поимённо, с префиксом проекта) и
 * в отчёт Playwright. Возвращает путь к файлу.
 *   await shot(page, 'orders-kanban')            // → screens/desktop-orders-kanban.png
 */
export async function shot(page, name, { fullPage = true, testInfo } = {}) {
  fs.mkdirSync(SHOTS_DIR, { recursive: true })
  const project = (testInfo?.project || page.__e2eProject || 'page').name || 'page'
  const file = path.join(SHOTS_DIR, `${project}-${name}.png`)
  // animations: 'disabled' — иначе счётчики и карточки попадают в кадр на середине анимации
  await page.screenshot({ path: file, fullPage, animations: 'disabled', caret: 'hide' })
  const abs = path.resolve(file)
  try {
    testInfo?.attach?.(name, { path: abs, contentType: 'image/png' })
  } catch { /* attach вне теста не нужен */ }
  return abs
}

// ---------------------------------------------------------------- страницы
/** Ждём, что React-приложение смонтировалось: #root непустой и в нём есть текст. */
export async function waitApp(page, { timeout = 20_000 } = {}) {
  await page.waitForSelector('#root', { state: 'attached', timeout })
  await page.waitForFunction(() => {
    const root = document.querySelector('#root')
    return !!root && root.children.length > 0 && (root.innerText || '').trim().length > 10
  }, null, { timeout })
  // шрифты/иконки: не ждём networkidle — на странице живёт SSE /api/events/stream
  await page.evaluate(() => document.fonts?.ready).catch(() => {})
  return page
}

/**
 * Проверка «не белый экран»: приложение смонтировано, у корня есть видимый текст,
 * на странице нет сообщения о сломанной странице.
 * Бросает Error с понятным текстом, если это не так.
 */
export async function expectRendered(page, note = '') {
  const info = await page.evaluate(() => {
    const root = document.querySelector('#root')
    const text = (root?.innerText || '').trim()
    const body = (document.body?.innerText || '').trim()
    const broken = /страница сломалась|такой страницы нет|Something went wrong/i.test(body)
    const rect = root?.getBoundingClientRect()
    return { textLen: text.length, bodyLen: body.length, broken, h: rect?.height || 0, text: text.slice(0, 200) }
  })
  if (info.broken) throw new Error(`Приложение показало экран ошибки${note ? ` (${note})` : ''}: ${info.text}`)
  if (info.textLen < 10 || info.h < 40) {
    throw new Error(`Похоже на белый экран${note ? ` (${note})` : ''}: текста ${info.textLen} симв., высота ${info.h}px`)
  }
  return info
}

/** Открыть корень приложения и дождаться готовности. */
export async function openApp(page, { testInfo } = {}) {
  if (testInfo) page.__e2eProject = testInfo.project
  await page.goto('/', { waitUntil: 'domcontentloaded' })
  await waitApp(page)
  await expectRendered(page, 'главная')
  return page
}

/** Открыть вкладку по ключу TABS ('orders') или по пути ('/orders'). */
export async function openTab(page, keyOrPath, { testInfo } = {}) {
  const tab = TABS.find((t) => t.key === keyOrPath || t.path === keyOrPath)
  const path_ = tab ? tab.path : keyOrPath
  const name = tab ? tab.title : keyOrPath
  await page.goto(path_, { waitUntil: 'domcontentloaded' })
  await waitApp(page)
  await expectRendered(page, name)
  return tab || { key: keyOrPath, path: path_, title: name }
}

/** Клик по вкладке в сайдбаре (на мобильном часть вкладок только в меню — поэтому goto надёжнее). */
export async function clickTab(page, keyOrPath) {
  const tab = TABS.find((t) => t.key === keyOrPath || t.path === keyOrPath)
  if (!tab) throw new Error(`Нет такой вкладки: ${keyOrPath}`)
  const nav = page.locator(`aside a[href="${tab.path}"], nav a[href="${tab.path}"]`).first()
  await nav.waitFor({ state: 'visible', timeout: 10_000 })
  await nav.click()
  await expectRendered(page, tab.title)
  return tab
}

// ---------------------------------------------------------------- клики и ввод
/** Клик по элементу с видимым текстом (кнопка, ссылка, пункт меню). */
export async function clickText(page, text, { exact = false, index = 0, timeout = 15_000 } = {}) {
  const loc = page.getByText(text, { exact }).nth(index)
  await loc.waitFor({ state: 'visible', timeout })
  await loc.click()
  return loc
}

/** Клик по кнопке с указанным именем/подписью. */
export async function clickButton(page, name, { timeout = 15_000 } = {}) {
  const btn = page.getByRole('button', { name, exact: false }).first()
  await btn.waitFor({ state: 'visible', timeout })
  await btn.click()
  return btn
}

/** Заполнить поле по подписи, плейсхолдеру или имени. */
export async function fillField(page, labelOrPlaceholder, value, { timeout = 15_000 } = {}) {
  const byLabel = page.getByLabel(labelOrPlaceholder, { exact: false })
  const field = (await byLabel.count()) ? byLabel.first() : page.getByPlaceholder(labelOrPlaceholder).first()
  await field.waitFor({ state: 'visible', timeout })
  await field.fill(value)
  return field
}

// ---------------------------------------------------------------- модалки и drawer
// Сайт рисует их как .sheet-backdrop > .sheet (portal в body), см. web/src/components/ui.jsx.

export async function expectSheet(page, { timeout = 15_000 } = {}) {
  const sheet = page.locator('.sheet-backdrop:not(.closing) .sheet').last()
  await sheet.waitFor({ state: 'visible', timeout })
  return sheet
}

export async function sheetTitle(page) {
  const sheet = await expectSheet(page)
  return (await sheet.locator('h2, h3').first().innerText().catch(() => '')).trim()
}

/** Закрыть верхнюю модалку: крестик, затем Esc, затем клик по подложке. */
export async function closeSheet(page) {
  const sheet = page.locator('.sheet-backdrop:not(.closing) .sheet').last()
  if (!(await sheet.isVisible().catch(() => false))) return
  const x = sheet.locator('button').first()
  if (await x.isVisible().catch(() => false)) {
    await x.click().catch(() => {})
  } else {
    await page.keyboard.press('Escape').catch(() => {})
  }
  await sheet.waitFor({ state: 'detached', timeout: 10_000 }).catch(() => {})
}

// ---------------------------------------------------------------- текст и счётчики
/** Видимый текст страницы. */
export async function pageText(page) {
  return page.evaluate(() => (document.querySelector('#root')?.innerText || '').trim())
}

/** Есть ли на странице текст (для проверок «демо-данные видны»). */
export async function hasText(page, text) {
  return pageText(page).then((t) => t.includes(text))
}

export async function expectText(page, text, { timeout = 15_000, note = '' } = {}) {
  await page.waitForFunction(
    (t) => (document.querySelector('#root')?.innerText || '').includes(t),
    text,
    { timeout },
  ).catch(async () => {
    const got = (await pageText(page)).slice(0, 300)
    throw new Error(`Не нашёл текст «${text}»${note ? ` (${note})` : ''}. На странице: ${got}`)
  })
  return true
}