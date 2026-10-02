# Установка на macOS

Инструкция для человека **без** Mac под рукой: что нажать, что доставить заранее и
что делать, если пошло не так. Для установки в режиме «приложение со значком в
строке меню» см. также [`mac/README.md`](../mac/README.md).

---

## Что нужно

| Что | Обязательно | Как поставить |
|---|---|---|
| **macOS 12 и новее** (проверено логикой скриптов: 12+ / 13+ / 14+) | да | — |
| **Python 3.10–3.14** | да | `brew install python@3.12` или [python.org](https://www.python.org/downloads/macos/) |
| **~1 ГБ свободного места** | да | базовая установка; голосовой аддон сверху ещё ~3 ГБ |
| **Homebrew** | нет, но очень желательно | [brew.sh](https://brew.sh) — одной командой, `sudo` не нужен |
| **Node.js** | нет | нужен только если будете пересобирать сайт (`build_web.command`) |
| **ffmpeg** | нет | `brew install ffmpeg` — нужен для нестандартных аудио/видео |
| **Ollama** | нет | [ollama.com/download](https://ollama.com/download), если хотите локальный мозг |
| **Tailscale** | нет | только чтобы зайти с телефона из другой сети |

> **Главная ловушка Apple Silicon.** `python3` на свежем Mac — это python из
> **Xcode Command Line Tools**, там обычно **3.9**, а проекту нужно **3.10+**.
> Установщик это проверяет и сам скажет, что делать, но проще сразу поставить
> Homebrew: `brew install python@3.12`.

---

## Вариант 1. «Приложение» (рекомендуется)

1. Скачайте ZIP репозитория и распакуйте **в свою папку** — например `~/Assistant`
   (не в `/Applications`, не в `~/Downloads`: нужны права на запись).
2. В Finder: правый клик по **`Install-Mac.command`** → **«Открыть»**. Первый раз
   macOS спросит подтверждение — нажмите «Открыть» ещё раз.
   *Если файла не видно или он не открывается:*
   ```bash
   cd ~/Assistant
   chmod +x *.command mac/*.sh
   xattr -dr com.apple.quarantine .
   ./Install-Mac.command
   ```
3. Установщик: создаст `.venv` (2–5 минут), поставит зависимости из
   `requirements-mac.txt`, создаст `config.yaml`, соберёт
   `~/Applications/J.A.R.V.I.S..app` и спросит про автозапуск.

**Про `sudo`:** установка его не требует и не просит. Всё ставится в вашу папку
проекта и в `~/.venv`. Если macOS требует пароль — это **Гейткипер или брандмауэр**,
а не установщик (см. «Типичные ошибки»).

---

## Вариант 2. Обычное окно Терминала

Если значок в строке меню не нужен, всё то же самое делается без `.app`:

```bash
cd ~/Assistant
./Install-Mac.command     # окружение + зависимости
./start.command           # ядро: сайт http://localhost:8765/ + Telegram
```

Остановить ядро — `Ctrl+C` в этом окне или откуда угодно:
`./start.command --stop`.

---

## Что делает каждый скрипт

| Скрипт | Что делает | Предпосылки |
|---|---|---|
| `Install-Mac.command` | окружение + зависимости + `.app` в `~/Applications` + (по желанию) автозапуск | Python 3.10+, права на запись в папку проекта |
| `install.command` | только окружение и зависимости, без `.app` (то же, что шаг 1 варианта 1) | Python 3.10+ |
| `start.command` | ядро: API, сайт на 8765, Telegram-бот, планировщик; сам перезапускается при падении | `.venv`, свободный порт |
| `start.command --stop` | остановить ядро, запущенное где угодно (иконка в меню, автозапуск, другое окно) | — |
| `update.command` | обновить зависимости после скачивания новой версии архива | `.venv` |
| `autostart.command` | LaunchAgent: ядро поднимается при входе в macOS | `.venv` |
| `autostart.command --remove` | снять автозапуск | — |
| `phone.command` | адреса для телефона (Wi-Fi и Tailscale) + подсказки по брандмауэру | ядро запущено |
| `voice.command` / `install_voice.command` | микрофон, wake word, озвучка (~700 МБ + Silero ~2 ГБ) | Homebrew + `brew install portaudio` |
| `build_web.command` | пересобрать `web/site` (нужен Node.js) | Node.js |

У всех скриптов есть **`--check`** — ничего не ставит и не запускает, только
проверяет окружение и объясняет, что не так:

```bash
./Install-Mac.command --check
./start.command --check
./update.command --check
./phone.command --check
./autostart.command --check
```

Это первое, что стоит запустить, если что-то не работает. Вывод годится и для
жалобы: там видны версия Python, порт, наличие `config.yaml`, `web/site` и ffmpeg.

---

## Обновление

```bash
# распаковать новый архив ПОВЕРХ старого (data/ и config.yaml не трогать)
./update.command
./start.command
```

На mac обновление идёт из `requirements-mac.txt` — это **не** `requirements.txt`,
в котором лежит `torch`: у torch нет macOS-колёс для Intel, и на Intel Mac базовая
установка на нём падала бы.

---

## Типичные ошибки

| Симптом | Причина | Что делать |
|---|---|---|
| `The file … is not executable` / `Permission denied` | ZIP из GitHub не сохраняет бит запуска | `chmod +x *.command mac/*.sh` |
| `command not found` или `$'\r': command not found` | в файле CRLF вместо LF (бывает, если проект закоммитили с Windows при `core.autocrlf=true`) | `sed -i '' 's/\r$//' *.command mac/*.sh`; и добавить в репозиторий `.gitattributes` со строками `*.command text eol=lf` и `*.sh text eol=lf` |
| `cannot be opened because it is from an unidentified developer`, «файл повреждён» | карантин Gatekeeper на скачанном файле | `xattr -dr com.apple.quarantine .` или ПКМ по файлу → «Открыть» ещё раз. Если не помогло: **Системные настройки → Конфиденциальность и безопасность → «Всё равно открыть»** |
| `Python 3.10+ не найден` | `python3` из Command Line Tools — это 3.9 | `brew install python@3.12` (Homebrew: https://brew.sh), затем скрипт снова |
| `ensurepip is not available` | Python без venv-модуля (бывает у минимальных сборок) | поставить Python через pkg-установщик с python.org или `brew install python@3.12` |
| `Порт 8765 уже занят` | ядро уже запущено — вторым окном или из автозагрузки | `./start.command --stop`, либо закройте иконку в строке меню. Список слушающих: `lsof -nP -iTCP:8765 -sTCP:LISTEN` |
| Нет страницы / «web/site не найдена» | сайт не собран (или архив распакован не полностью) | `npm ci && npm run build` в `web/` (нужен Node) либо `./build_web.command` |
| macOS просит доступ к «Микрофону» | системный запрос при первом `install_voice.command` / `voice.command` | разрешить: **Системные настройки → Конфиденциальность → Микрофон** |
| Сайт не открывается с телефона в той же Wi-Fi | брандмауэр macOS | **Системные настройки → Сеть → Брандмауэр → Параметры** → разрешить входящие для Терминала/Python. Подробнее — `./phone.command` |
| `ffmpeg не найден в PATH` | на mac его ставят через brew | `brew install ffmpeg` (или `/opt/homebrew/bin/brew install ffmpeg`, если brew не в PATH) |
| `brew: command not found` | на Apple Silicon brew лежит в `/opt/homebrew/bin`, которого нет в PATH у скриптов из Finder | полный путь: `/opt/homebrew/bin/brew install ffmpeg`, либо `eval "$(/opt/homebrew/bin/brew shellenv)"` |
| Значок в строке меню не появился | не встал `pystray` | `.venv/bin/python -m pip install pystray pillow` и запустить приложение снова |
| Автозапуск включён, но при входе ядро не поднялось | смотрите логи автозапуска | `cat data/autostart.err` — чаще всего нет папки `data/` или не запускаемый `start.command` (`./autostart.command --check`) |

**Где смотреть, если не помогло:** `data/core.log` — ядро, `data/host.log` —
приложение в строке меню, `data/autostart.log` и `data/autostart.err` — автозапуск.
Ключи и токены в логах маскируются, но перед публикацией лога всё равно
пробегитесь глазами.

---

## Что проверено, а что — нет

* **Проверено статически и в CI:** синтаксис всех `.command`/`mac/*.sh`
  (`bash -n`), наличие shebang, отсутствие CRLF и виндовых команд, единый
  стиль строгого режима, полнота `requirements-mac.txt`, работа
  `funnel_setup.py --check`, и — главное — **реальная установка из
  `mac/install.sh` на раннере `macos-latest`** с последующим прогоном
  тестов. См. `.github/workflows/tests.yml`, задание `macos`.
* **Проверяется только на живом Mac:** двойной клик в Finder и реакция
  Гейткипера, появление значка в строке меню, автозапуск при реальном входе
  в систему, работа `pystray` под Wayland-подобными ограничениями старых
  macOS, поведение брандмауэра для входящих подключений. Скрипты для этого
  готовы (`--check`, внятные сообщения), но «зелёный» CI этого не заменяет.

---

## Голос (необязательно)

```bash
./install_voice.command   # спросит про Silero (~2 ГБ) — можно отказаться
./voice.command           # запуск голосового клиента (ядро уже должно работать)
```

На mac дополнительно нужен PortAudio: `brew install portaudio`
(`install_voice.command` предложит поставить сам, если Homebrew есть).
macOS спросит разрешение на микрофон — разрешите.

---

## Сайт внутри Telegram (необязательно)

Нужен [Tailscale](https://tailscale.com/download/mac), установленный **и**
авторизованный на Mac (значок в строке меню → Log in).

```bash
.venv/bin/python funnel_setup.py --check   # только проверить, ничего не меняя
.venv/bin/python funnel_setup.py           # включить Funnel и записать адрес
.venv/bin/python funnel_setup.py off       # выключить
```

Подробности про безопасность и то, почему публичный адрес сам по себе не даёт
доступа к данным: [telegram-miniapp.md](telegram-miniapp.md).