# Мамина копия в облаке (PythonAnywhere free, ~0 ₽)

Отдельный инстанс: своя база, свой мозг (только облако), свой пароль. Telegram-бота нет —
мама открывает сайт с телефона (PWA), VPN не нужен.

## Что нужно от хозяина (один раз)

1. Ключ Groq (https://console.groq.com/keys — бесплатно, без карты, лимитов маме хватит).
   Он же идёт и на мозг, и на быстрый голосовой ввод.
2. Пароль для входа (придумать, 8+ символов) — записать себе, в репозиторий не попадает.
3. Аккаунт PythonAnywhere free.

## Заливка (консоль PythonAnywhere, Bash)

```bash
git clone --depth 1 https://github.com/vevxhzx/marvin-ru.git mom-marvin
cd mom-marvin
rm -rf .venv                             # если уже ставили полный набор и квота забита
python3 -m venv .venv && source .venv/bin/activate
pip install --no-cache-dir -r requirements-mom.txt   # SLIM-набор (~150 МБ): обычный requirements.txt ставит torch 550 МБ и упрётся в квоту 512 МБ!
cp config.example.yaml config.yaml       # дальше правим значения ниже
```

## Настройки (config.yaml мамы или переменные окружения вкладки Web)

```yaml
setup:
  done: true                  # мастер первого запуска пропущен (он только локальный)
brain:
  mode: "cloud"
  cloud:
    provider: "groq"                # бесплатно, лимитов маме хватит
    api_key: "ЕЁ_GROQ_КЛЮЧ"         # или env CLOUD_API_KEY
server:
  password: "ЕЁ_ПАРОЛЬ"        # или env ASSISTANT_PASSWORD
voice:
  stt:
    cloud: true                 # быстрый ввод тем же Groq-ключом
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
- Голосовые: распознавание — тем же Groq-ключом (`voice.stt.cloud: true`), секунды.
  Без ключа — локальный whisper-small на слабом CPU (до минуты). Озвучка — Edge, быстро.
- Трафик/диск free-тарифа маминым объёмам хватит с запасом.
- Бэкапы: раз в неделю скачивать `data/jarvis.db` из консоли (`cp data/jarvis.db ~/backup-*.db`).
