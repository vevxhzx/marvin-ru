import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Единый источник фронтенда — папка web/ (React-приложение для сайта).
// Корневая копия src/ + index.html была дублем и перенесена в _archive/web/root-vite-duplicate/.
// Сборка: `npm run build` → dist/ (его раздаёт server.ts в режиме production).
export default defineConfig({
  root: 'web',
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
})
