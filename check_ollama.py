# -*- coding: utf-8 -*-
"""Диагностика связи Джарвис ↔ Ollama. Запуск:  .venv\\Scripts\\python.exe check_ollama.py"""
import asyncio, os, sys
if sys.platform == "win32":
    os.system("chcp 65001 >nul")
    sys.stdout.reconfigure(encoding="utf-8")

import httpx
from core.brain import llm

async def main():
    print(f"Адрес Ollama из настроек: {llm.OLLAMA_URL}   модель: {llm.OLLAMA_MODEL}")
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        if os.environ.get(k):
            print(f"  ! В системе задан прокси {k}={os.environ[k]} — для Ollama игнорируем")
    for url in {llm.OLLAMA_URL, "http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"}:
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as c:
                r = await c.get(url + "/api/tags")
                names = [m["name"] for m in r.json().get("models", [])]
                print(f"  OK   {url}  → модели: {', '.join(names) or 'нет'}")
        except Exception as e:
            print(f"  FAIL {url}  → {type(e).__name__}: {e}")
    print("\nПробую задать вопрос модели (первый раз может занять 10–30 сек)...")
    try:
        out = await llm.ollama_chat([{"role": "user", "content": "Ответь одним словом: работаешь?"}])
        print("  Ответ модели:", out["content"])
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")

asyncio.run(main())
input("\nEnter — закрыть")
