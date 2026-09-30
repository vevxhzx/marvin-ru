import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Абсолютный путь к tailwind-конфигу: сборка запускается и из web/, и из корня
// проекта (`npm run build` → vite root=web), а tailwind ищет конфиг от cwd.
const here = path.dirname(fileURLToPath(import.meta.url))

export default {
  plugins: {
    tailwindcss: { config: path.join(here, 'tailwind.config.js') },
    autoprefixer: {},
  },
}
