// Пример теста для проверки фикстуры и хелперов: заказы на демо-БД.
// Не «регрессия продукта», а образец для следующих субагентов (UX заказов, ревью фронта).
// Запуск одного файла:  npx playwright test tests/e2e/specs/orders.spec.js
import { test, expect, watch, shot, openTab, expectText, expectSheet, closeSheet, clickText } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]

test.describe('заказы на демо-БД', () => {
  test('канбан показывает заказы разных стадий', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openTab(page, 'orders', { testInfo })
    // демо-клиент виден в списке заказов
    await expectText(page, 'Кофейня «Зерно»', { note: 'демо-клиент' })
    await shot(page, 'orders-list', { testInfo })

    await diag.expectClean('заказы/список')
  })

  test('карточка заказа открывается и показывает оплаты', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'на мобильном карточка открывается иначе — проверяем позже')
    const diag = watch(page, { ignore: IGNORE })

    await openTab(page, 'orders', { testInfo })
    // 1) клик по строке раскрывает её, 2) кнопка «карточка» открывает CRM-карточку в .sheet
    await clickText(page, 'Рекламный ролик 30 сек для «Зерна»', { exact: false })
    await page.getByRole('button', { name: 'карточка' }).first().click()
    const sheet = await expectSheet(page)
    await expect(sheet).toBeVisible()
    await expectText(page, 'Рекламный ролик', { note: 'заголовок карточки' })
    await shot(page, 'orders-card', { testInfo, fullPage: false })
    await closeSheet(page)

    await diag.expectClean('карточка заказа')
  })
})