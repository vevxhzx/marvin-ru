// Playwright-стенд для e2e-тестов сайта. Поднимает ядро FastAPI на ВРЕМЕННОЙ демо-БД
// (tests/e2e/serve.py + tests/e2e/demo_db.py) и проверяет собранный сайт web/site.
//
// Безопасность: путь к БД задаёт сам стенд (в %TEMP%), настоящая data/jarvis.db
// используется быть не может — см. tests/e2e/demo_db.py (assert_safe).
//
// Запуск (из web/):
//     npm run test:e2e            # оба проекта: desktop + mobile
//     npm run test:e2e:desktop    # только desktop
//     npx playwright test tests/e2e/specs/orders.spec.js --project=mobile
//
// Один раз после клона/обновления:
//     npm run test:e2e:install    # npx playwright install chromium (только chromium)
import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))          // …/web
const ROOT = path.resolve(HERE, '..')                             // корень репозитория
const E2E_DIR = path.join(ROOT, 'tests', 'e2e')

// Порт стенда. Не 8765 — это порт живого ассистента, его трогать нельзя.
// Фиксированный, а не «случайный»: конфиг читают и webServer, и воркеры тестов —
// значение должно совпадать везде. Свой: E2E_PORT=8917 npm run test:e2e
const PORT = Number(process.env.E2E_PORT || 8917)
const HOST = '127.0.0.1'
const BASE_URL = `http://${HOST}:${PORT}`

// Папка стенда во временном каталоге — настоящая data/ не затрагивается.
// Фиксированная (не по pid): значение читают и webServer, и воркеры тестов.
const WORKDIR = process.env.E2E_WORKDIR || path.join(os.tmpdir(), 'jarvis-e2e-playwright')

// Python: сначала .venv проекта, потом системный.
function pythonBin() {
  const name = process.platform === 'win32' ? 'python.exe' : 'python'
  for (const dir of ['.venv/Scripts', '.venv/bin', 'venv/Scripts', 'venv/bin']) {
    const p = path.join(ROOT, dir, name)
    if (fs.existsSync(p)) return p
  }
  return process.env.E2E_PYTHON || (process.platform === 'win32' ? 'python' : 'python3')
}

export default defineConfig({
  testDir: path.join(E2E_DIR, 'specs'),
  outputDir: path.join(E2E_DIR, 'test-results'),

  // Демо-БД одна на весь прогон, состояние между тестами может меняться — параллелизм выключен.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,

  timeout: 90_000,
  expect: { timeout: 15_000 },

  reporter: process.env.CI ? [['line']] : [['list'], ['html', { outputFolder: path.join(E2E_DIR, 'report'), open: 'never' }]],

  use: {
    baseURL: BASE_URL,
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
    // Приложение по умолчанию тёмное (тема из prefers-color-scheme), поэтому и стенд тёмный:
    // со светлой темой скриншоты не похожи на то, что видит владелец.
    colorScheme: 'dark',
    // Скриншоты и трассы — всегда в tests/e2e/screens (префикс проекта) и test-results.
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'off',
    ignoreHTTPSErrors: true,
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
  },

  // Стенд: ядро FastAPI на демо-БД + статика web/site (её раздаёт сам FastAPI).
  webServer: {
    command: `"${pythonBin()}" "${path.join(E2E_DIR, 'serve.py')}" --host ${HOST} --port ${PORT} --fresh --workdir "${WORKDIR}"`,
    url: `${BASE_URL}/api/health`,
    cwd: ROOT,
    reuseExistingServer: !process.env.CI,   // локально можно переиспользовать уже поднятый стенд
    timeout: 120_000,
    stdout: 'ignore',
    stderr: 'pipe',
    env: {
      E2E_WORKDIR: WORKDIR,
      JARVIS_NO_TG: '1',
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
    },
  },

  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'mobile',
      use: {
        ...devices['Pixel 5'],
        viewport: { width: 375, height: 812 },   // iPhone X по ширине, как просят
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
})