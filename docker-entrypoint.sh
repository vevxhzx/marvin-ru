#!/bin/sh
set -e
cd /app
if [ ! -s config.yaml ]; then
  cp config.example.yaml config.yaml
fi
mkdir -p data
exec python run.py "$@"
