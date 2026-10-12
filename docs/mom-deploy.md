# Мамина копия в облаке (PythonAnywhere free, ~0 ₽)

Отдельный инстанс: своя база, свой мозг (только облако), свой пароль. Telegram-бота нет —
мама открывает сайт с телефона (PWA), VPN не нужен.

## Что нужно от хозяина (один раз)

1. Новый API-ключ облака (OpenRouter: https://openrouter.ai/keys) — только для мамы.
2. Пароль для входа (придумать, 8+ символов).
3. Аккаунт PythonAnywhere free.

## Заливка (консоль PythonAnywhere, Bash)

```bash
git clone https://github.com/vevxhzx/marvin-ru.git mom-marvin
cd mom-marvin
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # лёгкий набор, без torch/голоса
cp config.example.yaml config.yaml       # дальше правим значения ниже
```

## Настройки (config.yaml мамы или переменные окружения вкладки Web)

```yaml
setup:
  done: true                  # мастер первого запуска пропущен (он только локальный)
brain:
  mode: "cloud"
  cloud:
    provider: "openrouter"
    api_key: "ЕЁ_КЛЮЧ"          # или env CLOUD_API_KEY
server:
  password: "ЕЁ_ПАРОЛЬ"        # или env ASSISTANT_PASSWORD
voice:
  tts:
    engine: "edge"              # Microsoft, без ключа, быстро и качественно
owner:
  name: "мама"                  # как Марвин к ней обращается
telegram:
  token: ""                     # пусто — бота нет, только сайт
```

Переменные окружения (вместо секретов в файле): `CLOUD_API_KEY`, `ASSISTANT_PASSWORD`.

## WSGI (вкладка Web → WSGI file)

```python
import sys
sys.path.insert(0, "/home/mom/mom-marvin")
from wsgi import application
```

Static files: `/assets/` → `/home/mom/mom-marvin/web/site/assets`.
Virtualenv: путь к `.venv`. Потом Reload.

## Как мама входит

Открывает адрес сайта → экран пароля → вводит пароль один раз (кука на 90 дней).
Никаких ключей и QR ей не нужно.

## Честные ограничения бесплатного тарифа

- Сайт засыпает без посетителей: первое открытие дня — 30–60 с прогрев.
- Воркер один: планировщик (уборка памяти, ролловеры) работает пока крутится воркер.
- Без Telegram напоминания не прилетают пушами — видны на сайте (дайджест, «Сегодня»).
- Голосовые: распознавание — локальный whisper-small на слабом CPU (до минуты) либо
  Groq-ключ в `voice.stt.cloud` (голос уйдёт в облако). Озвучка — Edge, быстро.
- Трафик/диск free-тарифа маминым объёмам хватит с запасом.
- Бэкапы: раз в неделю скачивать `data/jarvis.db` из консоли (`cp data/jarvis.db ~/backup-*.db`).
