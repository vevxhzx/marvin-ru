// Дизайн-скрины для аудита: 10 экранов × desktop/mobile в design-audit/shots/.
// Вьюпорт (не fullPage): как видит хозяин — на ПК контент по центру с пустотой по бокам.
// Не тест: ничего не ассертит, только снимает. Падает только если страница не открылась.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect } from '../helpers/index.js'
import { TABS, openApp, openTab, expectRendered } from '../helpers/index.js'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const SHOTS = path.resolve(HERE, '..', '..', '..', 'design-audit', 'shots')
const IGNORE = [/\/api\/events\/stream/, /favicon/i]

test.describe('design shots', () => {
  for (const tab of TABS) {
    test(`${tab.key}`, async ({ page }, testInfo) => {
      const mob = testInfo.project.name !== 'desktop'
      const shot = async (suffix) => {
        await page.waitForTimeout(1300) // анимации rise/stagger улеглись
        const dir = path.join(SHOTS, mob ? 'mob' : 'pc')
        fs.mkdirSync(dir, { recursive: true })
        await page.screenshot({ path: path.join(dir, `${tab.key}${suffix}.png`) })
      }
      page.on('pageerror', (e) => { throw new Error(`pageerror ${tab.key}: ${e.message}`) })
      page.on('response', (r) => {
        if (r.status() >= 400 && !IGNORE.some((re) => re.test(r.url()))) {
          throw new Error(`HTTP ${r.status()} ${tab.key}: ${r.url()}`)
        }
      })
      await openApp(page, { testInfo })
      const ready = async (old) => {
        // ждём именно СМЕНУ экрана (старый текст ушёл), а не любой текст:
        // ленивый чанк + ремаунт иначе дают кадр предыдущего экрана
        await page.waitForFunction(
          (prev) => ((document.querySelector('#root')?.innerText || '').trim() !== prev
            && (document.querySelector('#root')?.innerText || '').trim().length > 50),
          old, { timeout: 15000 },
        ).catch(() => {})
        await page.waitForTimeout(800)
      }
      const cur = () => page.evaluate(() => (document.querySelector('#root')?.innerText || '').trim())
      if (mob) {
        // мобильная копия (mapp): нижний бар вместо десктопных вкладок
        const mtab = { today: null, tasks: 'tasks', calendar: 'calendar', finance: 'finance' }[tab.key]
        if (mtab) {
          const before = await cur()
          await page.locator(`[data-testid="m-tab-${mtab}"]`).click()
          await ready(before)
        } else if (tab.key !== 'today') {
          await page.locator('[data-testid="m-tab-more"]').click()
          const tileId = { mind: 'brain' }[tab.key] || tab.key
          const tile = page.locator(`[data-testid="m-more-${tileId}"]`).first()
          try {
            await tile.waitFor({ state: 'visible', timeout: 10000 })
            const before = await cur()
            await tile.click()
            await ready(before)
          } catch (e) {
            await openTab(page, tab.key, { testInfo })
          }
        }
      } else {
        await openTab(page, tab.key, { testInfo })
      }
      await expectRendered(page, tab.title)
      await shot('')
      // второй кадр — проскролл вниз (длинные экраны: контент под фолдом)
      const h = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight)
      if (h > 200) {
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
        await shot('-down')
      }
    })
  }
})
