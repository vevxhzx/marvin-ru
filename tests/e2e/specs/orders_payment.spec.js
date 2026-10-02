// Review D: оплата заказа:
//   1) двойной мгновенный клик по «записать» — оба POST уходят, но доход ровно один
//      (идемпотентный ключ формы), заказ становится «оплачен», долг = 0;
//   2) удаление дохода в финансах возвращает заказ: статус «сдан», остаток снова > 0,
//      кнопка «записать оплату» в панели заказа появляется снова.
import { test, expect, watch, shot, openTab, expectText, expectSheet, closeSheet, confirmSheet } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]
const uniq = (p) => `${p}-${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`
const apiGet = (page, url) => page.evaluate((u) => fetch(u).then((r) => r.json()), url)

async function createOrder(page, TITLE) {
  await page.getByRole('button', { name: 'заказ', exact: true }).first().click()
  const form = await expectSheet(page)
  await expect(form.getByRole('heading', { name: 'новый заказ' })).toBeVisible()
  await form.getByPlaceholder('Монтаж ролика').fill(TITLE)
  await form.getByLabel('сумма').fill('10000')
  await form.getByLabel('клиент').fill('Кофейня «Зерно»')
  await form.getByLabel('Сколько часов планируете').fill('2')
  await form.getByRole('button', { name: 'переговоры', exact: true }).click()
  await form.getByRole('button', { name: 'добавить', exact: true }).click()
  await form.waitFor({ state: 'detached', timeout: 15_000 })
  await expectText(page, TITLE, { note: 'заказ создан' })
}

async function orderIdByTitle(page, TITLE) {
  const list = await apiGet(page, '/api/orders')
  const o = (Array.isArray(list) ? list : []).find((x) => x.title === TITLE)
  return o ? o.id : null
}

// открыть панель заказа и форму оплаты
async function openPaySheet(page, TITLE) {
  const row = page.locator('div[aria-label^="Открыть заказ"]').filter({ hasText: TITLE })
  await row.getByText(TITLE, { exact: true }).click()
  const drawer = await expectSheet(page)
  await drawer.getByRole('button', { name: 'записать оплату' }).click()
  const pay = await expectSheet(page)
  await expect(pay.getByRole('heading', { name: 'оплата по заказу' })).toBeVisible()
  return { drawer, pay }
}

test.describe('заказы: оплата', () => {
  test('двойной клик по «записать» создаёт одну оплату (идемпотентность)', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = `Оплата D ${uniq(testInfo.project.name)}`
    await page.addInitScript(() => { try { localStorage.setItem('orders.howto.v1', 'seen') } catch { /* ignore */ } })

    const payPosts = []
    page.on('request', (r) => {
      if (r.method() === 'POST' && /\/api\/orders\/\d+\/payments/.test(r.url())) payPosts.push(r)
    })

    await openTab(page, 'orders', { testInfo })
    await createOrder(page, TITLE)
    const oid = await orderIdByTitle(page, TITLE)
    expect(oid, 'заказ должен найтись в /api/orders').toBeTruthy()

    const { drawer, pay } = await openPaySheet(page, TITLE)

    // два мгновенных клика: оба POST уходят до первого ответа сервера
    const btn = pay.getByRole('button', { name: 'записать', exact: true })
    await btn.evaluate((b) => { b.click(); b.click() })
    await expect(pay.getByRole('heading', { name: 'оплата по заказу' })).toHaveCount(0, { timeout: 20_000 })

    expect(payPosts.length, 'оба клика должны уйти на сервер (иначе тест ничего не проверяет)')
      .toBeGreaterThanOrEqual(2)

    // сервер: одна оплата, заказ оплачен, долга нет
    await expect.poll(async () => (await apiGet(page, `/api/orders/${oid}`)).payments?.length, { timeout: 15_000 }).toBe(1)
    const o = await apiGet(page, `/api/orders/${oid}`)
    expect(o.status, 'статус заказа').toBe('paid')
    expect(o.left, 'остаток долга').toBe(0)

    // и ровно один доход с названием заказа
    const txs = await apiGet(page, '/api/finance/transactions?days=3650')
    const income = (Array.isArray(txs) ? txs : [])
      .filter((t) => t.kind === 'income' && String(t.note || '').includes(TITLE))
    expect(income.length, 'двойной клик не должен создавать второй доход').toBe(1)

    await expect(drawer.getByText('долга нет')).toBeVisible({ timeout: 15_000 })
    await shot(page, 'orders-paid', { testInfo })
    await closeSheet(page)
    await diag.expectClean('идемпотентность оплаты')
  })

  test('удаление дохода возвращает заказ: «сдан» и кнопка «записать оплату» снова есть', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = `Возврат D ${uniq(testInfo.project.name)}`
    await page.addInitScript(() => { try { localStorage.setItem('orders.howto.v1', 'seen') } catch { /* ignore */ } })

    await openTab(page, 'orders', { testInfo })
    await createOrder(page, TITLE)
    const oid = await orderIdByTitle(page, TITLE)
    expect(oid, 'заказ должен найтись в /api/orders').toBeTruthy()

    // полная оплата одним кликом
    const { drawer, pay } = await openPaySheet(page, TITLE)
    await pay.getByRole('button', { name: 'записать', exact: true }).click()
    await expect(pay.getByRole('heading', { name: 'оплата по заказу' })).toHaveCount(0, { timeout: 20_000 })
    await expect(drawer.getByText('долга нет')).toBeVisible({ timeout: 15_000 })
    let o = await apiGet(page, `/api/orders/${oid}`)
    expect(o.status, 'заказ должен стать «оплачен»').toBe('paid')
    await closeSheet(page)

    // удаляем доход в финансах (по названию заказа)
    await openTab(page, 'finance', { testInfo })
    await page.locator('#p-fin > .sg').getByText('операции', { exact: true }).click()
    const history = page.locator('section.c').filter({ hasText: 'история операций' })
    // поиск — в секции фильтров рядом с «историей операций», не внутри неё
    await page.locator('input[placeholder*="поиск"]').fill(TITLE)
    const rows = history.locator('.rowi')
    await expect(rows.filter({ hasText: TITLE }), 'доход по заказу в истории').toHaveCount(1, { timeout: 15_000 })
    await rows.filter({ hasText: TITLE }).locator('button[title="Удалить"]').click()
    await confirmSheet(page)   // подтверждение удаления — шторка приложения (ui.jsx Confirm)
    await expect(rows.filter({ hasText: TITLE })).toHaveCount(0, { timeout: 15_000 })

    // заказ снова «сдан» и ждёт оплаты
    o = await apiGet(page, `/api/orders/${oid}`)
    expect(o.status, 'после удаления дохода статус').toBe('done')
    expect(o.left, 'остаток к оплате вернулся').toBeGreaterThan(0)

    // и в интерфейсе кнопка оплаты снова доступна
    await openTab(page, 'orders', { testInfo })
    // после удаления дохода статус «сдан» (done): вкладка по умолчанию «в работе»
    // показывает только new/work/review (Orders.jsx, VIEWS) — открываем «все»
    await page.getByRole('button', { name: 'все', exact: true }).click()
    const row = page.locator('div[aria-label^="Открыть заказ"]').filter({ hasText: TITLE })
    await row.getByText(TITLE, { exact: true }).click()
    const drawer2 = await expectSheet(page)
    await expect(drawer2.getByRole('button', { name: 'записать оплату' })).toBeVisible()
    await shot(page, 'orders-payment-returned', { testInfo })
    await closeSheet(page)

    await diag.expectClean('возврат оплаты')
  })
})
