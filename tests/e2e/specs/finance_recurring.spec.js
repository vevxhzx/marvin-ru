// Финансы (новое): годовой платёж заводится из формы с месяцем; пауза оставляет
// карточку видимой («платёж на паузе», а не исчезновение); счёт-кредитка показывает
// долг и не входит в баланс на руках — трата с неё растёт в долг.
// Демо-БД общая на прогон: за собой прибираем (транзакцию и счёт удаляем).
import { test, expect, watch, openTab, expectSheet, openAdd } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]
const uniq = (p) => `${p}-${Date.now().toString(36)}`
const tabsOf = (page) => page.locator('#p-fin > .sg')
const recCards = (page) => page.locator('#p-fin section.gc-subs')

const api = (page, path, opts) => page.evaluate(
  ([p, o]) => fetch(p, o).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status} ${p}`)))),
  [path, opts],
)

test.describe('финансы: годовой платёж, пауза, кредитка', () => {
  test('годовой платёж заводится из формы с месяцем, пауза не прячет карточку', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = `Сертификат ${uniq(testInfo.project.name)}`

    await openTab(page, 'finance', { testInfo })
    await tabsOf(page).getByText('регулярные', { exact: true }).click()

    await openAdd(page, { testInfo, label: '+ платёж' })
    const sheet = await expectSheet(page)
    await sheet.getByLabel(/название/).fill(TITLE)
    await sheet.getByLabel(/сумма/).fill('1700')
    await sheet.getByRole('button', { name: 'год', exact: true }).click()   // период → каждый год
    await sheet.getByLabel(/день списания/).fill('23')
    await sheet.locator('select').first().selectOption('8')                 // август
    await sheet.getByRole('button', { name: 'сохранить', exact: true }).click()
    await sheet.waitFor({ state: 'detached', timeout: 15_000 })

    // на сервере — годовой, ближайшая дата в августе, 23-го
    const all = await api(page, '/api/finance/recurring?all=true')
    const rec = all.find((x) => x.title === TITLE)
    expect(rec, 'годовой платёж создан').toBeTruthy()
    expect(rec.period).toBe('yearly')
    expect(new Date(rec.next_date).getMonth() + 1).toBe(8)
    expect(new Date(rec.next_date).getDate()).toBe(23)

    // тумблер паузы: карточка остаётся на месте и честно подписана
    const card = recCards(page).filter({ hasText: TITLE })
    await expect(card).toHaveCount(1)
    await card.locator('button[role="switch"]').click()
    await expect(card).toHaveCount(1)
    await expect(card).toContainText('на паузе')

    await diag.expectClean('годовой платёж и пауза')
  })

  test('счёт-кредитка: показывается долгом, трата растит долг, баланс не трогает', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const CARD = `Кредитка ${uniq(testInfo.project.name)}`

    // заводим счёт-кредитку как пользователь — через форму
    await openTab(page, 'finance', { testInfo })
    await tabsOf(page).getByText('счета', { exact: true }).click()
    await openAdd(page, { testInfo, label: '+ счёт' })
    const sheet = await expectSheet(page)
    await sheet.getByLabel(/Название счёта/).fill(CARD)
    await sheet.locator('select').first().selectOption({ label: 'кредитка' })
    await sheet.getByLabel(/долг сейчас/).fill('5000')
    await sheet.getByRole('button', { name: 'сохранить', exact: true }).click()
    await sheet.waitFor({ state: 'detached', timeout: 15_000 })

    // карточка счёта: подпись «кредитка» и сумма долга
    const card = page.locator('#p-fin section.fg-acct').filter({ hasText: CARD })
    await expect(card).toContainText('кредитка')
    await expect(card).toContainText('5 000')

    const acc = (await api(page, '/api/finance/accounts')).find((a) => a.name === CARD)
    expect(acc.kind).toBe('debt_only')
    expect(acc.balance).toBe(-5000)

    const before = await api(page, '/api/finance/summary')
    const tx = await api(page, '/api/finance/transactions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount: 1700, kind: 'expense', category: 'Техника', note: 'сертификат', account: CARD }),
    })
    const after = await api(page, '/api/finance/summary')
    const acc2 = (await api(page, '/api/finance/accounts')).find((a) => a.name === CARD)
    expect(acc2.balance).toBe(-6700)
    expect(after.total_balance).toBe(before.total_balance)

    // убираем за собой: операция, затем счёт (иначе счёт с операциями не удалить)
    await api(page, `/api/finance/transactions/${tx.id}`, { method: 'DELETE' })
    await api(page, `/api/finance/accounts/${acc.id}`, { method: 'DELETE' })

    await diag.expectClean('счёт-кредитка')
  })
})