// Финансы: ручная операция (создание → видна после reload → удаление с подтверждением),
// фильтры и периоды, выписка CSV. Плюс три регрессии, найденные при чтении Finance.jsx:
//   1) TxSheet молча игнорирует нулевую сумму (submit: `if (!a || isNaN(a)) return`);
//   2) период «всё» уходит в API как days=0 → list_transactions(0) возвращает пустоту;
//   3) exportCSV собирает CSV из ВСЕХ txs, а не из отфильтрованного shownTxs.
// Скриншоты: tests/e2e/screens/<проект>-finance-*.png
import fs from 'node:fs'
import { test, expect, watch, shot, openTab, expectSheet } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]
const uniq = (p) => `${p}-${Date.now().toString(36)}`

// вкладки разделов финансов (обзор/операции/счета/…) — прямые дети .pg, вне шапки
const tabsOf = (page) => page.locator('#p-fin > .sg')
// переключатель периода живёт в шапке и подписан title="период: …"
const periodsOf = (page) => page.locator('#p-fin .top .sg[title^="период"]')
const history = (page) => page.locator('section.c').filter({ hasText: 'история операций' })
const rowsOf = (page) => history(page).locator('.rowi')

async function newOperation(page, title, amount) {
  await page.getByText('+ операция', { exact: true }).click()
  const sheet = await expectSheet(page)
  await sheet.getByLabel(/сумма/).fill(String(amount))
  await sheet.getByLabel(/описание/).fill(title)
  await sheet.getByRole('button', { name: 'сохранить', exact: true }).click()
  await sheet.waitFor({ state: 'detached', timeout: 15_000 })
}

test.describe('финансы: операции, фильтры, периоды, выписка', () => {
  test('операция создаётся, переживает reload и удаляется с подтверждением', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = `Трата D ${uniq(testInfo.project.name)}`
    page.on('dialog', (d) => d.accept())   // «Удалить эту операцию?»

    await openTab(page, 'finance', { testInfo })
    await tabsOf(page).getByText('операции', { exact: true }).click()
    // список подгружается асинхронно — ждём появления демо-строк, а не считаем сразу
    await expect.poll(() => rowsOf(page).count(), {
      timeout: 15_000,
      message: 'демо-БД должна иметь операции за 30 дней',
    }).toBeGreaterThan(0)
    const before = await rowsOf(page).count()

    await newOperation(page, TITLE, 111)
    await expect(rowsOf(page).filter({ hasText: TITLE })).toHaveCount(1)

    // данные пришли на сервер — переживают перезагрузку страницы
    await openTab(page, 'finance', { testInfo })
    await tabsOf(page).getByText('операции', { exact: true }).click()
    await expect(rowsOf(page).filter({ hasText: TITLE })).toHaveCount(1, { timeout: 15_000 })
    await shot(page, 'finance-tx-created', { testInfo })

    // удаление — с подтверждением; список возвращается к исходному размеру
    const row = rowsOf(page).filter({ hasText: TITLE })
    await row.locator('button[title="Удалить"]').click()
    await expect(rowsOf(page).filter({ hasText: TITLE })).toHaveCount(0, { timeout: 15_000 })
    await expect(rowsOf(page)).toHaveCount(before)

    await diag.expectClean('операция: создание и удаление')
  })

  test('нулевая сумма: форма не должна молча делать вид, что ничего не случилось', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = `Ноль D ${uniq(testInfo.project.name)}`
    const posts = []
    page.on('request', (r) => { if (r.method() === 'POST' && /\/api\/finance\/transactions/.test(r.url())) posts.push(r) })

    await openTab(page, 'finance', { testInfo })
    await tabsOf(page).getByText('операции', { exact: true }).click()
    await page.getByText('+ операция', { exact: true }).click()
    const sheet = await expectSheet(page)
    await sheet.getByLabel(/сумма/).fill('0')
    await sheet.getByLabel(/описание/).fill(TITLE)

    const save = sheet.getByRole('button', { name: 'сохранить', exact: true })
    await save.click()

    // 1. ноль не должен уйти на сервер
    expect(posts, 'нулевая сумма не должна создавать операцию').toHaveLength(0)
    // 2. форма либо не пускает (кнопка неактивна), либо объясняет причину — но не «тишина»
    const disabled = !(await save.isEnabled())
    const explained = await sheet.getByText(/больше нуля|ноль|пусто|неверн|ошибк|укажите/i).count()
    expect(
      disabled || explained > 0,
      'нулевая сумма: кнопка «сохранить» активна, клик ничего не делает и никакой подсказки нет — форма закрыта молча',
    ).toBe(true)
    await shot(page, 'finance-tx-zero-amount', { testInfo, fullPage: false })

    await diag.expectClean('валидация суммы')
  })

  test('период «всё» показывает всю историю, а не пустой список', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openTab(page, 'finance', { testInfo })
    await tabsOf(page).getByText('операции', { exact: true }).click()
    await expect(rowsOf(page).first()).toBeVisible({ timeout: 15_000 })
    const n30 = await rowsOf(page).count()

    // «7 дн» — история сокращается, но не исчезает
    await periodsOf(page).getByText('7 дн', { exact: true }).click()
    await expect.poll(() => rowsOf(page).count(), { timeout: 15_000 }).toBeLessThan(n30)
    expect(await rowsOf(page).count(), 'за 7 дней операции должны быть').toBeGreaterThan(0)

    // «всё» — та же история, что и за 30 дней, а не пустота
    await periodsOf(page).getByText('всё', { exact: true }).click()
    await page.waitForTimeout(800)
    const nAll = await rowsOf(page).count()
    expect(
      nAll,
      `период «всё» → days=0 → GET /api/finance/transactions?days=0 отдаёт 0 записей: показано ${nAll} из ${n30} (за 30 дней)`,
    ).toBe(n30)
    await shot(page, 'finance-period-all', { testInfo })

    await diag.expectClean('периоды')
  })

  test('фильтр по счёту сужает список, но выписка CSV всё равно несёт всё подряд', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = `Выписка D ${uniq(testInfo.project.name)}`
    page.on('dialog', (d) => d.accept())

    await openTab(page, 'finance', { testInfo })
    await tabsOf(page).getByText('операции', { exact: true }).click()
    await newOperation(page, TITLE, 111)      // одна уникальная строка = весь результат фильтра

    /* фильтр по названию (поиск живёт в соседней секции, а не в «истории операций») */
    const all = await rowsOf(page).count()
    await page.locator('input[placeholder*="поиск"]').fill(TITLE)
    await expect(rowsOf(page)).toHaveCount(1, { timeout: 15_000 })
    expect(all, 'до фильтра строк больше, чем после').toBeGreaterThan(1)

    /* выписка должна повторять то, что видит пользователь */
    let text = null
    try {
      const [dl] = await Promise.all([
        page.waitForEvent('download', { timeout: 12_000 }),
        page.getByText('выписка', { exact: true }).click(),
      ])
      text = fs.readFileSync(await dl.path(), 'utf8')
    } catch (e) {
      throw new Error(`Кнопка «выписка» не запустила скачивание: ${e.message}`)
    }
    const lines = text.replace(/^﻿/, '').split('\n').filter(Boolean)
    expect(lines[0], 'в CSV есть шапка').toMatch(/Дата/)
    expect(
      lines.length - 1,
      `выписка игнорирует фильтр: в списке 1 операция (${TITLE}), а в CSV ${lines.length - 1} строк (exportCSV читает txs, а не shownTxs)`,
    ).toBe(1)
    expect(text).toContain(TITLE)

    await shot(page, 'finance-csv-filter', { testInfo })
    await diag.expectClean('фильтр и выписка')
  })
})
