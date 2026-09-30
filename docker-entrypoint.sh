#!/bin/sh
# создаём config.yaml из примера, если его ещё нет (первый запуск) — дальше мастер в браузере
set -e
cd /app
if [ ! -s config.yaml ]; then
  cp config.example.yaml config.yaml
fi
mkdir -p data
exec python run.py "$@"
