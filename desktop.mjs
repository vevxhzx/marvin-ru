#!/usr/bin/env node
/**
 * Джарвис — Автономный запуск в отдельном окне приложения (Windows / macOS / Linux)
 * Запускает локальный сервер и открывает проекцию веб-интерфейса в изолированном
 * нативном окне приложения без вкладок и адресной строки браузера (WebView2 / App Mode).
 */
import { spawn } from 'child_process'
import http from 'http'

const PORT = process.env.PORT || 3000
const URL = `http://localhost:${PORT}`

function checkServerReady(timeout = 15000) {
  const start = Date.now()
  return new Promise((resolve, reject) => {
    const check = () => {
      const req = http.get(`${URL}/api/health`, (res) => {
        if (res.statusCode === 200) resolve(true)
        else setTimeout(check, 300)
      })
      req.on('error', () => {
        if (Date.now() - start > timeout) {
          reject(new Error('Таймаут ожидания запуска сервера Джарвиса'))
        } else {
          setTimeout(check, 300)
        }
      })
    }
    check()
  })
}

function launchWindow() {
  console.log(`[Джарвис] Открытие изолированного окна приложения: ${URL}`)

  const platform = process.platform
  let cmd = ''
  let args = []

  if (platform === 'win32') {
    // Windows: Edge или Chrome в режиме отдельного автономного окна
    cmd = 'msedge'
    args = [`--app=${URL}`, '--window-size=1280,840', '--window-position=center', '--app-id=jarvis-assistant']
  } else if (platform === 'darwin') {
    // macOS
    cmd = 'open'
    args = ['-n', '-a', 'Google Chrome', '--args', `--app=${URL}`]
  } else {
    // Linux
    cmd = 'google-chrome'
    args = [`--app=${URL}`, '--window-size=1280,840']
  }

  const child = spawn(cmd, args, { detached: true, stdio: 'ignore' })
  child.on('error', () => {
    // Fallback на стандартное открытие
    console.log('[Джарвис] Запуск через стандартный браузер...')
    if (platform === 'win32') spawn('cmd', ['/c', 'start', URL], { detached: true, stdio: 'ignore' })
    else if (platform === 'darwin') spawn('open', [URL], { detached: true, stdio: 'ignore' })
    else spawn('xdg-open', [URL], { detached: true, stdio: 'ignore' })
  })
}

async function main() {
  console.log('--------------------------------------------------')
  console.log('🤖 Джарвис — Персональный ассистент')
  console.log('--------------------------------------------------')

  try {
    await checkServerReady(3000)
    launchWindow()
  } catch {
    console.log('[Джарвис] Ожидание готовности сервера...')
    try {
      await checkServerReady(15000)
      launchWindow()
    } catch (e) {
      console.error(e.message)
    }
  }
}

main()
