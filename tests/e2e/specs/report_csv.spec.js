// Review D: экспорт CSV из настроек («память и данные» → «данные»):
//   1) четыре ссылки ведут на /api/export/*.csv;
//   2) каждая выгрузка скачивается: 200, BOM для Excel, без текста ошибки;
//   3) transactions.csv несёт свежую операцию, кириллицу и разделитель «;».
// Тело читаем из скачанного файла: у ответа с Content-Disposition attachment
// resp.body() после клика недоступен («response was navigated away from»).
// Скачивание файла — это навигация, прерванная браузером: requestfailed
// net::ERR_ABORTED на /api/export/ штатен, поэтому исключён из диагностики.
import fs from 'node:fs'
import { test, expect, watch, shot, openTab, expectText } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i, /\/api\/export\//]
const uniq = (p) => `${p}-${Date.now().toString(36)}`
const LINKS = [
  ['операции.csv', '/api/export/transactions.csv'],
  ['календарь.csv', '/api/export/events.csv'],
  ['задачи.csv', '/api/export/tasks.csv'],
  ['заметки.csv', '/api/export/notes.csv'],
]

const openExports = async (page, testInfo) => {
  await openTab(page, '/settings#memory', { testInfo })
  await expectText(page, 'операции.csv', { note: 'раздел «данные» с экспортами' })
}

// клик по ссылке экспорта → скачанный файл + статус ответа
const downloadCsv = async (page, href) => {
  const [dl] = await Promise.all([
    page.waitForEvent('download', { timeout: 20_000 }),
    page.click(`a[href="${href}"]`),
  ])
  const resp = await page.request.get(href)
  return { text: fs.readFileSync(await dl.path(), 'utf8'), status: resp.status() }
}

test.describe('экспорт CSV из настроек', () => {
  test('четыре ссылки ведут на /api/export/*.csv', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openExports(page, testInfo)
    for (const [label, href] of LINKS) {
      const a = page.locator(`a[href="${href}"]`)
      await expect(a, `ссылка «${label}» (${href})`).toHaveCount(1)
      await expect(a).toBeVisible()
      await expect(a).toContainText(label)
    }
    await diag.expectClean('ссылки экспорта')
  })

  for (const [label, href] of LINKS) {
    test(`выгрузка «${label}» скачивается: 200, BOM, без ошибок`, async ({ page }, testInfo) => {
      const diag = watch(page, { ignore: IGNORE })
      page.__e2eProject = testInfo.project

      await openExports(page, testInfo)
      const { text: body, status } = await downloadCsv(page, href)
      expect(status, `${label}: статус ответа`).toBe(200)
      expect(body.length, `${label}: пустое тело`).toBeGreaterThan(1)
      expect(body.charCodeAt(0), `${label}: нет BOM — Excel покажет кракозябры`).toBe(0xfeff)
      expect(body, `${label}: в выгрузке текст ошибки`).not.toMatch(/Traceback|Internal Server Error| detail /i)

      await diag.expectClean(`выгрузка ${label}`)
    })
  }

  test('transactions.csv содержит свежую операцию, кириллицу и разделитель «;»', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = `Экспорт D ${uniq(testInfo.project.name)}`

    // операция создаётся через API (сам UI создания покрыт finance_tx.spec.js)
    await openTab(page, '/finance', { testInfo })
    await page.evaluate((t) => fetch('/api/finance/transactions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount: 77, kind: 'expense', note: t }),
    }).then((r) => { if (!r.ok) throw new Error(`POST /api/finance/transactions → ${r.status}`) }), TITLE)

    await openExports(page, testInfo)
    const { text: raw, status } = await downloadCsv(page, '/api/export/transactions.csv')
    expect(status).toBe(200)
    const text = raw.replace(/^\uFEFF/, '')
    const lines = text.split(/\r?\n/).filter(Boolean)
    expect(lines[0], 'шапка CSV через точку с запятой').toMatch(/^[^,\n]+;[^,\n]+/)
    expect(text, 'в данных есть кириллица').toMatch(/[А-Яа-яЁё]/)
    expect(text, 'свежая операция должна попасть в выгрузку').toContain(TITLE)

    await shot(page, 'settings-export', { testInfo })
    await diag.expectClean('transactions.csv')
  })
})
