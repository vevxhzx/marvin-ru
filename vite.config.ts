import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Единый источник фронтенда — папка web/ (React-приложение для сайта).
// Корневая копия src/ + index.html была дублем и перенесена в _archive/web/root-vite-duplicate/.
// Сборка: `npm run build` → web/site/ (единственный output; раздаёт Python-ядро и server.ts в production).
export default defineConfig({
  root: 'web',
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 3000,
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  build: {
    outDir: 'site',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // recharts — отдельно от основного бандла: графики грузятся только на страницах
        // с ними, а не на первом экране. i18n осознанно остаётся в главном чанке
        // (нужен сразу для первого рендера, дробить его нет смысла).
        manualChunks: {
          'vendor-recharts': ['recharts'],
        },
      },
    },
  },
})
