// Страница «люди»: стадия КЛИЕНТА (вторая сущность, не воронка заказов) —
// бейдж с меткой ручного режима, выпадающий список, фильтр по стадии,
// и «следующий шаг» с датой в карточке человека.
// Скриншоты: tests/e2e/screens/<проект>-people-*.png
import { test, expect, watch, shot, openTab, expectText, expectSheet, closeSheet } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]

test.describe('люди: стадия клиента и следующий шаг', () => {
  test('бейдж со стадией, ручная смена и фильтр по стадии', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openTab(page, 'people', { testInfo })
    await expectText(page, 'СТАДИЯ КЛИЕНТА', { note: 'фильтр по стадии клиента (.label — капсом)' })
    await expectText(page, 'Кофейня «Зерно»', { note: 'демо-клиент' })
    await shot(page, 'people-list', { testInfo })

    // у карточек клиентов есть бейдж + выпадающий список для смены
    const sel = page.getByLabel('Стадия клиента: Кофейня «Зерно»')
    await expect(sel).toBeVisible({ timeout: 15_000 })

    // ручная смена стадии: значение видно и метка «вручную» тоже
    await sel.selectOption('permanent')
    const card = page.locator('section.c').filter({ hasText: 'Кофейня «Зерно»' })
    await expect(card.locator('.badge').filter({ hasText: 'постоянный' }).filter({ hasText: 'вручную' })).toBeVisible({ timeout: 15_000 })
    await shot(page, 'people-stage', { testInfo })

    // фильтр по стадии: остаются только карточки с выбранной стадией
    await page.getByRole('button', { name: /^постоянный/ }).first().click()
    await page.waitForTimeout(400)
    const vals = await page.getByLabel(/^Стадия клиента:/).evaluateAll((els) => els.map((e) => e.value))
    expect(vals.length, 'после фильтра должны остаться клиенты со стадией «постоянный»').toBeGreaterThan(0)
    expect(vals.every((v) => v === 'permanent'), 'фильтр оставил чужие стадии').toBe(true)
    await shot(page, 'people-filter', { testInfo })

    await diag.expectClean('люди: стадия клиента')
  })

  test('следующий шаг с датой — в карточке человека', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openTab(page, 'people', { testInfo })
    await expectText(page, 'Анна Демо', { note: 'демо-человек' })
    await page.locator('section.c').filter({ hasText: 'Анна Демо' }).click()

    const sheet = await expectSheet(page)
    await expect(sheet.getByRole('heading', { name: 'контакт' })).toBeVisible()
    await expectText(page, 'Анна Демо', { note: 'карточка человека открыта' })
    const stepInput = sheet.getByLabel('Следующий шаг', { exact: true })
    await expect(stepInput).toBeVisible({ timeout: 15_000 })

    await stepInput.fill('прислать смету')
    await sheet.getByLabel('Дата следующего шага').fill('2026-10-10')
    await sheet.getByRole('button', { name: 'Сохранить следующий шаг' }).click()
    await expect(sheet.getByText('сохранено')).toBeVisible({ timeout: 15_000 })
    await shot(page, 'people-next-step', { testInfo, fullPage: false })

    // сохранилось — правим ещё раз, чтобы убедиться, что кнопка снова работает
    await stepInput.fill('позвонить')
    await sheet.getByRole('button', { name: 'Сохранить следующий шаг' }).click()
    await expect(sheet.getByText('сохранено')).toBeVisible({ timeout: 15_000 })
    await closeSheet(page)

    await diag.expectClean('люди: следующий шаг')
  })
})
