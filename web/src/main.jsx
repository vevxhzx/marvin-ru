import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import { tgBoot } from './lib/tg'

// внутри Telegram сначала входим подписанными данными Telegram, потом рисуем — иначе первые запросы получат 401
tgBoot().finally(() => {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
})
