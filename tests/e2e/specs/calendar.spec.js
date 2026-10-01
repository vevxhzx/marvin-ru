// Review D: календарь — создание события через «+ событие» (datetime-local, ровно один раз
// в дне после reload) и навигация «‹ / сегодня / ›» + переключатель неделя ↔ месяц.
import { test, expect, watch, shot, openTab, expectText, expectSheet } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]
const uniq = (p) => `${p}-${Date.now().toString(36)}`

// ISO-строка для input[type=datetime-local] (локальное время браузера)
const localDT = (d) => {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}
const monthName = (d) => d.toLocaleDateString('ru-RU', { month: 'long' }).toLowerCase()

// панель выбранного дня: секция с заголовком «сегодня» (вид «месяц» по умолчанию)
const dayPanel = (page) => page.locator('#p-cal section.c').filter({
  has: page.getByRole('heading', { name: 'сегодня', exact: true }),
})

test.describe('календарь', () => {
  test('«+ событие»: дата через datetime-local, событие ровно один раз после reload', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = `E2E событие D ${uniq(testInfo.project.name)}`

    await openTab(page, '/calendar', { testInfo })
    await page.getByText('+ событие', { exact: true }).click()
    const sheet = await expectSheet(page)
    await expect(sheet.getByRole('heading', { name: 'новое событие' })).toBeVisible()

    await sheet.getByLabel('название встречи').fill(TITLE)
    const dt = sheet.locator('input[type="datetime-local"]')
    await expect(dt, 'поле «дата и время» — datetime-local').toBeVisible()
    const when = new Date()
    when.setHours(12, 0, 0, 0)             // сегодня в полдень: событие точно в текущем дне
    await dt.fill(localDT(when))

    await sheet.getByRole('button', { name: 'сохранить', exact: true }).click()
    await sheet.waitFor({ state: 'detached', timeout: 15_000 })

    // панель дня («сегодня») — ровно одна строка, без задвоений
    await expect(dayPanel(page).locator('.rowi', { hasText: TITLE })).toHaveCount(1, { timeout: 15_000 })
    await shot(page, 'calendar-event', { testInfo })

    await openTab(page, '/calendar', { testInfo })
    await expect(dayPanel(page).locator('.rowi', { hasText: TITLE }), 'после reload событие одно').toHaveCount(1, { timeout: 15_000 })

    await diag.expectClean('создание события')
  })

  test('навигация «‹»/«сегодня»/«›» и переключение неделя ↔ месяц', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openTab(page, '/calendar', { testInfo })
    await expectText(page, 'календарь')

    const title = page.locator('#p-cal .top h1').first()
    const nav = page.locator('#p-cal .top .sg').filter({ hasText: '‹' })
    const now = new Date()
    const cur = monthName(now)
    const prev = monthName(new Date(now.getFullYear(), now.getMonth() - 1, 1))
    const next = monthName(new Date(now.getFullYear(), now.getMonth() + 1, 1))

    // по умолчанию вид «месяц» — заголовок = текущий месяц
    await expect.poll(async () => (await title.innerText()).trim().toLowerCase(), { timeout: 10_000 }).toBe(cur)

    // «‹» уводит на месяц назад, «сегодня» возвращает, «›» — на месяц вперёд
    await nav.locator('span', { hasText: '‹' }).click()
    await expect.poll(async () => (await title.innerText()).trim().toLowerCase(), { timeout: 10_000 }).toBe(prev)
    await nav.locator('span', { hasText: 'сегодня' }).click()
    await expect.poll(async () => (await title.innerText()).trim().toLowerCase(), { timeout: 10_000 }).toBe(cur)
    await nav.locator('span', { hasText: '›' }).click()
    await expect.poll(async () => (await title.innerText()).trim().toLowerCase(), { timeout: 10_000 }).toBe(next)

    // вид «неделя»: заголовок «неделя <день> <месяц>», «месяц» возвращает месяц
    await nav.locator('span', { hasText: 'сегодня' }).click()
    await page.getByText('неделя', { exact: true }).click()
    await expect.poll(async () => (await title.innerText()).trim(), { timeout: 10_000 })
      .toMatch(new RegExp(`^неделя ${now.getDate()} `))
    await page.getByText('месяц', { exact: true }).click()
    await expect.poll(async () => (await title.innerText()).trim().toLowerCase(), { timeout: 10_000 }).toBe(cur)

    await shot(page, 'calendar-nav', { testInfo })
    await diag.expectClean('навигация по календарю')
  })
})
