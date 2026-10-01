// Мост к @playwright/test.
//
// Почему он нужен: тесты лежат в tests/e2e/ (вместе с хелперами и скриншотами), а пакет
// @playwright/test установлен как devDependency в web/ — Node ищет node_modules вверх по дереву
// от tests/e2e/ и там его нет. Этот файл резолвит тот самый пакет из web/node_modules,
// поэтому в тестах можно писать так же, как обычно:
//
//     import { test, expect } from '../helpers/index.js'
//
// Если потом решите перенести тесты внутрь web/ — этот файл можно удалить, импорты
// '@playwright/test' заработают сами.
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const WEB = path.resolve(HERE, '..', '..', '..', 'web')

// require из web/ — резолвит @playwright/test из web/node_modules
const requireFromWeb = createRequire(path.join(WEB, 'package.json'))
const pw = requireFromWeb('@playwright/test')

export const test = pw.test
export const expect = pw.expect
export const chromium = pw.chromium
export const devices = pw.devices
export const defineConfig = pw.defineConfig
export default pw