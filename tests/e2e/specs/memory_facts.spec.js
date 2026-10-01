// Review D: память:
//   1) жизненный цикл факта: добавить → «о вас» → «забыть» уносит в архив → «вернуть» возвращает;
//   2) правка стиля «как вы пишете» — регресс: PUT /api/facts/style раньше отдавал 422,
//      потому что роут `/api/facts/{fid}` перехватывал «style» (mind.py, порядок роутов).
import { test, expect, watch, shot, openTab, expectText } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]
const uniq = (p) => `${p}-${Date.now().toString(36)}`
const factsTab = (page, label) => page.locator('button.pill').filter({ hasText: label })

test.describe('память: факты и стиль', () => {
  test('факт: добавить → «забыть» в архив → «вернуть» обратно', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TEXT = `Факт D ${uniq(testInfo.project.name)}`

    await openTab(page, '/memory', { testInfo })
    // метка «как вы пишете» — класс .label с text-transform: uppercase, innerText отдаёт капсом
    await expectText(page, 'КАК ВЫ ПИШЕТЕ', { note: 'вкладка «о вас» по умолчанию' })

    // добавить
    await page.getByRole('button', { name: 'добавить', exact: true }).click()
    await page.getByPlaceholder(/не ем мясо/).fill(TEXT)
    await page.getByRole('button', { name: 'запомнить', exact: true }).click()
    await expect(page.locator('div.row', { hasText: TEXT })).toHaveCount(1, { timeout: 15_000 })
    await shot(page, 'memory-fact-added', { testInfo })

    // reload — факт на сервере
    await openTab(page, '/memory', { testInfo })
    let row = page.locator('div.row', { hasText: TEXT })
    await expect(row).toHaveCount(1, { timeout: 15_000 })

    // «забыть» → уходит из «о вас»
    await row.first().click()
    await row.getByText('забыть', { exact: true }).click()
    await expect(page.locator('div.row', { hasText: TEXT }), 'факт покинул «о вас»').toHaveCount(0, { timeout: 15_000 })

    // …и лежит в архиве (ничего не стирается)
    await factsTab(page, 'архив').click()
    row = page.locator('div.row', { hasText: TEXT })
    await expect(row, 'факт в архиве').toHaveCount(1, { timeout: 15_000 })

    // «вернуть» → снова «о вас», из архива пропал
    await row.first().click()
    await row.getByText('вернуть', { exact: true }).click()
    await factsTab(page, 'о вас').click()
    await expect(page.locator('div.row', { hasText: TEXT }), 'факт вернулся в «о вас»').toHaveCount(1, { timeout: 15_000 })
    await factsTab(page, 'архив').click()
    await expect(page.locator('div.row', { hasText: TEXT })).toHaveCount(0, { timeout: 15_000 })

    await diag.expectClean('жизненный цикл факта')
  })

  test('правка стиля «как вы пишете»: PUT /api/facts/style без 422', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TEXT = `— коротко и по делу. Факт D ${uniq(testInfo.project.name)}`
    const puts = []
    page.on('response', (r) => {
      if (r.request().method() === 'PUT' && r.url().includes('/api/facts/style')) puts.push(r)
    })

    await openTab(page, '/memory', { testInfo })
    await expectText(page, 'КАК ВЫ ПИШЕТЕ')
    await page.getByText('поправить', { exact: true }).click()
    const ta = page.locator('textarea')
    await expect(ta).toBeVisible()
    await ta.fill(TEXT)
    await page.getByRole('button', { name: 'сохранить', exact: true }).click()

    await expect.poll(() => puts.length, { timeout: 15_000 }).toBeGreaterThan(0)
    const st = puts[0].status()
    expect(st, `PUT /api/facts/style → ${st}: раньше роут /api/facts/{fid} перехватывал «style» и отдавал 422`).toBeLessThan(400)
    await shot(page, 'memory-style', { testInfo })

    // стиль пережил reload
    await openTab(page, '/memory', { testInfo })
    await expectText(page, '— коротко и по делу', { timeout: 15_000 })

    await diag.expectClean('правка стиля')
  })
})
