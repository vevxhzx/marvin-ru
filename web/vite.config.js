import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  // publicDir ('public') копируется в корень outDir по умолчанию — web/public/sw.js
  // становится web/site/sw.js и отдаётся бэкендом как /sw.js (см. PUBLIC_EXACT в core/api/auth.py)
  publicDir: 'public',
  build: { outDir: 'site', emptyOutDir: true },
})
