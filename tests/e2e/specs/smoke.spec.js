// Базовый smoke: главная + все вкладки на чистой демо-БД.
// Проверяет, что приложение поднимается и ни одна страница не «белая»/не сломана.
// Скриншоты: tests/e2e/screens/<проект>-smoke-<вкладка>.png
import { test, expect, TABS, watch, shot, openApp, openTab, clickTab, expectRendered, expectText } from '../helpers/index.js'

// /api/events/stream — живёт вечно, браузер не может его «завершить»: не считаем ошибкой
const IGNORE = [/\/api\/events\/stream/, /favicon/i]

test.describe('smoke: демо-БД', () => {
  test('главная открывается и показывает демо-данные', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openApp(page, { testInfo })
    await expectText(page, 'Зерно', { note: 'демо-клиент должен быть виден на главной' })
    await shot(page, 'smoke-home', { testInfo })

    await diag.expectClean('главная')
  })

  test('все вкладки открываются без белого экрана', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    for (const tab of TABS) {
      await openTab(page, tab.key, { testInfo })
      // страница не просто смонтирована, а что-то нарисовала
      await expectRendered(page, tab.title)
      await shot(page, `smoke-${tab.key}`, { testInfo })
      diag.clear()   // ошибки накапливаем по вкладкам, а не за весь прогон
      await diag.expectClean(tab.title)
    }
  })

  test('вкладки открываются кликом по сайдбару', async ({ page }, testInfo) => {
    // на мобильном сайдбар скрыт, поэтому кликаем только на desktop
    test.skip(testInfo.project.name !== 'desktop', 'сайдбар есть только на desktop')
    const diag = watch(page, { ignore: IGNORE })

    await openApp(page, { testInfo })
    for (const key of ['tasks', 'finance', 'orders']) {
      await clickTab(page, key)
      await expect(page).toHaveURL(new RegExp(key === 'today' ? '/' : `/${key}`))
    }
    await shot(page, 'smoke-sidebar-nav', { testInfo })
    await diag.expectClean('навигация по сайдбару')
  })
})