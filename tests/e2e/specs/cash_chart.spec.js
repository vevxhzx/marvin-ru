// График «касса на N дней»: подсказка из двух подписанных строк, ось с реальными датами,
// маркер «сегодня» на сегодняшней точке и отсутствие обрезки подсказки краями графика.
// Запуск одного файла:  npx playwright test tests/e2e/specs/cash_chart.spec.js
import { test, expect, watch, shot, openTab } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]
const CHART = 'svg[aria-label="график баланса и прогноза"]'

const dm = (iso) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`

test.describe('график «касса на N дней»', () => {
  test('подсказка показывает баланс на дату и изменение за день', async ({ page }, testInfo) => {
    // на сенсорном экране наведения нет — там проверяем тап (третий тест)
    test.skip(testInfo.project.name !== 'desktop', 'наведение мышью только на desktop')
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    await openTab(page, 'finance', { testInfo })

    const svg = page.locator(CHART).first()
    await expect(svg).toBeVisible({ timeout: 20_000 })
    // прямоугольник берём из самой страницы: boundingBox() иногда смещён на доли пикселя
    const box = await svg.evaluate((el) => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height } })
    expect(box.w).toBeGreaterThan(50)

    // ряд с сервера — эталон: подсказка обязана показывать точку, которая под курсором
    const points = await page.evaluate(async () => {
      const r = await fetch('/api/finance/forecast?days=30')
      const j = await r.json()
      return j.points.map((p) => ({ date: p.date, balance: p.balance, kind: p.kind }))
    })
    expect(points.length).toBeGreaterThan(30)

    const tip = page.getByTestId('cash-tip').first()
    for (const frac of [0.3, 0.6, 0.9]) {
      await page.mouse.move(box.x + box.w * frac, box.y + box.h / 2, { steps: 4 })
      await expect(tip).toBeVisible()
      const i = Math.round(frac * (points.length - 1))
      await expect(tip).toHaveAttribute('data-date', points[i].date)
      await expect(tip).toHaveAttribute('data-bal', String(points[i].balance))
      await expect(tip).toHaveAttribute('data-kind', points[i].kind)
    }

    const text = await tip.innerText()
    const cur = points[Math.round(0.9 * (points.length - 1))]
    // ровно две подписанные строки: на какую дату баланс и что изменилось за день
    expect(text).toMatch(/(баланс|прогноз) на \d\d\.\d\d: [−-]?[\d\s]+ ₽/)
    expect(text).toMatch(/за день( \(прогноз\))?: (без изменений|[−+]?[\d\s]+ ₽)/)
    // число в подсказке — то же, что в ряду (data-bal сверен выше)
    expect(text.replace(/\D/g, '')).toContain(String(Math.abs(cur.balance)))
    // точка будущего подписана как прогноз, точка факта — как баланс
    expect(text).toContain(cur.kind === 'future' ? 'прогноз на' : 'баланс на')

    // подсказка не вылезает за края графика
    const host = await svg.evaluate((el) => { const r = el.getBoundingClientRect(); return { x: r.x, w: r.width } })
    const tb = await tip.boundingBox()
    expect(tb.x).toBeGreaterThanOrEqual(host.x - 2)
    expect(tb.x + tb.width).toBeLessThanOrEqual(host.x + host.w + 2)

    await shot(page, 'cash-tip', { testInfo, fullPage: false })
    await diag.expectClean('подсказка графика')
  })

  test('ось X с реальными датами, «сегодня» одна и на сегодняшней точке', async ({ page }, testInfo) => {
    await openTab(page, 'finance', { testInfo })
    await expect(page.locator(CHART).first()).toBeVisible({ timeout: 20_000 })

    const ticks = page.getByTestId('cash-tick')
    const count = await ticks.count()
    expect(count).toBeGreaterThanOrEqual(3)      // 3-5 подписанных дат
    expect(count).toBeLessThanOrEqual(6)

    const first = await page.evaluate(async () => {
      const r = await fetch('/api/finance/forecast?days=30')
      const j = await r.json()
      return j.points[0].date
    })
    // первая подпись — реальная дата первой точки ряда (не «сегодня», как было раньше)
    await expect(ticks.first()).toHaveText(dm(first))

    const today = page.locator('[data-testid="cash-tick"][data-today="1"]')
    await expect(today).toHaveCount(1)
    await expect(today).toHaveText(/сегодня \d\d\.\d\d/)
  })

  test('на мобильном подсказка по тапу', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'mobile', 'тап только на сенсорном экране')
    await openTab(page, 'finance', { testInfo })
    const svg = page.locator(CHART).first()
    await expect(svg).toBeVisible({ timeout: 20_000 })
    const tip = page.getByTestId('cash-tip').first()
    await expect(tip).toBeHidden()

    await svg.tap({ position: { x: 40, y: 20 } })
    await expect(tip).toBeVisible()
    expect(await tip.innerText()).toMatch(/баланс на \d\d\.\d\d/)
    // повторный тап по той же точке убирает подсказку
    await svg.tap({ position: { x: 40, y: 20 } })
    await expect(tip).toBeHidden()
    await shot(page, 'cash-tip-mobile', { testInfo, fullPage: false })
  })
})