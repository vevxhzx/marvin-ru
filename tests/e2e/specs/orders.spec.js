// UX заказов: главный критерий готовности — «тест 5 секунд»:
// новый пользователь создаёт заказ, двигает его по трём стадиям, записывает оплату и меняет
// стадию клиента, НЕ открывая подсказку «Как это работает».
// Плюс проверка, что у каждой кнопки есть текстовая подпись, тултип или aria-label.
//
// Скриншоты: tests/e2e/screens/<проект>-orders-*.png
// ВАЖНО: Sheet рисуется порталом в body, поэтому текст внутри панели ищем в .sheet, а не в #root.
import { test, expect, watch, shot, openTab, expectText, expectSheet, closeSheet } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]
// у desktop и mobile общая демо-БД, поэтому у каждого проекта свой заказ
const titleFor = (project) => `Ролик для теста «5 секунд»${project === 'mobile' ? ' (телефон)' : ''}`

test.describe('заказы: понятный интерфейс', () => {
  test('при первом заходе показывается подсказка «Как это работает»', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openTab(page, 'orders', { testInfo })
    await expectText(page, 'Как это работает', { note: 'подсказка при первом заходе' })
    await expectText(page, 'Создать заказ', { note: 'шаг 1 подсказки' })
    await expectText(page, 'Записать оплату', { note: 'шаг 3 подсказки' })
    // схема воронки и напоминание, что стадия клиента — другое
    await expectText(page, 'лид → переговоры → клиент → постоянный → спит/ушёл')
    await shot(page, 'orders-howto', { testInfo })

    // сворачивается и открывается кнопкой «?» в шапке
    await page.getByRole('button', { name: 'Свернуть подсказку «Как это работает»' }).click()
    await expect(page.locator('#orders-howto')).toHaveCount(0)
    await page.getByRole('button', { name: 'Показать подсказку «Как это работает»' }).click()
    await expect(page.locator('#orders-howto')).toHaveCount(1)
    await page.getByRole('button', { name: 'Как это работает: 3 шага' }).click()
    await expect(page.locator('#orders-howto')).toHaveCount(0)

    await diag.expectClean('подсказка «Как это работает»')
  })

  test('клик по строке открывает панель заказа со всеми блоками', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openTab(page, 'orders', { testInfo })
    await expectText(page, 'Кофейня «Зерно»', { note: 'демо-клиент' })
    await shot(page, 'orders-list', { testInfo })

    // кнопки «карточка» в строке больше нет: панель и есть карточка заказа
    await expect(page.getByRole('button', { name: 'карточка', exact: true })).toHaveCount(0)

    await page.getByRole('button', { name: /Открыть заказ «Рекламный ролик/ }).click()
    const sheet = await expectSheet(page)
    await expect(sheet).toBeVisible()

    for (const block of ['стадия заказа', 'оплата', 'время', 'клиент', 'заметки и ТЗ', 'история']) {
      await expect(sheet.getByText(block, { exact: true })).toBeVisible()
    }
    // «потерян» требует причину
    await sheet.getByRole('button', { name: 'потерян' }).click()
    await expect(sheet.getByLabel('Причина потери заказа')).toBeVisible()
    await shot(page, 'orders-drawer', { testInfo, fullPage: false })
    await closeSheet(page)

    await diag.expectClean('панель заказа')
  })

  test('тест «5 секунд»: создать заказ → 3 стадии → оплата → стадия клиента, без подсказки', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = titleFor(testInfo.project.name)
    // подсказку не открываем: гасим её заранее, как будто её уже показали и свернули
    await page.addInitScript(() => { try { localStorage.setItem('orders.howto.v1', 'seen') } catch { /* ignore */ } })

    await openTab(page, 'orders', { testInfo })
    await shot(page, 'orders-5sec-before', { testInfo })

    /* 1. создать заказ */
    await page.getByRole('button', { name: 'заказ', exact: true }).first().click()
    const form = await expectSheet(page)
    await expect(form.getByRole('heading', { name: 'новый заказ' })).toBeVisible()
    await form.getByPlaceholder('Монтаж ролика').fill(TITLE)
    await form.getByLabel('сумма').fill('30000')
    await form.getByLabel('клиент').fill('Кофейня «Зерно»')
    await form.getByLabel('Сколько часов планируете').fill('5')
    // стадия — из той же воронки CRM, а не из отдельного списка статусов
    await form.getByRole('button', { name: 'переговоры', exact: true }).click()
    await form.getByRole('button', { name: 'добавить', exact: true }).click()
    await expectText(page, TITLE, { note: 'заказ создан и виден в списке' })

    const row = page.locator('div[aria-label^="Открыть заказ"]').filter({ hasText: TITLE })
    await expect(row).toBeVisible()

    /* 2. три шага по воронке главной кнопкой строки */
    const steps = [['Согласовать ТЗ', 'Взять в работу'], ['Взять в работу', 'Отправить на правки'], ['Отправить на правки', 'Сдать']]
    for (const [click, next] of steps) {
      await row.getByRole('button', { name: click }).click()
      await expect(row.getByRole('button', { name: next })).toBeVisible()
    }

    /* 3. оплата из панели заказа */
    await row.getByText(TITLE, { exact: true }).click()
    const sheet = await expectSheet(page)
    await sheet.getByRole('button', { name: 'записать оплату' }).click()
    const pay = await expectSheet(page)
    await expect(pay.getByRole('heading', { name: 'оплата по заказу' })).toBeVisible()
    await pay.getByRole('button', { name: 'записать', exact: true }).click()
    await expect(sheet.getByText('долга нет')).toBeVisible({ timeout: 15_000 })

    /* 4. стадия клиента — отдельная сущность, ставится вручную */
    const stageSel = sheet.getByLabel('Стадия клиента')
    await expect(stageSel).toBeVisible()
    await stageSel.selectOption('negotiation')
    // ручное значение авто-логика не перетирает — это видно по подписи и кнопке «вернуть авто»
    await expect(sheet.getByRole('button', { name: 'вернуть авто' })).toBeVisible({ timeout: 15_000 })
    await expect(sheet.getByText(/выставлено руками/)).toBeVisible()
    await shot(page, 'orders-5sec-after', { testInfo, fullPage: false })
    await closeSheet(page)

    // подсказку так и не открывали — и весь сценарий без неё прошёл
    await expect(page.locator('#orders-howto')).toHaveCount(0)

    await diag.expectClean('тест «5 секунд»')
  })

  test('канбан: у колонок есть стадия, количество и сумма, пустые объясняют себя', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project

    await openTab(page, 'orders', { testInfo })
    await page.getByRole('button', { name: 'канбан', exact: true }).click()
    // заголовок раздела без загадочных знаков: «канбан», а не «канбан ?»
    await expect(page.getByRole('heading', { name: 'канбан', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: /^канбан\s*\?$/ })).toHaveCount(0)
    // пустые колонки (в фильтре «в работе» стадии сдан/оплачен пусты) объясняют, что делать
    await expectText(page, 'Перетащите карточку сюда', { note: 'пустая колонка' })
    // в шапке колонки — количество и сумма заказов
    await expect(page.getByLabel(/Колонка «в работе»/)).toBeVisible()
    await expect(page.getByLabel(/Колонка «в работе»: заказов \d+, на [\d\s]+ ₽/)).toHaveCount(1)
    await shot(page, 'orders-kanban', { testInfo })

    await diag.expectClean('канбан')
  })

  test('у каждой кнопки есть подпись, тултип или aria-label', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'сканер кнопок нужен один раз — на десктопе')
    const diag = watch(page, { ignore: IGNORE })

    const check = async (note) => {
      const bad = await page.evaluate(() => {
        const out = []
        for (const b of document.querySelectorAll('#root button, .sheet-backdrop button')) {
          const r = b.getBoundingClientRect()
          if (!r.width || !r.height) continue
          const text = (b.innerText || '').trim()
          const label = b.getAttribute('aria-label') || ''
          const tip = b.getAttribute('data-tip') || ''
          const title = b.getAttribute('title') || ''
          if (!text && !label && !tip && !title) out.push(b.outerHTML.slice(0, 140))
          // кнопка-иконка (без видимого текста): и тултип, и aria-label — требование UX
          else if (!text && (!label || (!tip && !title))) out.push(`нет пары aria-label+тултип: ${b.outerHTML.slice(0, 120)}`)
        }
        return out
      })
      expect(bad, `${note}: кнопки без подписи, тултипа и aria-label`).toEqual([])
    }
    const clickIf = async (...args) => {
      const r = page.getByRole('button', ...args).first()
      if (await r.count()) { await r.click(); await page.waitForTimeout(800) }
    }

    await openTab(page, 'orders', { testInfo })
    await page.waitForTimeout(800)
    await check('заказы: список')

    await clickIf({ name: /Открыть заказ/ })
    await check('заказы: панель заказа')
    await closeSheet(page)

    await clickIf({ name: 'заказ', exact: true })
    await check('заказы: форма нового заказа')
    await closeSheet(page)

    await openTab(page, 'people', { testInfo })
    await page.waitForTimeout(800)
    await check('люди: список')

    const person = page.locator('section.c').first()
    if (await person.count()) { await person.click(); await page.waitForTimeout(800) }
    await check('люди: контакт')
    await closeSheet(page)

    await diag.expectClean('сканер кнопок')
  })
})