// Review D: вид (настройки → «вид»):
//   1) тема: светлая/тёмная/как в системе — атрибут data-theme меняется и переживает reload;
//   2) аккордеон «цвет для каждого раздела» (aria-expanded) и персональный цвет вкладки
//      «финансы»: inline-переменные на #p-fin, персистентность после reload, сброс «как всё».
import { test, expect, watch, shot, openTab, expectText } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]

const themeSection = (page) => page.locator('section.c').filter({
  has: page.getByRole('heading', { name: 'тема и цвет', exact: true }),
})
const colorsButton = (page) => page.getByRole('button', { name: 'цвет для каждого раздела' })
const dataTheme = (page) => page.evaluate(() => document.documentElement.getAttribute('data-theme'))

/**
 * Клик по теме + ожидание, пока выбор уйдёт на сервер.
 * Тема живёт в /api/ui-prefs (общая на весь прогон), а сохранение отложено
 * (debounce в web/src/lib/prefs.js). Без ожидания PUT reload может вернуть
 * старое серверное значение — тест зависит от тайминга и порядка тестов.
 */
async function pickTheme(page, label, expected) {
  const putP = page.waitForResponse(
    (r) => r.request().method() === 'PUT' && r.url().includes('/api/ui-prefs'),
    { timeout: 15_000 },
  )
  await themeSection(page).getByText(label, { exact: true }).click()
  await putP
  await expect.poll(() => dataTheme(page), { timeout: 10_000 }).toBe(expected)
}

test.describe('настройки: вид и цвета', () => {
  test('тема переключается и переживает reload', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    // pullRemote при старте может прислать тему из /api/ui-prefs (общая на прогон) —
    // дожидаемся первого GET, дальше тест сам задаёт состояние.
    const pullP = page.waitForResponse(
      (r) => r.request().method() === 'GET' && r.url().includes('/api/ui-prefs'),
      { timeout: 15_000 },
    )
    await openTab(page, '/settings#look', { testInfo })
    await pullP
    const sec = themeSection(page)
    await expect(sec).toBeVisible()

    // нормализация: не полагаемся на «стенд тёмный по умолчанию» — ставим тёмную сами
    await pickTheme(page, 'тёмная', 'dark')
    await openTab(page, '/settings#look', { testInfo })
    await expect.poll(() => dataTheme(page), { timeout: 10_000 }).toBe('dark')

    await pickTheme(page, 'светлая', 'light')

    // персистентность: reload не сбрасывает тему (значение уже на сервере)
    await openTab(page, '/settings#look', { testInfo })
    await expect.poll(() => dataTheme(page), { timeout: 10_000 }).toBe('light')

    await pickTheme(page, 'тёмная', 'dark')
    await openTab(page, '/settings#look', { testInfo })
    await expect.poll(() => dataTheme(page), { timeout: 10_000 }).toBe('dark')

    // «как в системе» следует за prefers-color-scheme (в стенде — тёмная)
    await pickTheme(page, 'как в системе', 'dark')

    await shot(page, 'settings-theme', { testInfo })
    await diag.expectClean('тема')
  })

  test('аккордеон разделов и цвет вкладки «финансы»', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openTab(page, '/settings#look', { testInfo })
    const acc = colorsButton(page)
    await expect(acc, 'аккордеон закрыт при первом открытии').toHaveAttribute('aria-expanded', 'false')
    await acc.click()
    await expect(acc).toHaveAttribute('aria-expanded', 'true')
    await expectText(page, 'каждый раздел может жить в своём цвете')

    // строка «финансы» внутри аккордеона
    const sec = page.locator('section.c').filter({ hasText: 'цвет для каждого раздела' })
    const finRow = sec.locator('div.flex.flex-wrap').filter({
      has: page.locator('span:text-is("финансы")'),
    })
    await expect(finRow, 'строка цвета «финансы»').toHaveCount(1)

    const hasAcc = async () => String(
      (await page.locator('#p-fin').getAttribute('style')) || '',
    ).includes('--acc')

    // исходного персонального цвета нет
    await openTab(page, '/finance', { testInfo })
    await expect.poll(hasAcc, { timeout: 10_000 }).toBe(false)

    // «зелёный» в строке «финансы» → inline-переменные на #p-fin
    await openTab(page, '/settings#look', { testInfo })
    await colorsButton(page).click()
    await expectText(page, 'каждый раздел может жить в своём цвете')
    const finRow2 = page.locator('section.c')
      .filter({ hasText: 'цвет для каждого раздела' })
      .locator('div.flex.flex-wrap')
      .filter({ has: page.locator('span:text-is("финансы")') })
    await finRow2.getByRole('button', { name: 'зелёный' }).click()
    await expect(finRow2.getByRole('button', { name: 'зелёный' })).toHaveAttribute('aria-pressed', 'true')

    await openTab(page, '/finance', { testInfo })
    await expect.poll(hasAcc, { timeout: 10_000 }).toBe(true)
    await shot(page, 'finance-page-accent', { testInfo })

    // reload — цвет пережил перезагрузку
    await page.reload()
    await expect.poll(hasAcc, { timeout: 10_000 }).toBe(true)

    // сброс строки «финансы» → «как всё» убирает персональный цвет
    await openTab(page, '/settings#look', { testInfo })
    await colorsButton(page).click()
    await expectText(page, 'каждый раздел может жить в своём цвете')
    const finRow3 = page.locator('section.c')
      .filter({ hasText: 'цвет для каждого раздела' })
      .locator('div.flex.flex-wrap')
      .filter({ has: page.locator('span:text-is("финансы")') })
    await finRow3.getByRole('button', { name: 'как всё' }).click()

    await openTab(page, '/finance', { testInfo })
    await expect.poll(hasAcc, { timeout: 10_000 }).toBe(false)

    await diag.expectClean('цвета разделов')
  })
})
