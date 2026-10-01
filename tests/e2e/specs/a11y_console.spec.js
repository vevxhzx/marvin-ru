// Review D: доступность и консоль:
//   1) фокус-ловушка: Tab внутри открытой шторки не должен уводить фокус за её пределы
//      (в Sheet есть только обработчик Esc — проверка на дефект);
//   2) Esc закрывает шторку; поля главных форм подписаны (getByLabel их находит);
//   3) сканер дублей id внутри #root по всем вкладкам.
// Сканеры гоняются один раз — на десктопе (как существующий сканер кнопок в orders.spec.js).
import { test, expect, watch, openTab, expectSheet } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]
const SCAN_TABS = ['/', '/tasks', '/calendar', '/finance', '/orders', '/mind', '/board', '/people', '/memory', '/settings']

test.describe('a11y и консоль', () => {
  test('Tab не уводит фокус из открытой шторки (фокус-ловушка)', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'проверка фокуса нужна один раз — на десктопе')
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openTab(page, '/tasks', { testInfo })
    await page.getByText('+ задача', { exact: true }).click()
    const sheet = await expectSheet(page)
    await sheet.getByLabel('что сделать').focus()

    const escaped = []
    for (let i = 0; i < 20; i++) {
      await page.keyboard.press('Tab')
      const inside = await page.evaluate(() => {
        const el = document.activeElement
        return !!(el && el.closest && el.closest('.sheet-backdrop'))
      })
      if (!inside) {
        escaped.push(await page.evaluate(() => (document.activeElement?.outerHTML || 'document.body').slice(0, 140)))
        break
      }
    }
    expect(
      escaped,
      'Tab увёл фокус из шторки за её пределы: в Sheet нет focus trap (только Esc), Tab уходит под шторку на страницу'
        + (escaped.length ? ` → ${escaped.join(' | ')}` : ''),
    ).toEqual([])

    // Esc при этом шторку закрывает — это работает
    await page.keyboard.press('Escape')
    await sheet.waitFor({ state: 'detached', timeout: 10_000 })
    await diag.expectClean('фокус-ловушка')
  })

  test('Esc закрывает шторку, поля формы задачи подписаны', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'сканер подписей нужен один раз — на десктопе')
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openTab(page, '/tasks', { testInfo })
    await page.getByText('+ задача', { exact: true }).click()
    const sheet = await expectSheet(page)
    // подписи: Field оборачивает control в <label>
    for (const label of ['что сделать', 'приоритет', 'когда', 'проект']) {
      await expect(sheet.getByText(label, { exact: true }), `подпись «${label}»`).toBeVisible()
    }
    await expect(sheet.getByLabel('что сделать')).toBeVisible()

    await page.keyboard.press('Escape')
    await sheet.waitFor({ state: 'detached', timeout: 10_000 })

    await diag.expectClean('подписи и Esc')
  })

  test('в #root нет дублирующихся id (все вкладки)', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'сканер id нужен один раз — на десктопе')
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    for (const path of SCAN_TABS) {
      await openTab(page, path, { testInfo })
      const dups = await page.evaluate(() => {
        const seen = new Map()
        for (const el of document.querySelectorAll('#root [id]')) {
          seen.set(el.id, (seen.get(el.id) || 0) + 1)
        }
        return [...seen.entries()].filter(([, n]) => n > 1).map(([id, n]) => `${id} ×${n}`)
      })
      expect(dups, `дубли id на ${path}`).toEqual([])
      diag.clear()
    }

    await diag.expectClean('обход вкладок')
  })
})
