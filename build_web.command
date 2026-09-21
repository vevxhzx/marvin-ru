#!/bin/bash
# Пересобрать web/site (нужен Node.js: brew install node).
cd "$(dirname "$0")/web" || exit 1
if ! command -v npm >/dev/null 2>&1; then
  echo "  Нужен Node.js: brew install node"
  exit 1
fi
npm ci && npm run build
echo "  site → $(cd .. && pwd)/web/site"
