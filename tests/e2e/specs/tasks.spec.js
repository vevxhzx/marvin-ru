// Review D: задачи — форма листа (pills приоритета/срока, «на день» → дата), чекбокс
// и вкладка «выполнено», правило «задача: …» из чата: карточка подтверждения, отмена
// командой «отмена» (рабочий путь) и кнопка «отменить последнее действие» (находка D6).
import { test, expect, watch, shot, openTab, expectText, expectSheet } from '../helpers/index.js'

const IGNORE = [/\/api\/events\/stream/, /favicon/i]
const uniq = (p) => `${p}-${Date.now().toString(36)}`

test.describe('задачи: форма, чекбокс, правило из чата', () => {
  test('лист создания: pills приоритета, «на день» открывает дату, задача переживает reload', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = `E2E задача D ${uniq(testInfo.project.name)}`

    await openTab(page, '/tasks', { testInfo })
    await page.getByText('+ задача', { exact: true }).click()
    const sheet = await expectSheet(page)
    await expect(sheet.getByRole('heading', { name: 'новая задача' })).toBeVisible()

    await sheet.getByLabel('что сделать').fill(TITLE)
    // pills приоритета и срока присутствуют
    for (const p of ['важно', 'обычная', 'низкая']) await expect(sheet.getByText(p, { exact: true })).toBeVisible()
    for (const w of ['без срока', 'на день', 'ко времени']) await expect(sheet.getByText(w, { exact: true })).toBeVisible()

    // «на день» раскрывает выбор даты
    await sheet.getByText('на день', { exact: true }).click()
    await expect(sheet.locator('input[type="date"]')).toBeVisible()

    await sheet.getByRole('button', { name: 'добавить', exact: true }).click()
    await sheet.waitFor({ state: 'detached', timeout: 15_000 })
    await expectText(page, TITLE, { note: 'задача создана' })
    await shot(page, 'tasks-created', { testInfo })

    // данные на сервере — переживают перезагрузку
    await openTab(page, '/tasks', { testInfo })
    await expectText(page, TITLE, { note: 'задача пережила reload' })

    await diag.expectClean('форма задачи')
  })

  test('чекбокс закрывает задачу — она уходит во вкладку «выполнено»', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = `E2E закрыть D ${uniq(testInfo.project.name)}`

    await openTab(page, '/tasks', { testInfo })
    await page.getByText('+ задача', { exact: true }).click()
    const sheet = await expectSheet(page)
    await sheet.getByLabel('что сделать').fill(TITLE)
    await sheet.getByRole('button', { name: 'добавить', exact: true }).click()
    await sheet.waitFor({ state: 'detached', timeout: 15_000 })
    await expectText(page, TITLE)

    const row = page.locator('#p-tasks .rowi', { hasText: TITLE })
    await expect(row, 'свежая задача в списке «открытые»').toHaveCount(1)
    await row.locator('input[aria-label="закрыть задачу"]').click()
    await expect(row, 'закрытая задача ушла из открытых').toHaveCount(0, { timeout: 15_000 })

    // …и появилась во вкладке «выполнено»
    await page.locator('.top .sg').getByText('выполнено', { exact: true }).click()
    await expectText(page, TITLE, { note: 'задача во вкладке «выполнено»' })
    await expect(page.locator('#p-tasks .rowi', { hasText: TITLE })).toHaveCount(1)
    await shot(page, 'tasks-done-tab', { testInfo })

    await diag.expectClean('закрытие задачи')
  })

  // Поток отмены проверяем рабочим путём — командой «отмена» (UNDO_RX, agent.py:565).
  // Кнопка «отменить» в шторке чата проверяется отдельным тестом ниже (находка D6).
  test('чат: «задача: …» создаёт задачу, команда «отмена» её удаляет', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = `чат-задача D ${uniq(testInfo.project.name)}`
    // в ответе бота первая буква заглавная («Чат-задача …»), поэтому сверяем ASCII-суффикс
    const SUFFIX = TITLE.split(' ').slice(1).join(' ')

    const taskExists = () => page.evaluate(
      (t) => fetch('/api/tasks?all=true').then((r) => r.json())
        .then((l) => Array.isArray(l) && l.some(
          (x) => String(x.title || '').trim().toLowerCase() === t.trim().toLowerCase(),
        )),
      TITLE,
    )

    await openTab(page, '/', { testInfo })
    await page.keyboard.press('Control+j')
    const chat = page.locator('.sheet-backdrop')
    await expect(chat.locator('textarea')).toBeVisible()
    await chat.locator('textarea').fill(`задача: ${TITLE}`)
    // Enter в textarea уходит в send() (onKey формы композера)
    await chat.locator('textarea').press('Enter')

    // правило сработало: задача создана на сервере и бот ответил карточкой
    await expect.poll(taskExists, {
      timeout: 30_000,
      message: 'задача из чата появилась в /api/tasks',
    }).toBe(true)
    await expect(
      chat.locator('.msg-bot').filter({ hasText: SUFFIX }),
      'бот ответил на «задача: …»',
    ).toBeVisible({ timeout: 30_000 })
    await shot(page, 'chat-task-card', { testInfo })

    // отмена той же командой из чата (правило, offline)
    await chat.locator('textarea').fill('отмена')
    await chat.locator('textarea').press('Enter')

    await expect.poll(taskExists, {
      timeout: 15_000,
      message: 'после «отмены» задача удалена из /api/tasks',
    }).toBe(false)

    await diag.expectClean('чат: задача и отмена')
  })

  // D6 (P2, закрыт): кнопка «отменить последнее действие» в шторке чата жила один RTT —
  // send() делал bump() → эффект истории перезагружал ленту → fromServer() выбрасывал
  // actions → canUndo = false. Теперь actions переносятся через историю, и кнопка
  // остаётся доступной, пока действие не отменено и не вышло за возраст (24 ч).
  // Проверяем ОБА признака: кнопка появляется (даже если лента догружается с опозданием)
  // и НЕ гаснет через пару секунд после ответа.
  test('шторка чата: кнопка «отменить последнее действие» остаётся доступной после ответа', async ({ page }, testInfo) => {
    const diag = watch(page, { ignore: IGNORE })
    page.__e2eProject = testInfo.project
    const TITLE = `чат-кнопка D ${uniq(testInfo.project.name)}`
    const SUFFIX = TITLE.split(' ').slice(1).join(' ')

    await openTab(page, '/', { testInfo })
    await page.keyboard.press('Control+j')
    const chat = page.locator('.sheet-backdrop')
    await expect(chat.locator('textarea')).toBeVisible()
    await chat.locator('textarea').fill(`задача: ${TITLE}`)
    await chat.locator('textarea').press('Enter')

    // ответ пришёл, действие действительно выполнено — отменять есть что
    await expect(chat.locator('.msg-bot').filter({ hasText: SUFFIX })).toBeVisible({ timeout: 30_000 })
    await expect.poll(async () => page.evaluate(
      (t) => fetch('/api/tasks?all=true').then((r) => r.json())
        .then((l) => Array.isArray(l) && l.some(
          (x) => String(x.title || '').trim().toLowerCase() === t.trim().toLowerCase(),
        )),
      TITLE,
    ), { timeout: 15_000, message: 'задача создана — кнопка отмены должна быть доступна' }).toBe(true)

    const undoBtn = chat.getByRole('button', { name: /отменить/ })
    await expect(
      undoBtn,
      'кнопка «отменить последнее действие» должна появиться после ответа (D6)',
    ).toBeVisible({ timeout: 15_000 })

    // окно живого ответа закрылось, история перезагрузилась — кнопка обязана ОСТАТЬСЯ
    await page.waitForTimeout(2_000)
    await expect(
      undoBtn,
      'кнопка «отменить последнее действие» гаснет через пару секунд — история всё ещё '
      + 'перетирает actions (fromServer, Chat.jsx:20) — D6',
    ).toBeVisible({ timeout: 2_000 })

    await diag.expectClean('кнопка отмены в шторке')
  })
})
