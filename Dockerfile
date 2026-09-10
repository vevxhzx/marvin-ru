# Ядро ассистента: API + сайт + Telegram + планировщик.
# Голос на ПК (микрофон/озвучка) в контейнере не работает — это отдельный voice.bat на Windows.

# --- 1. собираем сайт (если web/site уже есть в архиве, этот шаг просто пересоберёт его) ---
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- 2. ядро ---
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 ASSISTANT_NO_BROWSER=1 ASSISTANT_DOCKER=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=web /web/site ./web/site
RUN chmod +x docker-entrypoint.sh
VOLUME ["/app/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://127.0.0.1:8765/api/health || exit 1
ENTRYPOINT ["./docker-entrypoint.sh"]
