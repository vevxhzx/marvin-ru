# Второй инстанс в облаке (PythonAnywhere free, ~0 ₽)

Отдельный инстанс: своя база, свой мозг (только облако), свой пароль. Telegram-бота нет —
пользователь открывает сайт с телефона (PWA), VPN не нужен.

## Что нужно один раз

1. Ключ Groq (https://console.groq.com/keys — бесплатно, без карты, лимитов хватит).
   Он же идёт и на мозг, и на быстрый голосовой ввод.
2. Пароль для входа (придумать, 8+ символов) — записать себе, в репозиторий не попадает.
3. Аккаунт PythonAnywhere free.

## Заливка (консоль PythonAnywhere, Bash)

```bash
git clone --depth 1 https://github.com/vevxhzx/marvin-ru.git marvin-hosted
cd marvin-hosted
rm -rf .venv                             # если уже ставили полный набор и квота забита
python3 -m venv .venv && source .venv/bin/activate
pip install --no-cache-dir -r requirements-hosted.txt   # SLIM-набор (~150 МБ): обычный requirements.txt ставит torch 550 МБ и упрётся в квоту 512 МБ!
cp config.example.yaml config.yaml       # дальше правим значения ниже
```

## Настройки (config.yaml инстанса или переменные окружения вкладки Web)

```yaml
setup:
  done: true                  # мастер первого запуска пропущен (он только локальный)
brain:
  mode: "cloud"
  cloud:
    provider: "groq"                # бесплатно, лимитов хватит
    api_key: "ЕГО_GROQ_КЛЮЧ"         # или env CLOUD_API_KEY
server:
  password: "ЕГО_ПАРОЛЬ"        # или env ASSISTANT_PASSWORD
voice:
  stt:
    cloud: true                 # быстрый ввод тем же Groq-ключом
  tts:
    engine: "edge"              # Microsoft, без ключа, быстро и качественно
owner:
  name: "имя"                    # как Марвин к нему обращается
telegram:
  token: ""                     # пусто — бота нет, только сайт
```

Переменные окружения (вместо секретов в файле): `CLOUD_API_KEY`, `ASSISTANT_PASSWORD`.

## WSGI (вкладка Web → WSGI file)

```python
import sys
sys.path.insert(0, "/home/USER/marvin-hosted")
from wsgi import application
```

Static files: `/assets/` → `/home/USER/marvin-hosted/web/site/assets`.
Virtualenv: путь к `.venv`. Потом Reload.

## Как входят

Открывают адрес сайта → экран пароля → вводят пароль один раз (кука на 90 дней).
Никаких ключей и QR не нужно.

## Честные ограничения бесплатного тарифа

- Сайт засыпает без посетителей: первое открытие дня — 30–60 с прогрев.
- Чтобы не ждать прогрев: бесплатный UptimeRobot с HTTP-пингом `https://<сайт>/api/health`
  раз в 5 минут. Воркер не засыпает, сайт открывается сразу. Пинг дешёвый (один JSON).
- Воркер один: планировщик (уборка памяти, ролловеры) работает пока крутится воркер.
  Под WSGI lifespan-хендлеры не выполняются (проверено пробой), поэтому `wsgi.py` крутит
  планировщик в отдельном потоке со своим loop — напоминания, дайджесты и бэкапы живые.
- Без Telegram напоминания не прилетают пушами — видны на сайте (дайджест, «Сегодня»).
- Голосовые: распознавание — тем же Groq-ключом (`voice.stt.cloud: true`), секунды.
  Без ключа — локальный whisper-small на слабом CPU (до минуты). Озвучка — Edge, быстро.
- Трафик/диск free-тарифа хватает с запасом.
- Бэкапы: раз в неделю скачивать `data/jarvis.db` из консоли (`cp data/jarvis.db ~/backup-*.db`).
