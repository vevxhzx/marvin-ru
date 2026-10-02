import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import { tgBoot } from './lib/tg'
import { I18nProvider, getLang } from './lib/i18n'
import './lib/sw' // PWA: регистрация service worker (только prod), обновление по клику

// язык ставим до первого рендера, чтобы <html lang> и тексты совпали
document.documentElement.lang = getLang()

/* Стартовый экран из index.html живёт вне #root: пока грузится бандл, видно фон приложения
   и знак, а не белый лист. После первого кадра React убираем его — и по событию, и
   страховочным таймером, чтобы логотип не остался навсегда, если рендер упал. */
const BOOT_MAX_MS = 2500
let booted = false
function dropBoot() {
  if (booted) return
  booted = true
  const el = document.getElementById('boot')
  if (!el) return
  el.classList.add('is-out')          // гаснет transitionом из index.html
  setTimeout(() => el.remove(), 300)
}

// внутри Telegram сначала входим подписанными данными Telegram, потом рисуем — иначе первые запросы получат 401
setTimeout(dropBoot, BOOT_MAX_MS)
tgBoot().finally(() => {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <I18nProvider>
        <App />
      </I18nProvider>
    </React.StrictMode>,
  )
  // два кадра: React уже вставил разметку, дальше стартовый экран не нужен
  requestAnimationFrame(() => requestAnimationFrame(dropBoot))
})