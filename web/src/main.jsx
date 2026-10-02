import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import { tgBoot } from './lib/tg'
import { I18nProvider, getLang } from './lib/i18n'
import './lib/sw' // PWA: регистрация service worker (только prod), обновление по клику

// язык ставим до первого рендера, чтобы <html lang> и тексты совпали
document.documentElement.lang = getLang()

// внутри Telegram сначала входим подписанными данными Telegram, потом рисуем — иначе первые запросы получат 401
tgBoot().finally(() => {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <I18nProvider>
        <App />
      </I18nProvider>
    </React.StrictMode>,
  )
})
