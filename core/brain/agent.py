"""Мозг ассистента.

Порядок обработки любой фразы:
 1. Быстрые правила (мгновенно, без LLM, 100% приватно): траты, доходы, встречи, задачи, заметки, ссылки, отчёты.
 2. Локальная LLM (Ollama) с инструментами — для всего, что правила не поняли.
 3. Облако (Groq / OpenRouter / … — что выбрано в настройках) — разговор и общие вопросы, без личных данных, через анонимайзер.
 4. Честный ответ «не понял», если ничего не доступно.
"""
from __future__ import annotations

import logging
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import ChatMessage, get_setting, session, set_setting
from .. import identity
from ..services import brain_notes, calendar, finance, judge, memory, tasks, trace, undo, screen
from ..services.calendar import fmt_dt, fmt_due, fmt_repeat
from ..services.finance import money
from ..tools import registry
from ..services import bulk, insights, pc
from . import llm, quick, sorter
from .dates import ambiguous_night_hour, first_occurrence, parse_amount, parse_datetime, parse_datetime_ex, parse_repeat, task_due
from . import persona
from .persona import localize, now_line, say, system_prompt

log = logging.getLogger("assistant.agent")


@dataclass
class Reply:
    text: str
    actions: list[str] = field(default_factory=list)   # что было сделано (для UI/лога)
    via: str = "rules"                                  # rules / ollama / gemini(=облако) / none


# --------------------------------------------------------------------------- правила
EXPENSE_RX = re.compile(r"^\s*(потратил\w*|трата|расход|купил\w*|оплатил\w*|заплатил\w*|отдал\w*|внёс|внес|списали|минус|[-−])\s*", re.I)
INCOME_RX = re.compile(r"^\s*(получил\w*|доход|пришл[оа]|зарплата|зп|аванс|заработал\w*|плюс|\+)\s*", re.I)
EVENT_RX = re.compile(r"^\s*(встреча|созвон|звонок|запиши\s+встречу|запланируй|добавь\s+(?:в\s+)?календар\w*|событие|напомни(?:\s+мне)?|у меня)\s*", re.I)
TASK_RX = re.compile(r"^\s*(задача|таск|надо\s+бы|надо|нужно|не забыть|не забудь|сделать|добавь\s+задачу|todo|напомни\s+мне\s+что\s+надо)\s*[:\-—]?\s*", re.I)
NOTE_RX = re.compile(r"^\s*(мозг|в\s+мозг|мысль|заметка|запиши(?:\s+мысль)?|идея|запомни|сохрани)(?![а-яё])\s*[:\-—,]?\s*", re.I)
DONE_RX = re.compile(r"^\s*(сделал\w*|готово|выполнил\w*|закрой\s+задачу|done)\s*[:\-—]?\s*", re.I)
DEBT_RX = re.compile(r"^\s*(долг|кредит|должен|должна|взял\s+в\s+долг)\s*", re.I)
BALANCE_RX = re.compile(r"^\s*(баланс|на\s+счет[еу]|на\s+счёте)\s+(.+?)\s+(\d[\d\s.,]*\s*(?:к|тыс\w*)?)\s*$", re.I)
UNDO_RX = re.compile(r"^\s*(отмени(?:ть)?(?:\s+последн\w*)?|удали\s+последн\w*|отмена|отбой|не то,?\s*удали|не то|удали это|убери это|undo)\s*[.!]?\s*$", re.I)
MOVE_RX = re.compile(r"^\s*(перенеси|передвинь|сдвинь|перенести)\s+(.+?)\s+(?:на|в|к)\s+(.+)$", re.I | re.S)
RENAME_RX = re.compile(r"^\s*(переименуй|назови)\s+(.+?)\s+(?:в|на|как)\s+[«\"']?(.+?)[»\"']?\s*$", re.I | re.S)
DELETE_RX = re.compile(r"^\s*(удали|убери|отмени|снеси|сотри)\s+(задачу|событие|встречу|напоминание|заметку|мысль|ссылку)?\s*(?:про|о|об|с|на)?\s*(.+)$", re.I | re.S)
SKIP_RX = re.compile(r"^\s*(сегодня|завтра)\s+(.+?)\s+не\s+будет\s*[.!]?\s*$", re.I)
# дело без времени: «надо починить полку», «починить полку», «купить молоко», «позвонить маме»
ACTION_VERB_RX = re.compile(r"^\s*(?:надо|нужно|не забыть|надо бы|стоит|пора)?\s*(?:бы\s+)?"
                            r"(почини\w*|сдела\w*|сда\w*|отда\w*|куп\w*|позвон\w*|написа\w*|отправ\w*|забра\w*|отвез\w*|отнес\w*|оплат\w*|заплат\w*|продл\w*|"
                            r"записа\w*|заказ\w*|верн\w*|провер\w*|почист\w*|убра\w*|помы\w*|постира\w*|погла\w*|собра\w*|разобра\w*|"
                            r"дозвон\w*|договор\w*|найти|найд\w*|выбра\w*|скача\w*|установ\w*|обнов\w*|подготов\w*|доделать|доделаю|закончи\w*|"
                            r"сходи\w*|съезди\w*|зайти|зайд\w*|встрети\w*|подстри\w*|поменя\w*|замени\w*|распечата\w*|прочита\w*|посмотре\w*|"
                            r"выкин\w*|вынес\w*|полить|полей|покорм\w*|забронир\w*|перевест\w*|перезвон\w*|уточн\w*|спрос\w*|узна\w*|"
                            r"придума\w*|нарисова\w*|смонтир\w*|отснять|снять|выложи\w*|опубликова\w*|ответи\w*)\b", re.I)
# «событийные» существительные: если рядом есть время — это точно календарь
EVENT_NOUN_RX = re.compile(r"\b(встреч\w*|созвон\w*|звонок|звонк\w*|тренировк\w*|врач\w*|стоматолог\w*|зубн\w*|ужин\w*|обед\w*|завтрак\w*|"
                           r"свидани\w*|кино|концерт\w*|собеседовани\w*|экзамен\w*|лекци\w*|пар[аы]|занят\w*|урок\w*|репетиц\w*|съёмк\w*|съемк\w*|"
                           r"стрижк\w*|барбер\w*|маникюр\w*|массаж\w*|баня|бассейн\w*|зал|качалк\w*|самол[её]т\w*|поезд\w*|рейс\w*|вылет\w*|"
                           r"день рождени\w*|др\b|днюх\w*|праздник\w*|вечеринк\w*|дедлайн\w*|сдач[аиеу]\s+(?:проект|работ|отч[её]т|заказ|объект|экзамен|зач[её]т|ролик|монтаж)\w*|презентаци\w*|защит\w*|консультаци\w*|"
                           r"доставк\w*|курьер\w*|мастер\w*|сантехник\w*|электрик\w*|уборк\w*|игра|матч\w*|стрим\w*|эфир\w*|запись|напомни\w*)", re.I)
# прошедшее время («была», «сходила», «сказали») и показания здоровья — сигнал «это факт для памяти, не план»
PAST_RX = re.compile(r"\b(вчера|позавчера|только\s+что|был[аио]?|ходил[аи]?|сходил[аи]?|съездил[аи]?|принял[аи]?|выпил[аи]?|сдал[аи]?|получил[аи]?|"
                     r"сказал[аи]?|поставил[аи]?|измерил[аи]?|померил[аи]?|позвонил[аи]?|звонил[аи]?|заказал[аи]?|отдал[аи]?|забрал[аи]?|"
                     r"пришл[аио]|приехал[аи]?|узнал[аи]?|нашл[аи]|видел[аи]?|встретил[аи]?|поговорил[аи]?|договорил[аи]сь|закончил[аи]?|обещал[аи]?)\b", re.I)
HEALTH_RX = re.compile(r"\b(давлени\w*|температур\w*|сахар\b|пульс\w*|вес\s+\d|самочувстви\w*|болит|болел[аи]?|таблетк\w*|укол\w*|капл[иь])\b", re.I)
CLARIFY_RX = re.compile(r"^\s*(в\s+)?(задач\w*|дел[оа]|календар\w*|событи\w*|напомина\w*|заметк\w*|мысл\w*|мозг|нет|отмена|не надо|забудь|ничего)\s*[.!]?\s*$", re.I)

# ожидающие уточнения: channel -> (исходный текст, время)
PENDING_TTL_SEC = 300


def _pending_set(channel: str, text: str) -> None:
    set_setting(f"pending:{channel}", f"{datetime.now().isoformat()}|{text}")


def _pending_get(channel: str) -> tuple[str, datetime] | None:
    raw = get_setting(f"pending:{channel}")
    if not raw or "|" not in raw:
        return None
    ts, text = raw.split("|", 1)
    try:
        return text, datetime.fromisoformat(ts)
    except ValueError:
        return None


def _pending_clear(channel: str) -> None:
    set_setting(f"pending:{channel}", "")

CLOUD_RX = re.compile(r"^\s*(?:спроси\s+(?:у\s+)?)?(гемини|gemini|облако|джемини|дипсик|deepseek|грок|groq|нейронк\w*|интернет)\s*[,:\-—]?\s*", re.I)
LOCAL_RX = re.compile(r"^\s*(?:локально|" + identity.NAME_RX_SRC + r"\s+сам|сам|без\s+облака)\s*[,:\-—]?\s*", re.I)

# Всё, что пахнет личными данными или действием с ними, — только локальная модель.
PERSONAL_RX = re.compile(
    r"\b(запиши|запомни|добавь|сохрани|создай|поставь|напомни|удали|убери|отмени|перенеси|переименуй|покажи|найди|открой|"
    r"сотри|сотр[её]ть|стереть|стирай|очисти|очистить|почисти|снеси|грохни|обнули|вычисти|истори\w*|переписк\w*|чат\w*|операци\w*|"
    r"сделай|закрой|выполни|отметь|посчитай|сколько\s+(?:у\s+меня|я|мне|осталось|потратил|заработал)|"
    r"мо[йяие]\s+(?:задач|дел|встреч|план|календар|долг|баланс|счет|счёт|трат|расход|доход|заметк|мысл|ссылк|файл|бюджет|деньг|зарплат)|"
    r"задач\w*|(?<!как\s)(?<!как\sтвои\s)(?<!как\sу\sтебя\s)(?<!тебе\s)(?<!твои\s)(?<!у\sтебя\s)дел[аоы]?\b|встреч\w*|созвон\w*|календар\w*|событи\w*|напомина\w*|дедлайн\w*|"
    r"потрат\w*|трат\w*|расход\w*|доход\w*|зарплат\w*|аванс\w*|баланс\w*|сч[её]т\w*|долг\w*|кредит\w*|платеж\w*|платёж\w*|бюджет\w*|деньг\w*|денег|рубл\w*|₽|"
    r"заметк\w*|мысл\w*|идея|идеи|ссылк\w*|мозг|память|памяти|файл\w*|папк\w*|документ\w*|финанс\w*|"
    r"заказ\w*|клиент\w*|аванс\w*|оплат\w*|помодоро|таймер\w*|дедлайн\w*|цел[ьи]\b|копилк\w*|подушк\w*|"
    r"сегодня|завтра|послезавтра|вчера|на\s+неделе|на\s+этой\s+неделе|в\s+понедельник|во\s+вторник|в\s+среду|в\s+четверг|в\s+пятницу|в\s+субботу|в\s+воскресенье|"
    r"что\s+у\s+меня|что\s+мне\s+(?:надо|нужно)|план\w*\s+на|бриф\w*|дайджест|сводк\w*|отч[её]т\w*|"
    r"что\s+(?:я|мы)\s+(?:записыва|говорил|планирова|должен|должны)\w*|куда\s+(?:я|мы)\s+(?:ид|ед|соб)\w*|"
    r"когда\s+(?:у\s+меня|я|мне|мы)\b|во\s+сколько\s+(?:у\s+меня|я|мне|мы)\b|где\s+(?:у\s+меня|мо[йяё]|лежит|лежат|я|мы)\b|"
    r"сколько\s+(?:денег|осталось|должен|должны|мне\s+должны|я\s+должен|нужно\s+отдать|отдать)|"
    r"на\s+что\s+(?:я|мы)\s+(?:трат|потрат)\w*|компьютер|комп\b|рабоч\w+\s+стол|скачанн\w*|загрузк\w*|ярлык|открой|запусти|включи|выключи)\b", re.I)


SMALLTALK_RX = re.compile(r"^\s*(привет|здравствуй\w*|добр\w+\s+(?:утро|день|вечер|ночи)|хай|йо|ку|салют|как\s+(?:дела|ты|жизнь|настроение|сам)|"
                          r"(?:как\s+)?(?:тебе|твои|у\s+тебя)\s+дела|"   # Whisper часто слышит «как дела» как «тебе дела»
                          r"что\s+(?:нового|делаешь|умеешь)|спасибо|благодарю|пока|споки|спокойной\s+ночи|ты\s+кто|кто\s+ты|расскажи\s+о\s+себе)\b[^\n]{0,40}$", re.I)


OPINION_RX = re.compile(r"(?:как\s+(?:ты\s+)?(?:думаешь|считаешь|по-твоему)|что\s+(?:посоветуешь|скажешь|выбрать|взять|лучше|бы\s+ты)|посоветуй|"
                        r"твоё\s+мнение|твое\s+мнение|стоит\s+ли|\b[а-яё]+ть\s+ли\b|как\s+тебе\s+иде\w+|что\s+думаешь|"
                        r"(?:а\s+)?что\s+если\s+(?:я|мы|мне)\b|(?:а\s+)?если\s+(?:я|мы)\s+(?:возьм|куп|продам|уйд|брос|начн|поед|перейд)\w*)", re.I)


def is_personal(text: str) -> bool:
    """Нужны ли для ответа личные данные / действие в базе. Если нет — это разговор, его ведёт облако."""
    if SMALLTALK_RX.match(text):
        return False
    # «как думаешь, что взять на завтрак… через 10 минут…» — просьба о мнении, а не команда: цифры внутри не делают её личной.
    # Если облако решит, что без базы не ответить, оно вернёт local_needed и вопрос уйдёт локальной модели — это уже есть.
    if OPINION_RX.search(text) and not re.search(r"\b(запиши|запомни|добавь|напомни|поставь|удали|отмени|перенеси)\b", text, re.I):
        return False
    # «хлеб, молоко, яйца» — список покупок без глаголов: это дело, а не тема для беседы
    if re.fullmatch(r"\s*[а-яёa-z0-9 \-]{2,25}(?:\s*,\s*[а-яёa-z0-9 \-]{2,25}){2,}\s*\.?", text, re.I):
        return True
    # «сколько будет 15% от 3400», «переведи 100 долларов в рубли» — арифметика, не база
    if re.match(r"^\s*(сколько\s+будет|посчитай\s+\d|переведи\s+\d|\d[\d\s.,]*\s*[+\-*/×÷]\s*\d)", text, re.I):
        return False
    # число из 2+ цифр — почти всегда сумма/время/дата; слитное «128рублей» тоже (между «8» и «р» нет \b, поэтому не \b)
    return bool(PERSONAL_RX.search(text)) or bool(re.search(r"\d{1,2}[:.]\d{2}|(?<!\d)\d{2,}(?!\d)", text))


def _days_word(n: int) -> str:
    a, b = n % 100, n % 10
    return "дней" if 10 < a < 20 else "день" if b == 1 else "дня" if 1 < b < 5 else "дней"


def _core_status_text() -> str:
    """«Статус костюма», когда ПК-клиент не на связи: хотя бы состояние ядра."""
    import shutil
    from ..config import DATA_DIR
    parts = []
    try:
        u = shutil.disk_usage(DATA_DIR)
        parts.append(f"на диске свободно {u.free / 2**30:.0f} ГБ")
    except Exception:
        pass
    if llm.SMALL_MODEL:
        parts.append(f"малая модель {llm.SMALL_MODEL} " + ("на месте" if llm.small_model_active() else "НЕ скачана — мини-задачи на основной"))
    parts.append("локальный мозг " + ("спит (игровой режим)" if llm.GAME_MODE else llm.OLLAMA_MODEL))
    if llm.GPU_NOTE:
        parts.append(llm.GPU_NOTE.split(":")[-1].strip())
    parts.append(f"облако {llm.cloud_title()}" if llm.cloud_enabled() else "облако выключено")
    return "Ядро в норме, сэр: " + ", ".join(parts) + ". Датчики ПК подключатся, когда запустите voice.bat."


def _past_date(rest: str) -> tuple[datetime | None, str]:
    """«… вчера» / «… позавчера» / «… 5 сентября» в трате → дата операции (только прошлое) и текст без неё."""
    if not re.search(r"\b(вчера|позавчера|\d{1,2}\s+(?:янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек)|\d{1,2}[./]\d{1,2})", rest.lower()):
        return None, rest
    dt, rest2 = parse_datetime(rest)
    if dt and dt.date() < datetime.now().date():
        return dt.replace(hour=12, minute=0), rest2
    return None, rest


def _strip_fillers(t: str) -> str:
    t = re.sub(r"^\s*(на|за|в|для|по)\s+", "", t.strip(), flags=re.I)
    return t.strip(" ,.-—:")


_Q = r"^\s*(?:а\s+)?(?:что|чё|че|как|какие|каков\w*)\s+(?:там\s+)?(?:у\s+меня\s+)?"
FIN_REPORT_RX = re.compile(_Q + r"(?:по\s+|с\s+|со\s+)?(?:мои\w*\s+)?(?:финанс\w*|деньг\w*|денежк\w*|баланс\w*|бюджет\w*|кошельк\w*|бабк\w*|касс\w*)\W*$", re.I)
TASK_REPORT_RX = re.compile(_Q + r"(?:по\s+|с\s+|со\s+)?(?:мои\w*\s+)?(?:задач\w*|делам|дела)\W*$", re.I)
EVENT_REPORT_RX = re.compile(_Q + r"(?:по\s+|с\s+|со\s+)?(?:мои\w*\s+)?(?:встреч\w*|календар\w*|событи\w*|планам)\W*$", re.I)
# претензия к ответу: «сверься», «откуда ты это взял», «у меня другие данные», «ты выдумал» → не заметка, а перепроверка
RECHECK_RX = re.compile(r"^\s*(?:откуда\s+(?:ты\s+)?(?:это\s+)?(?:взял|взяла|берёшь|берешь)|сверься|свериться|перепроверь|проверь\s+(?:ещё|еще|данные|базу|цифры)|"
                        r"(?:это|у\s+меня)\s+(?:же\s+)?(?:там\s+)?(?:другие|не\s+те|неверные|неправильные)\s+(?:данные|цифры|значения|суммы)|"
                        r"ты\s+(?:это\s+)?(?:выдумал|придумал|сочинил|ошибся|врёшь|врешь|наврал)|не\s+сходится|неправильно\s+посчитал)", re.I)
# вопрос/претензия к ассистенту — никогда не заметка
_QUESTION_RX = re.compile(r"^(что|как|почему|зачем|когда|где|кто|куда|откуда|сколько|какой|какая|какие|каков\w*|можешь|расскажи|объясни|посоветуй|"
                          r"разве|неужели|серьёзно|серьезно|правда|ты\s+(?:уверен|точно|серьёзно|серьезно|что|это|же|сам|вообще|опять|снова)|сверься|перепроверь|проверь|исправь|"
                          r"не\s+так|неправильно|ошиб\w*|у\s+меня\s+(?:же\s+)?(?:там\s+)?друг\w*)\b", re.I)


ANALYZE_RX = re.compile(r"\b(разбери|разберись|проанализируй|анализируй|посчитай|прикинь|оцени|подскажи|посоветуй|подумай|помоги\s+разобраться|"
                        r"не\s+записывай|не\s+сохраняй|без\s+записи|просто\s+(?:скажи|ответь|посчитай)|хватит\s+ли|потяну\s+ли|стоит\s+ли)\b", re.I)


def _is_analysis(text: str) -> bool:
    """«разбери ситуацию», «посчитай, хватит ли», «не записывай» — человек хочет анализа, а не записи в базу."""
    return bool(ANALYZE_RX.search(text))


def _too_long_for_rules(text: str) -> bool:
    """Длинный текст или несколько сумм — это рассказ/анализ, шаблоны для коротких команд тут только навредят."""
    words = len(text.split())
    amounts = len(re.findall(r"\b\d{3,}(?:[.,]\d+)?\b|\b\d+\s*(?:к|k|тыс)\b", text, re.I))
    return words > 14 or (amounts >= 2 and words > 8)


MEM_REMEMBER_RX = re.compile(r"^\s*запомни\s*[,:—-]?\s*(?:что\s+)?(.+)$", re.I | re.S)
MEM_FORGET_RX = re.compile(r"^\s*забудь\s*[,:—-]?\s*(?:что\s+|про\s+|о\s+том,?\s+что\s+)?(.+)$", re.I | re.S)
MEM_ABOUT_RX = re.compile(r"^\s*(что\s+ты\s+(?:обо?\s+мне\s+)?(?:знаешь|помнишь)(?:\s+обо?\s+мне)?|что\s+ты\s+помнишь|расскажи,?\s+что\s+(?:ты\s+)?знаешь\s+обо?\s+мне|покажи\s+память|моя\s+память|портрет)\W*$", re.I)
# «запомни: у меня кот Барсик» — факт о человеке (в память); «запомни: идея для ролика…» — мысль (в Мозг, как раньше)
_ME_RX = re.compile(r"\b(я|у\s+меня|мне|мой|моя|мои|моё|мою|меня|люблю|не\s+люблю|предпочитаю|терпеть\s+не\s+могу|обычно|всегда|никогда|аллерги|зовут|живу|работаю)\b", re.I)


def _memory_rules(t: str, channel: str) -> Reply | None:
    if not memory.enabled():
        return None
    if MEM_ABOUT_RX.match(t):
        return Reply(memory.about_me_text(), ["about_me"])
    m = MEM_FORGET_RX.match(t)
    if m and len(t.split()) <= 20:
        what = m.group(1).strip(" .!")
        f = memory.find_fact(what)
        if f:
            memory.forget(f.id)
            return Reply(f"Забыл: «{f.text}». Лежит в архиве памяти — если что, верну.", ["forget_fact"])
        return Reply(f"Такого я и не помнил, сэр: «{what}». Проверьте страницу «память».", [])
    m = MEM_REMEMBER_RX.match(t)
    if m and _ME_RX.search(m.group(1)) and len(t.split()) <= 40 and not _looks_like_question(t):
        body = m.group(1).strip(" .!")
        f = memory.add_fact_sync(body, layer="long", confidence=0.95)   # вектор досчитает планировщик
        if f:
            return Reply(f"Запомнил: «{f.text}». Это теперь часть того, что я о вас знаю.", ["add_fact"])
    return None


# «это задача» / «это была трата» / «не трата, а заказ» — исправление последней записи: откат + перезапись нужным типом + урок
FIX_RX = re.compile(r"^\s*(?:нет,?\s*|не\s+то,?\s*)?(?:это\s+(?:был[аои]?\s+)?|не\s+\w+,?\s+а\s+|запиши\s+(?:это\s+)?как\s+|надо\s+было\s+как\s+|это\s+не\s+\w+,?\s+(?:а\s+)?)"
                    r"(?:в\s+)?(трата|тратой|трату|расход|расходом|доход|доходом|долг|долгом|заказ|заказом|проект|проектом|задача|задачей|задачу|дело|делом|"
                    r"событие|событием|встреча|встречей|встречу|календарь|в\s+календарь|заметка|заметкой|заметку|мысль|мыслью|мозг|в\s+мозг|память|в\s+память)\s*[.!]*\s*$", re.I)
_FIX_KIND = (("трат", "expense"), ("расход", "expense"), ("доход", "income"), ("долг", "debt"), ("заказ", "order"), ("проект", "order"),
             ("задач", "task"), ("дел", "task"), ("событи", "event"), ("встреч", "event"), ("календар", "event"),
             ("заметк", "note"), ("мысл", "note"), ("мозг", "note"), ("памят", "note"))
_ACTION_KIND = {"add_expense": "expense", "add_income": "income", "add_debt": "debt", "add_order": "order", "add_task": "task",
                "add_event": "event", "add_note": "note"}


def _fix_kind(word: str) -> str | None:
    w = word.lower()
    for pref, k in _FIX_KIND:
        if w.startswith(pref):
            return k
    return None


def _last_user_text(channel: str) -> str | None:
    """Предыдущая реплика хозяина (не текущая) — исходник для перезаписи другим типом."""
    with session() as s:
        rows = s.exec(select(ChatMessage).where(ChatMessage.role == "user").order_by(ChatMessage.id.desc()).limit(2)).all()
    return rows[1].text if len(rows) > 1 else None


def _write_as(kind: str, text: str, channel: str) -> Reply | None:
    """Записать фразу заданным типом (после судьи, урока или исправления). None — не смог разобрать (нет суммы и т.п.)."""
    t = text.strip()
    if kind in ("expense", "income"):
        amount, rest = parse_amount(re.sub(r"^\s*(потратил\w*|получил\w*|отдал\w*|заплатил\w*|пришл[оа])\s*", "", t, flags=re.I))
        if amount is None:
            return None
        when, rest = _past_date(rest)
        note = _strip_fillers(rest) or None
        tx = finance.add_transaction(amount, kind, None, note, source=channel, date=when)
        sm = finance.summary(1)
        return Reply(say(kind, amount=money(tx.amount), category=tx.category, balance=money(sm["total_balance"])), [f"add_{kind}"])
    if kind == "debt":
        amount, rest = parse_amount(t)
        if amount is None:
            return None
        title = _strip_fillers(re.sub(r"^\s*(долг|должен|должна|отдал\w*|дал\w*|занял\w*|взял\w*)\s*", "", rest, flags=re.I)) or "Долг"
        d = finance.add_debt(title[0].upper() + title[1:], amount)
        return Reply(f"Долг «{d.title}» на {money(d.remaining)} записан.", ["add_debt"])
    if kind == "order":
        from ..services import orders
        client = None
        mc = re.search(r"(?:^|\s)(?:для|от|клиент[:\s])\s*([А-ЯЁA-Z][\w\-]*(?:\s+[А-ЯЁA-Z][\w\-]*)?)", t)
        body = t
        if mc:
            client = mc.group(1); body = (t[:mc.start()] + " " + t[mc.end():]).strip()
        amount, rest = parse_amount(re.sub(r"^\s*(заказ|проект|новый\s+заказ)\s*[:\-—]?\s*", "", body, flags=re.I))
        dt, rest = parse_datetime(rest)
        title = re.sub(r"\s{2,}", " ", rest).strip(" ,.-—:;")
        if not title:
            return None
        o = orders.add_order(title[0].upper() + title[1:], amount or 0, client, dt, source=channel)
        return Reply(f"Заказ #{o.id} «{o.title}»" + (f" · {money(o.price)}" if o.price else " · сумму уточним") + ". В работе.", ["add_order"])
    if kind == "task":
        due, body, time_set = parse_datetime_ex(t)
        due = task_due(due, time_set)
        body = re.sub(r"^\s*(задача|надо\s+бы|надо|нужно|не\s+забыть)\s*[:\-—]?\s*", "", body, flags=re.I).strip() or t
        tk = tasks.add_task(body[0].upper() + body[1:], due, source=channel)
        return Reply(say("task", title=tk.title) + fmt_due(due), ["add_task"])
    if kind == "event":
        dt, rest = parse_datetime(t)
        if not dt:
            return None
        title = _strip_fillers(re.sub(r"^\s*(встреча|событие|у\s+меня|напомни(?:\s+мне)?)\s*[:\-—]?\s*", "", rest, flags=re.I)) or "Событие"
        ev = calendar.add_event(title[0].upper() + title[1:], dt, remind_minutes=30, source=channel)
        return Reply(say("event", title=ev.title, when=fmt_dt(ev.start)), ["add_event"])
    if kind == "note":
        brain_notes.add_note(re.sub(r"^\s*(мозг|мысль|заметка|запомни)\s*[:\-—,]?\s*", "", t, flags=re.I) or t, source=channel)
        return Reply(say("note"), ["add_note"])
    return None


def _fix_rule(t: str, channel: str) -> Reply | None:
    """«это задача» после неверной записи: откатить последнее, записать исходную фразу нужным типом, запомнить урок."""
    m = FIX_RX.match(t)
    if not m:
        return None
    kind = _fix_kind(m.group(1))
    if not kind:
        return None
    a = undo.last_action(channel, max_age_min=30)
    orig = _last_user_text(channel)
    if not a or not orig or a.kind not in _ACTION_KIND:
        return Reply("Исправлять нечего, сэр: за последние полчаса я ничего не записывал. Скажите фразу заново — запишу как " + judge.KIND_RU[kind] + ".", [])
    wrong = _ACTION_KIND[a.kind]
    if wrong == kind:
        return Reply(f"Так и записано — {judge.KIND_RU[kind]}: «{a.title}».", [])
    try:
        r = _write_as(kind, orig, channel)
    except (finance.FinanceError, ValueError) as e:
        log.warning("fix as %s failed: %s", kind, e)
        r = None
    if r is None:
        return Reply(f"Понял, что это {judge.KIND_RU[kind]}, но из «{orig[:60]}» не собрал запись" + (" — нет суммы." if kind in ("expense", "income", "debt") else " — нет даты." if kind == "event" else ".") + " Скажите заново, сэр.", [])
    undo.undo_one(a)   # откатываем именно ту запись, а не только что созданную
    judge.add_lesson(orig, kind, wrong=wrong)
    r.text = f"Переложил: было «{judge.KIND_RU[wrong]}», теперь {judge.KIND_RU[kind]}. " + r.text + " Запомнил на будущее."
    r.actions = r.actions + ["fix", "lesson"]
    return r


def _resolve_judge(text: str, channel: str) -> Reply | None:
    """Ответ на вопрос судьи («трата, заказ или доход?»)."""
    p = _pending_get(channel)
    if not p or not p[0].startswith("judge|"):
        return None
    orig, ts = p
    if (datetime.now() - ts).total_seconds() > PENDING_TTL_SEC:
        _pending_clear(channel)
        return None
    orig = orig[6:]
    m = re.match(r"^\s*(?:это\s+)?(трата|расход|доход|долг|заказ|проект|задача|дело|событие|встреча|календарь|заметка|мысль|мозг)\s*[.!]*\s*$", text, re.I)
    if NO_RX.match(text):
        _pending_clear(channel)
        return Reply("Ок, не записываю.", [])
    if not m:
        return None   # заговорили о другом — вопрос снимется по TTL
    kind = _fix_kind(m.group(1))
    _pending_clear(channel)
    try:
        r = _write_as(kind, orig, channel)
    except finance.FinanceError as e:
        return Reply(f"Не записал: {e}", [], "rules")
    if r is None:
        return Reply(f"Понял, {judge.KIND_RU[kind]}, но из «{orig[:60]}» не собрал запись. Скажите заново полностью, сэр.", [])
    judge.add_lesson(orig, kind)
    r.text += " Запомнил: в следующий раз такое не переспрошу."
    r.actions = r.actions + ["lesson"]
    return r


def _judge_question(orig: str, channel: str, options: tuple[str, ...]) -> Reply:
    _pending_set(channel, "judge|" + orig)
    names = [judge.KIND_RU[k].split()[0] for k in options]
    return Reply(f"«{orig}» — это " + ", ".join(names[:-1]) + f" или {names[-1]}? Ответьте одним словом, сэр.", ["clarify"])


# спорные фразы: где шаблон угадывает, а не знает. Судья зовётся ТОЛЬКО тут; явные команды идут как раньше
def _disputed(t: str) -> tuple[str, ...] | None:
    """Варианты для судьи, если фраза спорная; None — фраза однозначная (или слишком длинная), судья не нужен."""
    low = t.lower().strip()
    n = len(t.split())
    if n > 12 or _looks_like_question(t) or "\n" in t:
        return None
    amount, _rest = parse_amount(t)
    # «3 монтажа подряд», «12 марта», «2 раза» — число меньше 10 без «руб/к» или число, ушедшее в дату, — не сумма
    has_amount = amount is not None and (amount >= 10 or re.search(r"\d\s*(?:р\b|руб|₽|к\b|тыс)", low)) \
        and not (parse_datetime(t)[0] is not None and not re.search(r"\d", parse_datetime(t)[1]))
    # «сайт 15000», «логотип для Кати 8к», «пятёрочка 25к» — сумма + слово без глагола: трата, доход или заказ?
    if has_amount and n <= 6 and not EXPENSE_RX.match(t) and not INCOME_RX.match(t) and not DEBT_RX.match(t) and not re.search(r"[:.]\d{2}\b|\b(в|к|до|через)\s+\d", low):
        rest = parse_amount(t)[1]
        if rest.strip() and finance.guess_category(rest, "expense") in ("Другое", "Долги"):
            from ..services import pulse
            return ("expense", "income", "order") if pulse.enabled() else ("expense", "income", "debt")
    # «отдал Ване 2000», «дал маме 5к», «занял у Пети 3000» — трата или долг?
    if has_amount and re.match(r"^\s*(отдал\w*|дал\w*|занял\w*|одолжил\w*|скинул\w*|перевёл|перевел)\s+[А-ЯЁ]", t):
        return ("expense", "debt", "income")
    return None


# эмоциональный префикс перед командой: «ты еблан? запиши 510 доставка еды», «блин, запиши…», «слушай, добавь…» — команда начинается после него
_VENT_PREFIX_RX = re.compile(r"^\s*(?:(?:(?:ты|вы)\s+[а-яё]+\s*[?!.,]+|(?:блин|бля|блять|сука|чёрт|черт|капец|пиздец|слушай|короче|так|ну|окей|ок|ладно|ало|алло|эй)\s*[,!.:—-]*)\s*)+"
                             r"(?=(?:запиши|запомни|добавь|поставь|напомни|удали|отмени|перенеси|покажи|найди|потратил|купил|заплатил|задача|мысль|встреча)\b)", re.I)
# «запиши 510 доставка еды», «запиши трату 700 такси» — не заметка, а трата (сумма + категория), решает шаблон траты ниже
_NOTE_BUT_EXPENSE_RX = re.compile(r"^\s*(?:запиши|добавь|внеси)\s+(?:трату\s+|расход\s+)?(?=\d)", re.I)


def rules(text: str, channel: str) -> Reply | None:
    text = _VENT_PREFIX_RX.sub("", text, count=1) or text
    t = text.strip()
    low = t.lower()
    if FIN_TECH_RX.match(t):   # «хватит ли на платежи» — готовый отчёт, а не анализ моделью
        return _orders_rules(t, low, channel)
    if pc.TIDY_RX.match(t) or pc.TIDY_UNDO_RX.match(t):   # «разбери рабочий стол» — уборка на ПК, а не «разбери ситуацию»
        cmd = pc.parse(t)
        return Reply(pc.dispatch(cmd, channel), [f"pc_{cmd.action}"])
    r_fix = _resolve_judge(t, channel) or _fix_rule(t, channel)
    if r_fix:
        return r_fix
    mr = _memory_rules(t, channel)
    if mr:
        return mr
    if _is_analysis(t) or _too_long_for_rules(t):
        # только быстрые отчёты/откат/явные префиксы («мозг:», «задача:») — остальное решает модель
        m_note = NOTE_RX.match(t)
        if m_note and not _is_analysis(t):
            body = t[m_note.end():].strip()
            if body:
                brain_notes.add_note(body, source=channel)
                return Reply(say("note"), ["add_note"])
        if UNDO_RX.match(low):
            msg = sorter.undo_batch(channel) or undo.undo_last(channel)
            return Reply(msg or "Отменять нечего, сэр.", ["undo"] if msg else [])
        return _edit_note_rule(t, channel)

    # ---- ссылки: приоритет, если в сообщении есть URL ----
    urls = brain_notes.extract_urls(t)
    if urls:
        return None  # ссылки обрабатываются асинхронно в handle() — здесь только сигнал
    r_edit = _edit_note_rule(t, channel)
    if r_edit:
        return r_edit

    # ---- быстрые отчёты ----
    if low in ("что сегодня", "что у меня сегодня", "план на сегодня", "сегодня", "дайджест", "бриф", "брифинг"):
        return Reply(registry.today_briefing(), ["briefing"])
    if re.match(r"^(прогноз|прогноз (по )?(деньгам|кассы|финансов|бюджета)|хватит ли (мне )?(денег|до зарплаты)|до зарплаты хватит|сколько (могу|можно) тратить( в день)?|"
                r"сколько будет (на счете|на счёте|денег) через (месяц|30 дней)|что с деньгами (через месяц|к концу месяца)|дотяну до зарплаты)\??$", low):
        return Reply(insights.cash_forecast_text(), ["forecast"])
    if re.match(r"^(подписки|мои подписки|какие у меня подписки|на что я подписан|найди подписки|повторяющиеся списания)\??$", low):
        subs = insights.detect_subscriptions()
        rec = [r for r in finance.list_recurring() if r.kind == "expense" and not r.debt_id]
        lines = []
        if rec:
            lines.append("💳 **Регулярные**: " + "; ".join(f"{r.title} {money(r.amount)}" for r in rec[:8]))
        if subs:
            lines.append("🔁 **Похоже на подписки** (не в регулярных): " + "; ".join(f"{x['name']} {money(x['amount'])}/мес" for x in subs[:6]))
            lines.append(f"Итого «тихих» списаний ~**{money(sum(x['amount'] for x in subs))}** в месяц.")
        return Reply("\n".join(lines) or "Подписок не вижу, сэр. Либо вы аскет, либо платите наличными.", ["subscriptions"])
    if re.match(r"^(стрик|серия|сколько дней подряд|мой стрик|рекорд)\??$", low):
        st = insights.streak()
        return Reply(f"🔥 {st['current']} {_days_word(st['current'])} подряд ведёте записи (рекорд — {st['best']})." +
                     ("" if st["today_done"] else " Сегодня ещё ничего не записали — стрик под угрозой, сэр."), ["streak"])
    if re.match(r"^(подкинь монетку|монетка|орёл или решка|орел или решка|брось монетку|кинь монетку)\??$", low):
        import random
        return Reply(random.choice(["Орёл. Судьба высказалась, сэр.", "Решка. Не спорьте со случайностью.", "Орёл. Хотя вы ведь уже решили, пока она летела, верно?",
                                    "Решка. Если расстроились — значит, хотели орла. Делайте то, чего хотели."]), ["coin"])
    m = re.match(r"^(выбери за меня|выбери|реши за меня|что выбрать)\s*[:\-—]?\s*(.+?)\s*\??$", low)
    if m and re.search(r"\bили\b|,", m.group(2)):
        import random
        opts = [o.strip(" .!?") for o in re.split(r"\s+или\s+|,", m.group(2)) if o.strip(" .!?")]
        if len(opts) >= 2:
            return Reply(random.choice([f"«{random.choice(opts).capitalize()}». Не благодарите.", f"Однозначно «{random.choice(opts)}». Я бы поставил на это деньги. Ваши.",
                                        f"«{random.choice(opts)}» — и не оглядывайтесь."]), ["choose"])
    if re.match(r"^(протокол\s+)?[«\"]?чистый лист[»\"]?\s*[.!]?$", low):
        n = insights.archive_done_tasks(30)
        return Reply(f"Протокол «Чистый лист» выполнен: {n} выполненных задач старше месяца убраны в архив. Ничего не удалено — только с глаз долой, сэр." if n
                     else "Протокол «Чистый лист»: архивировать нечего — всё и так чисто. Подозрительно чисто.", ["clean_slate"])
    if re.match(r"^(я\s+)?железный человек\s*[.!]?$|^я\s+тони\s+старк", low):
        return Reply("Конечно, сэр. Костюм в ремонте, Пеппер не в курсе, а реактор — это ваш кофе. Но в остальном — один в один.", ["easter"])
    if re.match(r"^(" + identity.NAME_RX_SRC + r",?\s+)?ты\s+(жив|живой|тут|здесь|на связи|меня слышишь)\??$", low):
        return Reply("На связи, сэр. Всегда.", ["ping"])
    if re.match(r"^(статус\s+костюма|статус\s+" + identity.NAME_RX_SRC + r"|статус\s+систем)\s*[?.!]?$", low) and not pc.alive():
        return Reply(_core_status_text(), ["status"])
    if re.match(r"^(спокойной ночи|доброй ночи|я спать|пошёл спать|пошел спать|иду спать)\s*[.!]?$", low):
        evs = calendar.list_events(datetime.now().replace(hour=0, minute=0) + timedelta(days=1), datetime.now().replace(hour=0, minute=0) + timedelta(days=2))
        first = f" Завтра первое — «{evs[0].title}» в {evs[0].start:%H:%M}." if evs else " Завтра с утра пусто, можно выспаться."
        return Reply("Спокойной ночи, сэр." + first + " Ночной режим включён.", ["night"])

    # ---- управление ПК: открой / найди / пауза / что на экране / статус костюма ----
    cmd = pc.parse(t)
    if cmd:
        if cmd.action == "power" and cmd.arg in ("shutdown", "reboot"):
            # необратимое для несохранённой работы — только после «да» (тем же pending-механизмом, что и крупные суммы)
            _pending_set(channel, "confirm|" + json.dumps({"pc": cmd.arg}))
            return Reply(("Выключить компьютер" if cmd.arg == "shutdown" else "Перезагрузить компьютер") + "? Несохранённое пропадёт. Скажите «да» или «нет», сэр.", ["clarify"])
        return Reply(pc.dispatch(cmd, channel), [f"pc_{cmd.action}"])
    st = screen.chat_rule(t)   # «сколько сидел за компом», «на что ушёл день», «сколько ютуба сегодня»
    if st:
        return Reply(st, ["screen_time"])
    if low in ("задачи", "мои задачи", "список задач", "что надо сделать", "дела"):
        return Reply(registry.list_tasks(), ["list_tasks"])
    if low in ("календарь", "события", "встречи", "план на неделю", "что на неделе"):
        return Reply(registry.list_events(7), ["list_events"])
    if low in ("финансы", "баланс", "деньги", "сколько денег", "отчет", "отчёт", "сводка", "траты") or FIN_REPORT_RX.match(low):
        return Reply(registry.finance_summary(30), ["finance_summary"])
    if TASK_REPORT_RX.match(low) and not SMALLTALK_RX.match(low):   # «как дела» — приветствие, не «как там мои дела»
        return Reply(registry.list_tasks(), ["list_tasks"])
    if EVENT_REPORT_RX.match(low):
        return Reply(registry.list_events(7), ["list_events"])
    if RECHECK_RX.match(low):
        # «сверься», «откуда ты это взял», «у меня другие данные» — перечитать базу по теме последних сообщений
        topic = " ".join(h["text"] for h in _history(channel, 4)).lower()
        if re.search(r"задач|дел[аы]\b", topic) and not re.search(r"финанс|деньг|баланс|трат", topic):
            return Reply("Перечитал базу.\n" + registry.list_tasks(), ["list_tasks"])
        if re.search(r"встреч|календар|событи", topic) and not re.search(r"финанс|деньг|баланс|трат", topic):
            return Reply("Перечитал базу.\n" + registry.list_events(7), ["list_events"])
        return Reply("Перечитал базу — вот точные цифры.\n" + registry.finance_summary(30), ["finance_summary"])
    if low in ("долги", "мои долги", "кредиты"):
        return Reply(registry.list_debts(), ["list_debts"])
    r_o = _orders_rules(t, low, channel)
    if r_o:
        return r_o
    if UNDO_RX.match(low):
        msg = sorter.undo_batch(channel) or undo.undo_last(channel)
        return Reply(msg or "Отменять нечего, сэр.", ["undo"] if msg else [])

    # ---- быстрые справки и деньги без LLM: «сколько потратил на еду», «что завтра», «заплатил Ване 2000», «подписка …» ----
    q = quick.run(t, channel)
    if q:
        return Reply(q[0], q[1])

    # ---- правка из чата: перенести / переименовать / удалить / пропустить повтор ----
    r = _edit_rules(t, channel)
    if r:
        return r

    # ---- установить баланс ----
    m = BALANCE_RX.match(t)
    if m:
        amount, _ = parse_amount(m.group(3))
        if amount is not None:
            a = finance.set_balance(m.group(2).strip().title(), amount)
            return Reply(f"Баланс «{a.name}» — {money(a.balance)}. Сверено.", ["set_balance"])

    # ---- траты / доходы ----
    m = EXPENSE_RX.match(t)
    if m:
        amount, rest = parse_amount(t[m.end():])
        if amount is not None:
            when, rest = _past_date(rest)
            note = _strip_fillers(rest) or None
            tx = finance.add_transaction(amount, "expense", None, note, source=channel, date=when)
            s = finance.summary(1)
            txt = say("expense", amount=money(tx.amount), category=tx.category, balance=money(s["total_balance"]))
            if when:
                txt += f" (за {when:%d.%m})"
            return Reply(txt, ["add_expense"])
    m = INCOME_RX.match(t)
    if m:
        amount, rest = parse_amount(t[m.end():])
        if amount is not None:
            when, rest = _past_date(rest)
            note = _strip_fillers(rest) or m.group(1)
            tx = finance.add_transaction(amount, "income", None, note, source=channel, date=when)
            s = finance.summary(1)
            return Reply(say("income", amount=money(tx.amount), category=tx.category, balance=money(s["total_balance"])), ["add_income"])

    # ---- «700 такси», «кофе 350», «такси 700 вчера» — без глагола, но сумма + известная категория ----
    if len(t.split()) <= 5 and not _looks_like_question(t) and re.search(r"\d", t):
        amount, rest = parse_amount(t)
        words = [w for w in re.findall(r"[а-яё]+", rest.lower()) if w not in ("вчера", "позавчера", "сегодня", "на", "за", "в", "руб", "рублей")]
        # «обед 450», «врач 2500», «510 доставка еды» — слово одновременно событийное и категория трат; без времени и даты
        # («обед в 14», «врач завтра») это трата: у события всегда есть когда, у траты — сколько
        has_when = bool(re.search(r"[:.]\d{2}\b|\b(в|к|до|через|на)\s+\d|\b(завтра|послезавтра|сегодня\s+в|утром|вечером|днём|днем|в\s+\d{1,2}\s*(утра|дня|вечера)|"
                                  r"понедельник|вторник|сред[уа]|четверг|пятниц[уа]|суббот[уа]|воскресень[еа]|пн|вт|ср|чт|пт|сб|вс)\b", t.lower()))
        if amount is not None and 0 < amount < 1_000_000 and words and not has_when and not TASK_RX.match(t) and not ACTION_VERB_RX.match(t) \
                and not re.match(r"^\s*(встреч|созвон|звонок)", rest.lower()):
            cat = finance.guess_category(rest, "expense")
            if cat not in ("Другое", "Долги") and not DEBT_RX.match(t):
                when, rest2 = _past_date(rest)
                tx = finance.add_transaction(amount, "expense", cat, _strip_fillers(rest2) or None, source=channel, date=when)
                s = finance.summary(1)
                return Reply(say("expense", amount=money(tx.amount), category=tx.category, balance=money(s["total_balance"])), ["add_expense"])

    # ---- долг: «долг Сберу 120к плачу 8к 25-го» / «должен Ване 5000» ----
    m = DEBT_RX.match(t)
    if m:
        body = t[m.end():]
        total, rest = parse_amount(body)
        if total is not None:
            payment, rest2 = (None, rest)
            pm = re.search(r"(?:плачу|платёж|платеж|по)\s+(\d[\d\s.,]*\s*(?:к|тыс\w*)?)", rest, re.I)
            if pm:
                payment, _ = parse_amount(pm.group(1))
                rest2 = rest.replace(pm.group(0), " ")
            day = 1
            dm = re.search(r"(\d{1,2})[- ]?(?:го|числа)", rest2)
            if dm:
                day = int(dm.group(1)); rest2 = rest2.replace(dm.group(0), " ")
            title = _strip_fillers(re.sub(r"\b(каждое|каждый|месяц|в месяц|ежемесячно)\b", " ", rest2, flags=re.I)) or "Долг"
            try:
                d = finance.add_debt(title.capitalize(), total, payment or 0, 0, day)
            except finance.FinanceError as e:
                return Reply(f"Не записал: {e}, сэр.")
            f = finance.debt_forecast(d)
            txt = f"Долг «{d.title}» на {money(d.remaining)} записан."
            if f["months"]:
                txt += f" Платёж {money(d.payment)} каждое {day}-е → закроется через {f['months']} мес., к {f['close_date']}. Терпение, сэр."
            return Reply(txt, ["add_debt"])

    # ---- задача выполнена ----
    m = DONE_RX.match(t)
    if m and t[m.end():].strip():
        what = t[m.end():].strip()
        tk = tasks.complete_task(what)
        if tk:
            return Reply(say("done", title=tk.title) + tasks.progress_tail(tk.id), ["complete_task"])
        ev = calendar.find_event(what)
        if ev and ev.start <= datetime.now() + timedelta(hours=12) and not calendar.is_done(ev):
            # событие календаря — тоже дело: «сделал тренировку» ставит галочку на сегодняшней тренировке
            calendar.set_done(ev.id, True, ev.start)
            return Reply(say("done", title=ev.title), ["complete_event"])
        if ev and ev.start > datetime.now() + timedelta(hours=12) and not calendar.is_done(ev):
            # раньше отвечал «не нашёл», хотя событие есть — просто впереди. Честно: спросить, закрыть ли заранее
            _pending_set(channel, f"done_future|{ev.id}")
            return Reply(f"«{ev.title}» у вас {fmt_dt(ev.start)} — ещё не наступило. Отметить сделанным заранее? «Да» или «нет», сэр.", ["clarify"])
        if len(what.split()) <= 6:
            # раньше «готово: X» / «сделал X» без такой задачи проваливалось дальше и заводило задачу «Сделал X» — теперь честно говорим
            return Reply(f"Не нашёл дела «{what}» ни в задачах, ни в календаре, сэр. Если это просто факт — скажите «запомни: сделал {what}».", [])

    # ---- повторяющееся событие: «тренировка каждый пн ср пт в 19», «др мамы каждый год 14 марта» ----
    rule, rest_r = parse_repeat(t)
    if rule:
        dt0, rest_r = parse_datetime(rest_r)
        start = first_occurrence(rule, dt0)
        title = re.sub(r"^(напомни(?:\s+мне)?|у меня|мне|запланируй|добавь|поставь)\s+", "", rest_r, flags=re.I)
        title = _strip_fillers(title) or "Событие"
        title = title[0].upper() + title[1:]
        m_ev = EVENT_RX.match(title)
        if m_ev and title[m_ev.end():].strip():
            title = title[m_ev.end():].strip(); title = title[0].upper() + title[1:]
        ev = calendar.add_event(title, start, remind_minutes=30, source=channel, repeat=rule["repeat"], repeat_days=rule["days"])
        return Reply(f"Поставил «{ev.title}» — {fmt_repeat(ev)}, ближайшее {fmt_dt(ev.start)}. Напомню за полчаса, сэр.", ["add_event"])

    # ---- прошедшее время и показания: «вчера была у врача, сказали пить таблетки», «утром давление 140 на 90» —
    # это память (заметка), а не событие в календаре на вчера/завтра ----
    dt, rest = parse_datetime(t)
    starts_past = bool(re.match(r"^\s*(?:вчера|позавчера|сегодня|утром|днём|днем|вечером|только\s+что)?\s*,?\s*" + PAST_RX.pattern, low, re.I))
    if dt and rest and not _looks_like_question(t) and len(t.split()) <= 25 and (
            starts_past or (PAST_RX.search(low) and dt < datetime.now()) or (HEALTH_RX.search(low) and not EVENT_NOUN_RX.search(low))):
        brain_notes.add_note(t, source=channel)
        return Reply(say("note"), ["add_note"])

    # ---- встреча / событие ----
    m = EVENT_RX.match(t)
    has_clock = bool(re.search(r"\d{1,2}[:.]\d{2}|\b(?:в|на|к)\s+\d{1,2}\b|\d{1,2}\s+(?:утра|дня|вечера|ночи)|утром|вечером|днём|днем|ночью|в обед|полдень|полночь", low))
    # «ужин в 7 вечера», «в 19 созвон», «завтра утром зубной» — есть событийное слово или явное время и это не «надо сделать X»
    is_deadline = bool(re.search(r"\bдо\s+(конца|завтра|послезавтра|\d|пн|вт|ср|чт|пт|сб|вс|понедельник|вторник|сред|четверг|пятниц|суббот|воскресень)", low))
    explicit_task = bool(re.match(r"^\s*(задача|таск|todo|добавь\s+задачу)\s*[:\-—]", t, re.I))
    explicit_task = explicit_task or bool(re.match(r"^\s*(задача|таск|todo|добавь\s+задачу)\b", t, re.I))
    # «купить корм в 4», «позвонить маме в 5» — это дело со сроком, а не часовая встреча в календаре: глагол действия без
    # событийного слова уходит в задачи (в календаре задача всё равно видна — с галочкой и получасовым слотом)
    av = ACTION_VERB_RX.match(t)
    action_task = bool(av and re.search(r"(?:ть|ти|чь|и|й|ю)$", av.group(1).lower())   # «купить/купи/куплю», но не «сдача»
                       and not EVENT_NOUN_RX.search(low) and not m and not re.match(r"^\s*напомни", low))
    if dt and not is_deadline and not explicit_task and not action_task and (m or EVENT_NOUN_RX.search(low) or (has_clock and len(rest.split()) <= 8)):
        title = re.sub(r"^(напомни(?:\s+мне)?|у меня|мне)\s+", "", rest, flags=re.I)
        # «напомни … что надо не забыть вычесть жкх» → «вычесть жкх»
        title = re.sub(r"^(?:что\s+|чтобы\s+)?(?:(?:мне\s+)?(?:надо|нужно|стоит|пора)\s+(?:бы\s+)?)?(?:не\s+забыть|не\s+забудь)?\s*(?:что\s+)?(?:(?:мне\s+)?(?:надо|нужно)\s+)?", "", title, flags=re.I)
        title = re.sub(r"^(запиши\s+встречу|запланируй|добавь\s+(?:в\s+)?календар\w*|событие)\s*[:\-—]?\s*", "", title, flags=re.I)
        # «поставь событие что я иду на др» → «я иду на др»
        title = re.sub(r"^(поставь|создай|добавь|запиши|сделай)\s+(событие|встречу|напоминание|в\s+календарь)?\s*(,?\s*(что|о\s+том,?\s+что|про\s+то,?\s+что)\s+)?", "", title, flags=re.I)
        title = _strip_fillers(title) or "Событие"
        # «встреча с Ваней» → сохраняем «Встреча с Ваней», а не «С Ваней»
        title = title[0].upper() + title[1:]
        remind = 10 if low.startswith("напомни") else 30
        if low.startswith("напомни") and re.search(r"через\s+\S+\s*(мин|полчаса|час)", low):
            remind = 0   # «напомни через 20 минут» — ровно тогда
        ev = calendar.add_event(title, dt, remind_minutes=remind, source=channel)
        return Reply(say("event", title=ev.title, when=fmt_dt(ev.start)), ["add_event"])

    # ---- «напомни маме позвонить» без времени: спрашиваем когда ----
    if not dt and re.match(r"^\s*напомни\b", low) and len(t.split()) <= 10:
        what = re.sub(r"^\s*напомни(?:\s+мне)?\s*(?:что\s+(?:надо|нужно)\s+)?", "", t, flags=re.I).strip(" ,.-—:")
        if what:
            _pending_set(channel, "remind|" + what)
            return Reply(f"Напомнить «{what}» — когда, сэр? Например: «завтра в 10» или «через час».", ["clarify"])

    # ---- задача ----
    m = TASK_RX.match(t)
    # «заказ для Пятёрочки 25к до пятницы» — ACTION_VERB ловит «заказ» как «заказать»; с суммой и клиентом это заказ (модель/add_order), не задача
    _order_like = bool(re.match(r"^\s*(?:новый\s+)?(?:заказ|проект)\b", t, re.I) and parse_amount(t)[0] is not None)
    if not m and ACTION_VERB_RX.match(t) and len(t.split()) <= 12 and not _looks_like_question(t) and not _order_like:
        m = re.match(r"^\s*(?:надо бы|стоит|пора)?\s*", t, re.I)  # «починить полку» / «позвонить маме завтра»
    if m:
        body = t[m.end():].strip()
        due, body, time_set = parse_datetime_ex(body)
        due = task_due(due, time_set)   # «сегодня» / «через 3 дня» без времени = задача на весь день
        if body:
            from ..services import aims
            body, link = aims.split_link(body)
            tk = tasks.add_task(body[0].upper() + body[1:], due, source=channel)
            hint = aims.attach_hint(tk, link)
            if due and (nh := ambiguous_night_hour(t)) is not None and due.hour == nh + 12:
                hint += f" «В {nh}» понял как {due:%H:%M}; если имелось в виду {nh:02d}:00 — скажите «в {nh} утра»."
            return Reply(say("task", title=tk.title) + fmt_due(due) + hint, ["add_task"])

    # ---- заметка ----
    m = NOTE_RX.match(t)
    if m and t[m.end():].strip() and not _NOTE_BUT_EXPENSE_RX.match(t):
        brain_notes.add_note(t[m.end():].strip(), source=channel)
        return Reply(say("note"), ["add_note"])

    # ---- есть дата/время, но непонятно, что это: спросим, а не будем гадать ----
    # «сегодня 3 монтажа сдал, устал», «Вовчик устал сегодня» — дата есть, времени и дела нет: это рассказ, его ведёт модель/память
    _, _, _time_set = parse_datetime_ex(t)
    _told = bool(re.search(r"\b[а-яё]{2,}(?:ал|ил|ел|ул|ыл|ял)(?:а|и|о|ась|ись|ся)?\b", rest.lower()))   # «устал», «сдал», «сходила» — уже случилось
    if dt and rest and not _looks_like_question(t) and len(t.split()) <= 12 and (_time_set or EVENT_NOUN_RX.search(low) or ACTION_VERB_RX.search(rest) or not _told) \
            and not (re.match(r"^\s*(?:новый\s+)?(?:заказ|проект)\b", t, re.I) and parse_amount(t)[0] is not None):   # заказ с суммой — модели (add_order)
        _pending_set(channel, t)
        return Reply(f"«{rest}» — {fmt_dt(dt)}. Это событие в календарь или задача с дедлайном? Ответьте «календарь» или «задача», сэр.", ["clarify"])

    return None


EDIT_NOTE_RX = re.compile(r"^\s*(исправь|поправь|измени|дополни|допиши|обнови)\s+(?:в\s+)?(заметк\w*|мысл\w*|запис\w*)\s+(?:про|о|об|насчёт|насчет|с)?\s*"
                          r"(.+?)\s*[:\-—]\s*(.+)$", re.I | re.S)


def _edit_note_rule(t: str, channel: str) -> Reply | None:
    """«исправь заметку про очки: они в комоде», «дополни мысль о ролике: добавить титры» — правка памяти без модели."""
    m = EDIT_NOTE_RX.match(t)
    if not m:
        return None
    verb, _, query, body = m.group(1).lower(), m.group(2), m.group(3).strip(" «»\"'"), m.group(4).strip()
    n = brain_notes.find_note(query)
    if not n:
        return Reply(f"Заметку про «{query}» не нашёл, сэр. Посмотрите в Мозге, как она называется.", [])
    if verb.startswith(("дополни", "допиши")):
        head = (n.title or n.text.splitlines()[0])[:50]
        n = brain_notes.update_note(n.id, append=body)
        return Reply(f"Дописал в «{head}»: {body[:150]}", ["edit_note"])
    body = body[0].upper() + body[1:]
    n = brain_notes.update_note(n.id, text=body)
    return Reply(f"Заметка обновлена: «{n.text[:200]}». Старый вариант сохранён как оригинал.", ["edit_note"])


POMO_RX = re.compile(r"^\s*(?:" + identity.NAME_RX_SRC + r"\W*)?(?:запусти|включи|поставь|начни|стартуй)?\s*(?:таймер|помодоро|помидор\w*|фокус)\s*(?:на\s+(\d{1,3})\s*(?:мин\w*)?)?"
                     r"\s*(?:(?:по|на|над|для)\s+(.+?))?\s*[.!]?\s*$", re.I)
POMO_STOP_RX = re.compile(r"^\s*(?:стоп|останови|выключи|хватит|заверши|закончи)\s*(?:таймер|помодоро|фокус|работу)?\s*[.!]?\s*$|^\s*(?:таймер|помодоро)\s+(?:стоп|выкл\w*|хватит)\s*[.!]?$", re.I)
POMO_BREAK_RX = re.compile(r"^\s*(?:перерыв|пауза|отдых)\s*(?:на\s+)?(\d{1,2})?\s*(?:мин\w*)?\s*[.!]?\s*$", re.I)
POMO_Q_RX = re.compile(r"^\s*(?:сколько\s+(?:я\s+)?(?:сегодня\s+)?(?:работал\w*|наработал\w*|отработал\w*|фокус\w*)|(?:статус\s+)?таймер\??|помодоро\s+статус|сколько\s+осталось\s+(?:таймер\w*|помодоро))\W*$", re.I)
ORDER_RX = re.compile(r"^\s*(?:новый\s+)?(?:заказ|проект|взял\w*\s+(?:заказ|проект|в\s+работу)|монтаж)\s*[:\-—]\s*(.+)$", re.I | re.S)
LATE_Q_RX = re.compile(r"^\s*(?:кто\s+(?:задерживает|тянет|затягивает)(?:\s+(?:с\s+)?оплат(?:у|ы|ой|ами)?)?|задержки\s+(?:по\s+)?оплат\w*|просроченные\s+оплаты|кто\s+должен\s+давно)\W*$", re.I)
ORDERS_Q_RX = re.compile(r"^\s*(?:мои\s+)?(?:заказы|проекты|что\s+по\s+заказам|кто\s+(?:мне\s+)?(?:должен|не\s+заплатил)|сколько\s+(?:мне\s+)?не\s+оплачено|дедлайны)\W*$", re.I)
GOAL_RX = re.compile(r"^\s*(?:цель|копим|коплю|накопить|конверт)\s*(?:на)?\s*[:\-—]?\s*(.+)$", re.I | re.S)
SAVE_RX = re.compile(r"^\s*(отложил\w*|положил\w*\s+в\s+копилку|в\s+копилку|перевёл\s+в\s+копилку|перевел\s+в\s+копилку|взял\w*\s+из|снял\w*\s+с|достал\w*\s+из)\s+(.+)$", re.I)
PAYMENT_RX = re.compile(r"^\s*(?:пришл[аои]|приш[её]л|получил\w*|перевели|заплатил\w*|оплатил\w*)\s+(?:аванс|оплат\w*|предоплат\w*|деньги|\d)", re.I)
GOALS_Q_RX = re.compile(r"^\s*(?:мои\s+)?(?:цели|копилк\w*|конверты|накопления)\W*$", re.I)
FIN_TECH_RX = re.compile(r"^\s*(?:(50\s*/?\s*30\s*/?\s*20)|(сравни\w*\s+(?:с\s+)?прошл\w+\s+месяц\w*|месяц\s+к\s+месяцу|как\s+(?:я\s+)?трачу\s+по\s+сравнению)|"
                         r"(на\s+сколько\s+(?:дней\s+)?хватит|сколько\s+дней\s+(?:протяну|хватит))|(хватит\s+ли\s+на\s+платежи|хватает\s+(?:ли\s+)?на\s+платежи))\W*$", re.I)


_MONTH_TARGET_RX = re.compile(r"\s*\b(?:к|до)\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*(?:\s+(\d{4}))?\b", re.I)
_MONTH_N = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "май": 5, "мая": 5, "июн": 6, "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}


def _month_target(text: str):
    """«к марту», «до декабря 2027» → первое число того месяца (следующего такого, если уже прошёл)."""
    m = _MONTH_TARGET_RX.search(text)
    if not m:
        return None, text
    mon = _MONTH_N[m.group(1).lower()]
    now = datetime.now()
    year = int(m.group(2)) if m.group(2) else (now.year if mon > now.month else now.year + 1)
    return datetime(year, mon, 1, 23, 59), (text[:m.start()] + " " + text[m.end():]).strip()


PERSON_Q_RX = re.compile(r"^\s*(?:что\s+(?:по|у\s+меня\s+с|там\s+с|с)|кто\s+такой|кто\s+такая|кто\s+это|карточк[аи]\s+(?:клиента|человека)?|досье\s+(?:на)?|напомни\s+(?:мне\s+)?(?:про|кто\s+такой))\s+(?:по\s+)?([А-ЯЁA-Z@][\w@\-]*(?:\s+[А-ЯЁA-Z][\w\-]*)?)\s*[?.!]*\s*$", re.U)
PERSON_ADD_RX = re.compile(r"^\s*(?:человек|контакт|персона|клиент|компания|фирма|семья|родня|родственник|друг|подруга|приятель)\s*[:\-—]\s*(.+)$", re.I)


def _people_rules(t: str, channel: str) -> Reply | None:
    """«что по Ване», «кто такой Иванов», «человек: Лена, сестра» — без модели."""
    from ..services import people
    m = PERSON_Q_RX.match(t)
    if m:
        c = people.find_person(m.group(1))
        if c:
            return Reply(people.card_text(people.card(c)), ["person_card"])
        return None   # неизвестное имя — пусть решает модель/память
    m = PERSON_ADD_RX.match(t)
    if m:
        body = m.group(1).strip()
        head = t.lower().lstrip()
        kind = ("client" if head.startswith("клиент") else "company" if head.startswith(("компани", "фирм"))
                else "family" if head.startswith(("семья", "родн", "родствен")) else "friend" if head.startswith(("друг", "подруг", "прият"))
                else None)   # None — угадать по подписи
        name, _, rest = body.partition(",")
        name = name.strip(" «»\"'")
        if not name or len(name) > 60:
            return None
        c = people.add_person(name, kind, notes=rest.strip() or None)
        return Reply(f"{ {'client': 'Клиент', 'company': 'Компания', 'family': 'Семья', 'friend': 'Друг'}.get(c.kind, 'Карточка')} «{c.name}» — есть. Всё, где всплывёт это имя, теперь собирается в одном месте — спросите «что по …» или «кто такой …».", ["add_person"])
    return None


def people_hint(text: str, reply_text: str) -> str | None:
    """Триггер: в реплике всплыл известный человек → одна строка контекста (неоплата, долг, встреча). Не повторяем то, что уже в ответе."""
    from ..services import people
    try:
        found = people.people_in_text(text)
    except Exception:
        return None
    lines = []
    for c in found[:2]:
        if c.name.lower() in (reply_text or "").lower() and ("👤" in (reply_text or "")):
            continue
        h = people.hint_once(c)
        if h:
            lines.append(h)
    return "\n".join(lines) if lines else None


def _orders_rules(t: str, low: str, channel: str) -> Reply | None:
    """Заказы, помодоро, цели и фин-отчёты без модели — мгновенно."""
    from ..services import goals, orders
    r = _people_rules(t, channel)
    if r:
        return r
    if LATE_Q_RX.match(t):
        from ..services import pulse
        return Reply(pulse.late_text(), ["late_payments"])
    if ORDERS_Q_RX.match(t):
        return Reply(orders.summary_text(), ["list_orders"])
    if GOALS_Q_RX.match(t):
        return Reply(goals.goals_text(), ["list_goals"])
    m = FIN_TECH_RX.match(t)
    if m:
        kind = "buckets" if m.group(1) else "compare" if m.group(2) else "runway" if m.group(3) else "payments"
        return Reply(registry.finance_report(kind), ["finance_report"])
    if POMO_STOP_RX.match(t):
        return Reply(registry.pomodoro("stop", _channel=channel), ["pomodoro"])
    if POMO_Q_RX.match(t):
        return Reply(registry.pomodoro("status", _channel=channel), ["pomodoro"])
    m = POMO_BREAK_RX.match(t)
    if m:
        return Reply(registry.pomodoro("break", minutes=int(m.group(1)) if m.group(1) else None, _channel=channel), ["pomodoro"])
    m = POMO_RX.match(t)
    if m and re.search(r"таймер|помодоро|помидор|фокус", low):
        mins = int(m.group(1)) if m.group(1) else None
        q = (m.group(2) or "").strip(" «»\"'")
        if q and not orders.find_order(q):
            return Reply(f"Заказ «{q}» не нашёл, сэр. Запустил бы без привязки — скажите «таймер» без названия, или добавьте заказ: «заказ: {q}».", [])
        return Reply(registry.pomodoro("start", query=q or None, minutes=mins, _channel=channel), ["pomodoro"])
    m = GOAL_RX.match(t)
    if m:
        body = m.group(1).strip()
        amount, rest = parse_amount(body)
        dt, rest = _month_target(rest)
        if not dt:
            dt, rest = parse_datetime(rest)
        title = re.sub(r"\s{2,}", " ", rest).strip(" ,.-—:;")
        if amount and title:
            g = goals.add_goal(title, amount, dt, source=channel)
            v = goals.goal_view(g)
            return Reply(f"Цель «{g.title}»: {money(g.target)}" + (f" к {g.due:%d.%m.%Y} — откладывать по {money(v['per_month'])} в месяц" if v["per_month"] else "")
                         + ". Пополнять: «отложил 10к — " + g.title.lower() + "».", ["add_goal"])
    m = SAVE_RX.match(t)
    if m:
        amount, rest = parse_amount(m.group(2))
        q = re.sub(r"^\s*(?:в|на|—|-)\s*", "", rest).strip(" ,.-—:;«»\"'")
        if amount and q:
            g = goals.find_goal(q)
            if not g:
                return Reply(f"Цель «{q}» не нашёл, сэр. Есть: " + (", ".join(x["title"] for x in goals.list_goals()) or "пока ни одной — «цель: подушка 300к»") + ".", [])
            r_ = goals.put_to_goal(g.id, -amount if m.group(1).lower().startswith(("взял", "снял", "достал")) else amount, source=channel)
            v = r_["goal"]
            return Reply(f"«{v['title']}»: {money(v['saved'])} из {money(v['target'])} ({v['pct'] * 100:.0f}%)." + (" Цель достигнута 🎉" if r_["reached"] else ""), ["save_to_goal"])
    m = PAYMENT_RX.match(t)
    if m and not _too_long_for_rules(t):
        amount, rest = parse_amount(t)
        q = re.sub(r"^\s*(?:пришл[аои]|приш[её]л|получил\w*|перевели|заплатил\w*|оплатил\w*)\s*(?:аванс|оплат\w*|предоплат\w*|деньги)?\s*(?:за|от|по)?\s*", "", rest, flags=re.I).strip(" ,.-—:;«»\"'")
        q = re.sub(r"\s*(?:за|от|по)\s+(?:заказ\w*|ролик\w*|проект\w*)?\s*$", "", q).strip()
        when, q2 = parse_datetime(q)   # «…за ролик 20 августа» — деньги пришли задним числом
        pay_date = None
        if when and q2.strip() != q.strip():
            if when > datetime.now():   # парсер дат смотрит вперёд; оплата в будущем — это прошлый год
                when = when.replace(year=when.year - 1)
            pay_date = when.replace(hour=12, minute=0)
            q = q2.strip(" ,.-—:;«»\"'")
        if amount:
            o = orders.find_order(q) if q else (orders.list_orders()[0] if len(orders.list_orders()) == 1 else None)
            if o and hasattr(o, "id"):
                oid = o.id
            elif isinstance(o, dict):
                oid = o["id"]
            else:
                oid = None
            if oid:
                if amount >= CONFIRM_AMOUNT:
                    return None   # крупная сумма — через модель с подтверждением
                orders.add_payment(oid, amount, source=channel, date=pay_date)
                v = orders.order_view(orders.get_order(oid))
                return Reply(f"Оплата {money(amount)} по «{v['title']}» — в доходах" + (f" за {pay_date:%d.%m}" if pay_date else "") + "." + (f" Осталось {money(v['left'])}." if v["left"] > 0 else " Заказ закрыт как оплаченный ✓"), ["order_payment"])
    m = ORDER_RX.match(t)
    if m and not _too_long_for_rules(t):
        body = m.group(1).strip()
        # «ролик для Пятёрочки, 25к, до пятницы» — клиент («для X» с заглавной), сумма и дата вырезаются, остаток — название
        client = None
        mc = re.search(r"(?:^|\s)(?:для|от|клиент[:\s])\s*([А-ЯЁA-Z][\w\-]*(?:\s+[А-ЯЁA-Z][\w\-]*)?)", body)
        if mc:
            client = mc.group(1); body = (body[:mc.start()] + " " + body[mc.end():]).strip()
        amount, rest = parse_amount(body)
        dt, rest = parse_datetime(rest)
        title = re.sub(r"\s{2,}", " ", rest).strip(" ,.-—:;")
        title = title[0].upper() + title[1:] if title else title
        if title:
            o = orders.add_order(title, amount or 0, client, dt, source=channel)
            v = orders.order_view(o)
            return Reply(f"Заказ #{o.id} «{o.title}»" + (f" · {v['client']}" if v["client"] else "") + (f" · {money(o.price)}" if o.price else " · сумму уточним")
                         + (f" · до {o.deadline:%d.%m}" if o.deadline else "") + ". В работе. Скажите «таймер на " + o.title.split()[0].lower() + "», когда сядете за него.", ["add_order"])
    return None


def _edit_rules(t: str, channel: str) -> Reply | None:
    """«перенеси ужин на 8», «переименуй встречу в созвон», «удали задачу про полку», «сегодня тренировки не будет»."""
    m = SKIP_RX.match(t)
    if m:
        ev = calendar.find_event(m.group(2).strip())
        if ev and ev.repeat:
            day = datetime.now() + (timedelta(days=1) if m.group(1).lower() == "завтра" else timedelta(0))
            calendar.skip_occurrence(ev.id, day)
            return Reply(f"Понял, «{ev.title}» {m.group(1).lower()} пропускаем. Повтор остаётся.", ["update_event"])
        if ev:
            calendar.delete_event(ev.id)
            return Reply(f"Убрал «{ev.title}» из календаря.", ["delete_event"])
        return Reply(f"Не нашёл «{m.group(2).strip()}» в календаре, сэр.")

    m = MOVE_RX.match(t)
    if m:
        what, when = m.group(2).strip(), m.group(3).strip()
        # «на 8» / «на 20:00» / «на завтра в 10» / «на пятницу»
        dt, _ = parse_datetime("в " + when if re.fullmatch(r"\d{1,2}(?:[:.]\d{2})?", when) else when)
        if not dt:
            return Reply(f"Не понял, на когда перенести «{what}», сэр. Скажите время или день.")
        ev = calendar.find_event(what)
        if ev:
            # «на 8» без даты — оставляем день события, меняем только время
            if re.fullmatch(r"(?:в\s+)?\d{1,2}(?:[:.]\d{2})?(?:\s*(?:утра|вечера|дня|ночи))?", when.lower()):
                dt = ev.start.replace(hour=dt.hour, minute=dt.minute)
            old = fmt_dt(ev.start)
            ev = calendar.update_event(ev.id, start=dt)
            return Reply(f"Перенёс «{ev.title}»: {old} → {fmt_dt(ev.start)}.", ["update_event"])
        tk = tasks.find_task(what)
        if tk:
            tasks.update_task(tk.id, due=dt)
            return Reply(f"Дедлайн «{tk.title}» теперь {fmt_dt(dt)}.", ["update_task"])
        return Reply(f"Не нашёл «{what}» ни в календаре, ни в задачах, сэр.")

    m = RENAME_RX.match(t)
    if m:
        what, new = m.group(2).strip(), m.group(3).strip()
        what = re.sub(r"^(задачу|событие|встречу)\s+", "", what, flags=re.I)
        ev = calendar.find_event(what)
        if ev:
            calendar.update_event(ev.id, title=new[0].upper() + new[1:])
            return Reply(f"«{ev.title}» теперь называется «{new[0].upper() + new[1:]}».", ["update_event"])
        tk = tasks.find_task(what)
        if tk:
            tasks.update_task(tk.id, title=new[0].upper() + new[1:])
            return Reply(f"Задача «{tk.title}» → «{new[0].upper() + new[1:]}».", ["update_task"])
        return Reply(f"Не нашёл «{what}», сэр.")

    m = DELETE_RX.match(t)
    if m and m.group(3).strip() and not re.match(r"^(последн|это|её|его)", m.group(3).strip(), re.I):
        kind = (m.group(2) or "").lower()
        what = m.group(3).strip(" .!«»\"")
        if kind.startswith("задач") or not kind:
            tk = tasks.find_task(what)
            if tk and (kind or not calendar.find_event(what)):
                tasks.delete_task(tk.id)
                return Reply(f"Задача «{tk.title}» удалена.", ["delete_task"])
        if kind.startswith(("событ", "встреч", "напомин")) or not kind:
            ev = calendar.find_event(what)
            if ev:
                calendar.delete_event(ev.id)
                return Reply(f"«{ev.title}» ({fmt_dt(ev.start)}) убрано из календаря.", ["delete_event"])
        if kind.startswith(("заметк", "мысл")):
            n = brain_notes.find_note(what)
            if n:
                brain_notes.delete_note(n.id)
                return Reply("Заметку удалил.", ["delete_note"])
        if kind:
            return Reply(f"Не нашёл «{what}», сэр.")
    return None


YES_RX = re.compile(r"^\s*(да|давай|ага|угу|подтверждаю|конечно|точно|yes|ок|окей|окей давай|да,?\s*удали|удаляй|стирай|сотри|погнали|валяй|делай)\s*[.!]*\s*$", re.I)
NO_RX = re.compile(r"^\s*(нет|не надо|отмена|отбой|стоп|не|неа|передумал|оставь|не удаляй|no)\s*[.!]*\s*$", re.I)
_PLURAL_RX = re.compile(r"^(финанс\w*|операци[ии]|транзакции|траты|расходы|доходы|платежи|задачи|дела|события|встречи|календар\w*|напоминания|"
                        r"заметки|мысли|идеи|ссылки|закладки|чат|переписк\w*|сообщения|истори\w*.*)$", re.I)


def _bulk_rule(t: str, channel: str) -> Reply | None:
    """«сотри все финансы за последние 2 дня», «удали задачи за неделю», «очисти историю чата».
    Никогда не удаляет сразу: показывает, сколько попадёт под нож, и ждёт «да»."""
    m = bulk.BULK_RX.match(t)
    if not m:
        return None
    noun, tail = m.group(2), (m.group(3) or "").strip()
    kind = bulk.kind_of(noun)
    if not kind:
        return None
    has_all = bool(re.search(r"\b(все|всю|всё|всех|полностью)\b", t[: m.start(2)], re.I))
    has_period = bool(re.match(r"^(за|с|начиная)\b", tail, re.I))
    plural = bool(_PLURAL_RX.match(noun))
    if not (has_all or has_period or (plural and not tail)):
        return None   # «удали задачу про полку» — это точечное удаление, им займётся _edit_rules
    since, until, label = bulk.parse_period(tail)
    txt = bulk.describe(kind, since, until, label)
    if txt.startswith("Тут и стирать"):
        return Reply(txt, [])
    _pending_set(channel, "bulk|" + json.dumps({"kind": kind, "since": since.isoformat() if since else None,
                                                 "until": until.isoformat() if until else None, "label": label}, ensure_ascii=False))
    return Reply(txt, ["clarify"])


def _resolve_bulk(text: str, channel: str) -> Reply | None:
    p = _pending_get(channel)
    if not p or not p[0].startswith("bulk|"):
        return None
    orig, ts = p
    if (datetime.now() - ts).total_seconds() > PENDING_TTL_SEC:
        _pending_clear(channel)
        return None
    if YES_RX.match(text):
        _pending_clear(channel)
        d = json.loads(orig[5:])
        since = datetime.fromisoformat(d["since"]) if d["since"] else None
        until = datetime.fromisoformat(d["until"]) if d["until"] else None
        res = bulk.execute(d["kind"], since, until, channel)
        if not res["count"]:
            return Reply("Уже пусто, сэр — удалять нечего.", [])
        return Reply(f"Стёр {res['count']} {res['label']} {d['label']}." +
                     (" Балансы пересчитал." if d["kind"] == "transaction" else "") +
                     " Передумаете — скажите «отмена», всё лежит в корзине.", ["bulk_delete"])
    if NO_RX.match(text):
        _pending_clear(channel)
        return Reply("Отбой, ничего не трогаю.", [])
    _pending_clear(channel)   # спросил про другое — забываем вопрос
    return None


def _resolve_pending(text: str, channel: str) -> Reply | None:
    """Ответ на уточняющий вопрос: «календарь» / «задача» / «заметка» / «нет»."""
    p = _pending_get(channel)
    if not p:
        return None
    orig, ts = p
    if orig.startswith(("bulk|", "confirm|", "sorter|")):
        return None
    if (datetime.now() - ts).total_seconds() > PENDING_TTL_SEC:
        _pending_clear(channel)
        return None
    if orig.startswith("done_future|"):
        if YES_RX.match(text):
            _pending_clear(channel)
            ev = calendar.set_done(int(orig[12:]), True)
            return Reply(say("done", title=ev.title), ["complete_event"]) if ev else Reply("Событие уже исчезло, сэр.", [])
        if NO_RX.match(text):
            _pending_clear(channel)
            return Reply("Оставил как есть.", [])
        return None
    if orig.startswith("remind|"):
        what = orig[7:]
        if re.match(r"^\s*(нет|не надо|отмена|забудь|отбой|никогда)\b", text, re.I):
            _pending_clear(channel)
            return Reply("Понял, без напоминания. Тогда просто задача.", []) if not tasks.add_task(what[0].upper() + what[1:], None, source=channel) else Reply(f"Хорошо, без времени. «{what[0].upper() + what[1:]}» — в задачах.", ["add_task"])
        dt, _ = parse_datetime(text)
        if not dt:
            return None   # это не ответ на вопрос — обычная фраза
        _pending_clear(channel)
        title = what[0].upper() + what[1:]
        ev = calendar.add_event(title, dt, remind_minutes=0 if re.search(r"через", text, re.I) else 10, source=channel)
        return Reply(say("event", title=ev.title, when=fmt_dt(ev.start)), ["add_event"])
    m = CLARIFY_RX.match(text)
    if not m:
        return None
    _pending_clear(channel)
    kind = m.group(2).lower()
    dt, rest = parse_datetime(orig)
    title = (rest or orig).strip(" ,.-—:")
    title = title[0].upper() + title[1:] if title else "Событие"
    if kind.startswith(("календар", "событи", "напомина")):
        ev = calendar.add_event(title, dt, remind_minutes=30, source=channel)
        return Reply(say("event", title=ev.title, when=fmt_dt(ev.start)), ["add_event"])
    if kind.startswith(("задач", "дел")):
        dt = task_due(dt, parse_datetime_ex(orig)[2])
        tk = tasks.add_task(title, dt, source=channel)
        return Reply(say("task", title=tk.title) + fmt_due(dt), ["add_task"])
    if kind.startswith(("заметк", "мысл", "мозг")):
        brain_notes.add_note(orig, source=channel)
        return Reply(say("note"), ["add_note"])
    return Reply("Понял, забыли.", [])


# Суммы от этого порога, пришедшие из инструмента LLM (не из правил-шаблонов, где цифру написал сам человек),
# записываем только после «да»: маленькая модель путает 15 000 и 150 000, а откатывать потом — лишняя работа.
CONFIRM_AMOUNT = 100_000
_CONFIRM_TOOLS = {"add_expense": "amount", "add_income": "amount", "transfer": "amount", "pay_debt": "amount", "set_balance": "balance", "order_payment": "amount", "save_to_goal": "amount"}


def _needs_confirm(name: str, args: dict) -> float | None:
    key = _CONFIRM_TOOLS.get(name)
    if not key:
        return None
    try:
        v = abs(float(str((args or {}).get(key, 0)).replace(" ", "").replace(",", ".")))
    except (TypeError, ValueError):
        return None
    return v if v >= CONFIRM_AMOUNT else None


def _confirm_question(name: str, args: dict, amount: float) -> str:
    what = {"add_expense": "трату", "add_income": "доход", "transfer": "перевод", "pay_debt": "платёж по долгу", "set_balance": "баланс", "order_payment": "оплату по заказу", "save_to_goal": "перевод в цель"}[name]
    tail = (args or {}).get("note") or (args or {}).get("account") or (args or {}).get("debt") or (args or {}).get("to_account") or ""
    return f"Записать {what} на **{money(amount)}**" + (f" ({tail})" if tail else "") + "? Сумма крупная — подтвердите «да» или «нет», сэр."


async def _resolve_sorter_draft(text: str, channel: str) -> Reply | None:
    """«Да»/«нет» на черновик разбора списка (настройка «показывать разбор перед записью»)."""
    p = _pending_get(channel)
    if not p or not p[0].startswith("sorter|"):
        return None
    orig, ts = p
    _pending_clear(channel)
    if (datetime.now() - ts).total_seconds() > PENDING_TTL_SEC:
        return None
    return await sorter.resolve_pending(text, channel, orig, CONFIRM_AMOUNT)   # None — заговорили о другом, черновик снят


def _resolve_confirm(text: str, channel: str) -> Reply | None:
    p = _pending_get(channel)
    if not p or not p[0].startswith("confirm|"):
        return None
    orig, ts = p
    if (datetime.now() - ts).total_seconds() > PENDING_TTL_SEC:
        _pending_clear(channel)
        return None
    if YES_RX.match(text):
        _pending_clear(channel)
        d = json.loads(orig[8:])
        if "pc" in d:
            cmd = pc.PcCommand("power", d["pc"], say="Выключаю компьютер через 30 секунд. «Отмена выключения» — если передумали." if d["pc"] == "shutdown" else "Перезагружаю через 30 секунд.")
            return Reply(pc.dispatch(cmd, channel), ["pc_power"], "rules")
        if "tidy" in d:
            cmd = pc.PcCommand("tidy_apply", d["tidy"], say="Убираю. Отчёт — через пару секунд.")
            return Reply(pc.dispatch(cmd, channel), ["pc_tidy"], "rules")
        res = registry.run_tool(d["name"], d["args"], channel)
        return Reply(res, [d["name"]], "rules")
    if NO_RX.match(text):
        _pending_clear(channel)
        return Reply("Отбой, ничего не делаю.", [], "rules")
    _pending_clear(channel)   # заговорили о другом — вопрос снимается, ничего не записано
    return None


_SAVED_RX = re.compile(r"\b(запис[ая]|записал|сохран[ия]|сохранил|запомн[ию]|запомнил|добав[ия]л|зафиксир|внес|внёс)\w*", re.I)


_FORCED = [
    (re.compile(r"баланс|финанс|сколько\s+(?:у\s+меня\s+)?денег|деньг|бюджет|куда\s+(?:ушл|дел)|как\s+(?:я\s+)?трач", re.I), "finance_summary", {"days": 30}),
    (re.compile(r"долг|кредит|кому\s+(?:я\s+)?должен", re.I), "list_debts", {}),
    (re.compile(r"задач|что\s+(?:мне\s+)?(?:надо|нужно)\s+сделать|мои\s+дела", re.I), "list_tasks", {}),
    (re.compile(r"встреч|календар|событи|что\s+у\s+меня\s+(?:на\s+неделе|завтра|сегодня)|план\w*\s+на", re.I), "list_events", {"days": 7}),
]


def _forced_tool(text: str) -> tuple[str, dict] | None:
    """Вопрос о личных данных (без глагола-действия), на который модель ответила «из головы»: какой инструмент дать вместо неё."""
    if _is_analysis(text) or _too_long_for_rules(text):
        return None
    if not _looks_like_question(text) and not re.search(r"\?$|сколько|какие|что\s+по|как\s+(?:там\s+)?(?:у\s+меня|мои|с\s+)", text, re.I):
        return None
    if re.search(r"\b(добавь|запиши|потратил|купил|заплатил|перевёл|перевел|напомни|создай|удали|отмени|закрой|перенеси)\b", text, re.I):
        return None
    for rx, name, args in _FORCED:
        if rx.search(text):
            return name, args
    return None


def _claims_saved(answer: str) -> bool:
    return bool(_SAVED_RX.search(answer or ""))


def _looks_like_question(text: str) -> bool:
    t = text.strip().lower()
    return t.endswith("?") or bool(_QUESTION_RX.match(t)) or bool(RECHECK_RX.match(t))


# --------------------------------------------------------------------------- история чата
HISTORY_MAX_AGE_H = 12   # вчерашний разговор — не контекст: модель начинает «продолжать» тему, которой уже нет


_FAIL_WHY = {"add_event": "не разобрал дату и время", "add_task": "не понял, что за дело",
             "add_expense": "не понял сумму", "add_income": "не понял сумму", "add_order": "не хватило данных о заказе"}


def _destructive_question(name: str, args: dict) -> str:
    what = {"delete_event": "удалить событие", "stop_recurring": "остановить регулярный платёж"}.get(name, f"выполнить {name}")
    target = (args or {}).get("query") or (args or {}).get("title") or ""
    return f"Точно {what}" + (f" «{target}»" if target else "") + "? Это не отменить одной кнопкой — скажите «да» или «нет», сэр."


def _truth_gate(answer: str, results: list["registry.ToolResult"]) -> str:
    """Последняя проверка перед тем, как отдать ответ человеку.

    Модель видит результат инструмента и всё равно склонна закончить бодрым «Готово, сэр» — особенно маленькая.
    Здесь сверяемся не с её словами, а с тем, что реально легло в базу (registry.call проверил это чтением).
    Ничего не записалось, а ответ обещает обратное — заменяем ответ. Записалось частично — дописываем, что именно не вышло.
    """
    # провал, который модель тут же исправила повторным вызовом того же инструмента, — не провал:
    # «не разобрал дату» → модель прислала ISO → записано. Человеку про первую попытку знать незачем.
    failed = [r for r in results if not r.ok and not any(s.ok and s.name == r.name for s in results)]
    if not failed:
        return answer
    why = "; ".join(_FAIL_WHY.get(r.name, "не выполнено") for r in failed[:2])
    failed_writes = [r for r in failed if r.risk != "read"]
    if not failed_writes:
        # сломался только читающий инструмент — остальной ответ мог быть полезным, не затираем его
        return answer.rstrip() + "\n\n⚠️ Часть данных поднять не удалось — цифры могут быть неполными."
    if any(r.wrote for r in results):
        return answer.rstrip() + f"\n\n⚠️ Но не всё: {why}. Остальное записано."
    # ни одной успешной записи, а инструмент записи провалился: что бы модель ни написала, это неправда.
    # Не полагаемся на то, распознали ли мы её формулировку как «обещание» — заменяем ответ целиком.
    hint = ("Скажите иначе — например, «встреча завтра в 15:00 с Димой»."
            if any(r.name == "add_event" for r in failed_writes) else "Повторите фразу поточнее — запишу.")
    return f"Не записал, сэр: {why}. {hint}"


def _history(channel: str, limit: int = 6, max_chars: int = 600, current: str | None = None) -> list[dict]:
    """Последние реплики для контекста (все каналы: чат сайта и Telegram — один разговор).
    Длинные сообщения режем, старше HISTORY_MAX_AGE_H часов — не берём: история не должна съедать окно модели
    и тянуть в ответ тему трёхдневной давности. current — текущая реплика: она уже записана в чат (_log_chat в начале
    _handle) и отдельно идёт последним сообщением, поэтому из истории её убираем — иначе модель видит её дважды."""
    since = datetime.now() - timedelta(hours=HISTORY_MAX_AGE_H)
    with session() as s:
        rows = s.exec(select(ChatMessage).where(ChatMessage.created_at >= since).order_by(ChatMessage.id.desc()).limit(limit + 1)).all()
    if rows and rows[0].role == "user" and (current is None or (rows[0].text or "").strip() == current.strip()):
        rows = rows[1:]
    rows = rows[:limit]
    out = []
    for r in reversed(rows):
        t = r.text or ""
        if r.role == "assistant" and t.startswith("Что-то пошло не так"):
            continue   # наш собственный сбой — не контекст
        if len(t) > max_chars:
            t = t[:max_chars].rsplit(" ", 1)[0] + " …"
        out.append({"role": r.role, "text": t})
    return out


def _log_chat(role: str, text: str, channel: str) -> None:
    with session() as s:
        s.add(ChatMessage(role=role, text=text, channel=channel))
        s.commit()


# --------------------------------------------------------------------------- LLM-путь
CJK_RX = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


async def _russian_only(messages: list[dict], out: dict) -> str:
    """qwen2.5 иногда отвечает по-китайски (особенно на невнятный ввод). Ловим и переспрашиваем один раз;
    если и второй раз китайский — вырезаем иероглифы."""
    content = out.get("content") or ""
    if not CJK_RX.search(content):
        return content
    log.warning("ответ модели содержит иероглифы — переспрашиваю по-русски")
    retry = messages + [{"role": "assistant", "content": content},
                        {"role": "user", "content": "Ты ответил на китайском. Повтори этот же ответ ТОЛЬКО на русском языке, кириллицей, коротко."}]
    try:
        out2 = await _chat(retry, temperature=0.1)
        c2 = out2.get("content") or ""
        if c2 and not CJK_RX.search(c2):
            return c2
    except Exception as e:
        log.debug("retry failed: %s", e)
    cleaned = "\n".join(l for l in content.splitlines() if not CJK_RX.search(l)).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned or "Готово, сэр."


def _cloud_tools_mode() -> bool:
    """brain.mode = cloud без Ollama: инструменты (записать трату, найти заметку, что сегодня) выполняет облачная модель.
    Личные данные при этом уходят провайдеру — пользователь выбрал это в мастере осознанно."""
    return llm.MODE == "cloud" and llm.cloud_enabled() and llm.CLOUD_PROVIDER not in ("", "gemini")


async def _chat(messages: list[dict], tools: list[dict] | None = None, **kw) -> dict:
    """Локальная модель или — в режиме cloud — облако с теми же инструментами."""
    if _cloud_tools_mode():
        out = await llm.cloud_tools_chat(messages, tools or [], temperature=kw.get("temperature", 0.2))
        if out is None:
            raise RuntimeError(llm.LAST_CLOUD_ERROR or "облако не ответило")
        return out
    return await llm.ollama_chat(messages, tools, **kw)


def _no_repeat_block() -> str:
    """Образы (слова) из последних ответов и проактивных — в промпт чата, чтобы модель не повторяла один и тот же факт из памяти."""
    used = persona.recent_images()
    return ("\nНЕДАВНО УПОМЯНУТЫЕ ОБРАЗЫ (не повторяй их в этом ответе): " + ", ".join(used[:20]) + "\n") if used else ""


def _fit_budget(messages: list[dict], tools: list[dict], channel: str) -> list[dict]:
    """Уложить запрос в окно локальной модели БЕЗ смены num_ctx: сначала выкидываем историю (старые реплики), потом блок памяти.
    Оценка как в llm.ollama_chat (символы/3). Смена окна — это перезагрузка модели (+12 с), а 16384 на 6 ГБ вытесняет
    часть весов в оперативку, и чтение промпта замедляется в 3–4 раза (7.5k токенов за 35 с в логе пользователя)."""
    budget = llm.OLLAMA_NUM_CTX - (160 if llm.short_mode.get() else 512) - 250
    tools_len = len(json.dumps(tools, ensure_ascii=False)) if tools else 0

    def est(msgs: list[dict]) -> int:
        return (sum(len(str(m.get("content") or "")) for m in msgs) + tools_len) // 3 + 200

    before = est(messages)
    dropped = 0
    while est(messages) > budget and len(messages) > 2:
        messages.pop(1)   # самая старая реплика истории (0 — system, -1 — текущая)
        dropped += 1
    if est(messages) > budget and "ЧТО ТЫ ЗНАЕШЬ О ХОЗЯИНЕ" in (messages[-1].get("content") or ""):
        body = messages[-1]["content"]
        messages[-1]["content"] = body[body.rindex("\n", 0, body.rfind("(сейчас ")) + 1:] if "(сейчас " in body else body.splitlines()[-1]
        dropped += 100
    if dropped:
        log.info("[%s] промпт ≈%d ток. > окно %d: убрал %s → ≈%d ток.", channel, before, llm.OLLAMA_NUM_CTX,
                 (f"{dropped % 100} реплик истории" if dropped % 100 else "") + (" и блок памяти" if dropped >= 100 else ""), est(messages))
    return messages


async def via_ollama(text: str, channel: str, with_tools: bool = True) -> Reply | None:
    cloud_tools = _cloud_tools_mode()
    if not cloud_tools and (llm.MODE == "cloud" or not await llm.ollama_available()):
        return None
    via = "gemini" if cloud_tools else "ollama"
    if not with_tools:
        # болтовня/общий вопрос, облако не ответило: без схем инструментов промпт в 4–5 раз короче → ответ в разы быстрее
        voice_hint = " Отвечай 1–2 короткими предложениями, без списков и эмодзи." if channel.endswith("voice") else ""
        messages = [{"role": "system", "content": system_prompt(compact=not cloud_tools) + voice_hint + await memory.context(text) + _no_repeat_block()}]
        for h in _history(channel, 4, current=text):
            messages.append({"role": h["role"], "content": h["text"]})
        messages.append({"role": "user", "content": text + "\n" + now_line()})
        try:
            out = await _chat(messages)
            return Reply((await _russian_only(messages, out)) or "…", [], via)
        except Exception as e:
            log.exception("%s failed: %s", "cloud tools" if cloud_tools else "ollama", e)
            return None
    voice_hint = "\nОТВЕТ ГОЛОСОМ: максимум 1–2 коротких предложения, без списков, без markdown и без эмодзи.\n" if channel.endswith("voice") else ""
    allow_cloud_pre = llm.cloud_enabled() and llm.GEMINI_AUTO
    # Блок памяти («что ты знаешь о хозяине») меняется от фразы к фразе, поэтому он идёт НЕ в системное сообщение,
    # а перед репликой пользователя: системный промпт + схемы 40 инструментов тогда неизменны от запроса к запросу,
    # и Ollama берёт их из кэша вместо того, чтобы каждый раз заново читать ~6k токенов (на 6 ГБ карте это 15–25 с).
    mem_ctx = await memory.context(text)
    messages = [{"role": "system", "content": system_prompt(compact=not cloud_tools) + voice_hint +
                 "\nУ тебя есть инструменты — это ЕДИНСТВЕННЫЙ способ что-то сохранить. Правила:\n"
                 "• Просят записать/добавить/запомнить/сохранить/напомнить/показать — ВЫЗОВИ инструмент. "
                 "Отвечать «записал» без вызова инструмента ЗАПРЕЩЕНО — это ложь.\n"
                 "• Пользователь делится мыслью, идеей, наблюдением, планом, фактом о себе (не вопрос и не приказ) — "
                 "это заметка: вызови add_note с его текстом как есть.\n"
                 "• Пользователь пишет о трате/доходе/долге/встрече/задаче — соответствующий инструмент.\n"
                 "• Есть конкретное время или дата («ужин в 7 вечера», «завтра в 10 зубной») → add_event на ЭТО время; "
                 "без даты «сегодня» считай, что речь о сегодня (если время ещё не прошло) или завтра.\n"
                 "• Дело без времени («починить полку», «купить молоко») → add_task. С «до пятницы» — add_task с due.\n"
                 "• Фриланс: «заказ/проект/взял монтаж … для … за … до …» → add_order (все детали одним вызовом, даже надиктованные вразнобой); "
                 "«сдал/правки/отменили …» → update_order; «пришёл аванс/оплата от …» → order_payment (НЕ add_income); "
                 "«помодоро/таймер/стоп/сколько работал» → pomodoro; «заказы/кто должен» → list_orders.\n"
                 "• «Цель/копим/подушка … к …» → add_goal; «отложил … в …» → save_to_goal; «50/30/20», «сравни с прошлым месяцем», "
                 "«на сколько хватит», «хватит ли на платежи», «цели» → finance_report.\n"
                 "• Если непонятно, событие это или задача, — задай ОДИН короткий уточняющий вопрос вместо угадывания.\n"
                 "• Просто вопрос или болтовня — отвечай без инструментов.\n"
                 "• ЦИФРЫ ТОЛЬКО ИЗ ИНСТРУМЕНТОВ. Спрашивают про баланс, траты, доходы, долги, задачи, встречи — сначала вызови "
                 "finance_summary / spent / list_debts / list_tasks / list_events / agenda и отвечай по их результату. "
                 "Придумывать суммы, даты и остатки ЗАПРЕЩЕНО. Не вызвал инструмент — значит, не знаешь, так и скажи.\n"
                 "• «Разбери ситуацию», «посчитай», «хватит ли», «не записывай» — человек хочет АНАЛИЗА: возьми данные через "
                 "finance_summary/list_debts/agenda, сложи с цифрами из его сообщения и дай расклад по пунктам. В базу НИЧЕГО не пиши, "
                 "разве что в конце предложи: «записать эти доходы/траты как ожидаемые?».\n"
                 "• Пользователь спорит, сомневается или просит перепроверить («откуда взял», «сверься») — это НЕ заметка: "
                 "вызови инструмент заново и ответь по фактам.\n"
                 "Даты передавай в ISO 8601. После результата инструмента — короткий ответ в характере."}]
    for h in _history(channel, current=text):
        messages.append({"role": h["role"], "content": h["text"]})
    messages.append({"role": "user", "content": (mem_ctx + "\n" if mem_ctx else "") + (_no_repeat_block() if mem_ctx else "") + text + "\n" + now_line()})
    tools_now = registry.tools_schema(with_cloud=allow_cloud_pre and not cloud_tools, text=None if cloud_tools else text)
    if not cloud_tools:
        messages = _fit_budget(messages, tools_now, channel)
    actions: list[str] = []
    done_results: list[str] = []   # что уже реально сделано — на случай падения модели после вызова инструментов
    results: list[registry.ToolResult] = []   # чем на самом деле кончился каждый вызов (проверено по базе)
    seen_calls: dict[tuple[str, str], bool] = {}   # подпись вызова → прошёл ли он (для стража дублей)
    allow_cloud = llm.cloud_enabled() and llm.GEMINI_AUTO
    try:
        for _ in range(4):  # максимум 4 вызова инструментов подряд
            out = await _chat(messages, tools_now if allow_cloud == allow_cloud_pre else registry.tools_schema(with_cloud=False, text=None if cloud_tools else text))
            trace.step(llm._cloud_model() if cloud_tools else llm.OLLAMA_MODEL)
            if not out["tool_calls"] and not actions:
                forced = _forced_tool(text)
                if forced:
                    # вопрос о данных, а модель инструмент не вызвала (и, скорее всего, сочинила цифры) — вызываем сами
                    name, args = forced
                    log.info("[%s] модель ответила без инструмента на вопрос о данных → %s", channel, name)
                    tr = registry.call(name, args, channel)
                    results.append(tr)
                    if tr.ok:
                        actions.append(name)
                        return Reply(tr.text, actions, via)
                    # инструмент, который мы позвали за модель, тоже может упасть — тогда не выдаём сырую ошибку
                    log.warning("[%s] принудительный %s не выполнен: %s", channel, name, tr.error)
                    return Reply(_truth_gate(out.get("content") or "", results) or
                                 "Не смог поднять цифры, сэр — данные не отдались. Попробуйте ещё раз.", actions, via)
            if not out["tool_calls"]:
                content = (await _russian_only(messages, out)) or "…"
                content = _truth_gate(content, results)
                # модель не вызвала НИ ОДНОГО инструмента, но пишет «записал» — старый путь: сохраняем сами.
                # Если инструмент вызывался и провалился, сюда не идём: _truth_gate уже сказал правду,
                # а угадывать запись за упавшим инструментом — как раз способ записать не то.
                if not actions and not results and _claims_saved(content) and not _looks_like_question(text) and not _is_analysis(text) and not _too_long_for_rules(text):
                    # модель соврала, что сохранила — сохраняем сами: время → событие, глагол дела → задача, иначе заметка
                    dt, rest = parse_datetime(text)
                    if dt and rest:
                        title = rest[0].upper() + rest[1:]
                        if ACTION_VERB_RX.match(text):
                            tasks.add_task(title, dt, source=channel); actions.append("add_task")
                            content = say("task", title=title) + f" Дедлайн {fmt_dt(dt)}."
                        else:
                            ev = calendar.add_event(title, dt, source=channel); actions.append("add_event")
                            content = say("event", title=ev.title, when=fmt_dt(ev.start))
                    elif ACTION_VERB_RX.match(text):
                        tk = tasks.add_task(text[0].upper() + text[1:], source=channel); actions.append("add_task")
                        content = say("task", title=tk.title)
                    else:
                        brain_notes.add_note(text, source=channel); actions.append("add_note")
                        content = say("note")
                return Reply(content, actions, via)
            # локальная модель решила, что вопрос общий → в облако (обезличенно)
            cloud = next((c for c in out["tool_calls"] if c["name"] == registry.CLOUD_TOOL), None)
            if cloud:
                q = (cloud["arguments"] or {}).get("question") or text
                r = await via_gemini(q, channel, explicit=False)
                if r:
                    r.actions = actions + ["ask_cloud"]
                    return r
                allow_cloud = False  # облако не ответило — продолжаем локально
                messages.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": registry.CLOUD_TOOL, "arguments": cloud["arguments"]}}]})
                messages.append({"role": "tool", "content": "Облако недоступно. Ответь сам, кратко."})
                continue
            messages.append({"role": "assistant", "content": out["content"], "tool_calls": [
                {"function": {"name": c["name"], "arguments": c["arguments"]}} for c in out["tool_calls"]]})
            for c in out["tool_calls"]:
                sig = (c["name"], json.dumps(c["arguments"] or {}, sort_keys=True, ensure_ascii=False))
                if sig in seen_calls and c["name"].startswith(("add_", "pay_", "transfer", "set_", "complete_", "delete_", "move_", "stop_")):
                    # модель повторила тот же вызов (частая привычка маленьких моделей). Если он прошёл — второй раз
                    # не записываем. Если провалился — повторять с теми же аргументами бессмысленно, но и говорить
                    # «уже выполнено» нельзя: модель поверит и отчитается об успехе, которого не было.
                    ok_before = seen_calls[sig]
                    log.info("[%s] повторный вызов %s пропущен (первый %s)", channel, c["name"], "прошёл" if ok_before else "провалился")
                    messages.append({"role": "tool", "content":
                                     "Уже выполнено выше — второй раз делать не нужно. Ответь пользователю." if ok_before else
                                     f"Тот же вызов {c['name']} с теми же аргументами уже не прошёл. Повтор ничего не изменит: "
                                     "либо измени аргументы, либо честно скажи пользователю, что не получилось."})
                    continue
                seen_calls[sig] = False
                if c["name"] in ("add_note", "add_event", "add_task") and (_looks_like_question(text) or _is_analysis(text)):
                    res = "Это вопрос, возражение или просьба разобраться, а не команда сохранить — НЕ сохранено. Ответь по существу; если нужны данные — вызови finance_summary / list_debts / agenda."
                    log.info("[%s] модель хотела записать вопрос в заметки — отклонено", channel)
                elif (big := _needs_confirm(c["name"], c["arguments"] or {})) is not None:
                    # крупная сумма — не пишем, а спрашиваем; «да» выполнит ровно этот вызов (см. _resolve_confirm)
                    try:
                        args_ok = registry.validate_args(c["name"], c["arguments"] or {})
                    except registry.ToolArgError as e:
                        messages.append({"role": "tool", "content": f"Инструмент {c['name']} не выполнен: {e}"})
                        continue
                    _pending_set(channel, "confirm|" + json.dumps({"name": c["name"], "args": args_ok}, ensure_ascii=False))
                    log.info("[%s] %s на %.0f — жду подтверждения", channel, c["name"], big)
                    # что уже успели сделать в этом ходу — сообщаем, чтобы не потерялось
                    return Reply("\n".join(done_results + [_confirm_question(c["name"], args_ok, big)]), actions + ["clarify"], via)
                elif registry.risk_of(c["name"]) == "destructive":
                    # удаление/остановка — только по «да». Раньше подтверждения требовали лишь крупные суммы,
                    # а «удали встречу» модель могла выполнить по своей трактовке фразы.
                    try:
                        args_ok = registry.validate_args(c["name"], c["arguments"] or {})
                    except registry.ToolArgError as e:
                        messages.append({"role": "tool", "content": f"Инструмент {c['name']} не выполнен: {e}"})
                        continue
                    _pending_set(channel, "confirm|" + json.dumps({"name": c["name"], "args": args_ok}, ensure_ascii=False))
                    log.info("[%s] %s — необратимое действие, жду подтверждения", channel, c["name"])
                    return Reply("\n".join(done_results + [_destructive_question(c["name"], args_ok)]), actions + ["clarify"], via)
                else:
                    tr = registry.call(c["name"], c["arguments"], channel)
                    results.append(tr)
                    seen_calls[sig] = tr.ok
                    res = tr.for_model()
                    if tr.ok:
                        actions.append(c["name"])
                        done_results.append(tr.text)
                    else:
                        log.warning("[%s] инструмент %s НЕ выполнен: %s", channel, tr.name, tr.error)
                messages.append({"role": "tool", "content": res})
        out = await _chat(messages)
        content = (await _russian_only(messages, out)) or ("Готово." if any(r.ok for r in results) else "Не получилось, сэр.")
        return Reply(_truth_gate(content, results), actions, via)
    except Exception as e:
        log.exception("%s failed: %s", "cloud tools" if cloud_tools else "ollama", e)
        if actions:
            # инструменты уже отработали (трата записана, событие создано), а модель упала на финальной фразе.
            # Вернуть None нельзя: handle() уйдёт в облако/скажет «недоступно», человек повторит команду — и получит дубль.
            return Reply("\n".join(done_results) or "Готово.", actions, via)
        return None


async def via_gemini(text: str, channel: str, explicit: bool = True) -> Reply | None:
    """Облако (Gemini / OpenRouter / Groq / DeepSeek… — что выбрано в настройках)."""
    if not llm.cloud_enabled():
        return None
    # кэш частых общих вопросов («что такое инфляция», «сколько будет 2+2») — не ждём облако второй раз за день
    ck = _cache_key(text, channel)
    hit = _ANSWER_CACHE.get(ck) if ck else None
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        log.info("[%s] ОБЛАКО: ответ из кэша", channel)
        return Reply(hit[1], [], "gemini")
    # историю передаём только при явном обращении (и она тоже проходит анонимайзер)
    voice_hint = " ОТВЕТ ГОЛОСОМ: максимум 1–2 коротких предложения, без списков, markdown и эмодзи." if channel.endswith("voice") else ""
    ans = await llm.cloud_chat(system_prompt() + voice_hint + await memory.context(text) + _no_repeat_block() + "\nТы ведёшь разговор и отвечаешь на общие вопросы. Личных данных пользователя (деньги, календарь, задачи, заметки, файлы) "
                               "у тебя нет — не проси их и не выдумывай (то, что выше в блоке «что ты знаешь о хозяине», — знаешь). Если для ответа НУЖНЫ его личные данные или надо что-то записать/изменить/показать из них — "
                               "ответь ровно одним словом: LOCAL (без пояснений). Во всех остальных случаях отвечай кратко, по-русски, в характере.",
                               text + "\n" + now_line(), _history(channel, 6, current=text) if explicit else None)
    if not ans:
        return None
    if LOCAL_MARK_RX.search(ans) or re.search(r"локальн\w+\s+(модул|модел|мозг)|без\s+обращения\s+к\s+облаку", ans, re.I):
        # облако само поняло, что вопрос личный → не показываем это пользователю, а молча идём в локальную модель
        log.info("[%s] ОБЛАКО: «это личное» → перекидываю в локальную модель", channel)
        return Reply("", [], "local_needed")
    if ck:
        _ANSWER_CACHE[ck] = (time.monotonic(), ans)
        if len(_ANSWER_CACHE) > 300:
            for k in sorted(_ANSWER_CACHE, key=lambda k: _ANSWER_CACHE[k][0])[:100]:
                _ANSWER_CACHE.pop(k, None)
    return Reply(ans, [], "gemini")


LOCAL_MARK_RX = re.compile(r"^\W*LOCAL\W*$", re.I)
_ANSWER_CACHE: dict[str, tuple[float, str]] = {}
CACHE_TTL = 24 * 3600
_CACHE_NO_RX = re.compile(r"\b(сейчас|сегодня|завтра|вчера|погод|курс|новост|который час|время|дата|случайн|придумай|сгенерируй|напиши|расскажи анекдот|шутк|"
                          r"подкинь|выбери|последн|актуальн|свеж)\w*", re.I)


def _cache_key(text: str, channel: str) -> str | None:
    """Кэшируем только «энциклопедические» вопросы: без времени, погоды, творчества и коротких реплик-разговора."""
    t = re.sub(r"\s+", " ", text.strip().lower().strip(" .?!"))
    if len(t) < 8 or len(t) > 200 or _CACHE_NO_RX.search(t):
        return None
    if not re.match(r"^(что такое|кто такой|кто такая|что значит|как переводится|сколько будет|сколько (в|км|грамм|калорий)|почему|чем отличается|как работает|"
                    r"в каком году|когда (был|была|было|родился|умер|появил)|столица|формула|переведи (слово|фразу)|как пишется|как по[- ]английски)", t):
        return None
    return ("v" if channel.endswith("voice") else "t") + ":" + t


def _mark(r: Reply) -> Reply:
    """Пометка источника ответа + обращение к хозяину как в настройках (owner.name)."""
    r.text = localize(r.text)
    if not llm.MARK_SOURCE:
        return r
    tag = {"gemini": "☁️", "ollama": "🧠", "rules": "⚡", "none": ""}.get(r.via, "")
    if tag and not r.text.rstrip().endswith(tag):
        r.text = r.text.rstrip() + f"  {tag}"
    return r


# хук «что-то изменилось» — его ставит API, чтобы сайт обновлялся после Telegram/голоса
on_change = None  # Callable[[str, dict], None] | None
notify = None     # async (text, buttons=None) — сообщение владельцу в Telegram (ставит run.py); None — без Telegram


def _changed(channel: str, actions: list[str]) -> None:
    if on_change and actions:
        try:
            on_change("chat", {"channel": channel, "actions": actions})
        except Exception:  # pragma: no cover
            pass


# --------------------------------------------------------------------------- вход
VOICE_RX = re.compile(r"^\s*(?:" + identity.NAME_RX_SRC + r"\W*)?(поменяй|смени|измени|другой|давай другой|переключи|выбери|поставь)?\s*голос(?![а-яё])\W*(?:на\s+)?([а-яёa-z0-9\- ]+)?\s*$", re.I)
_VOICE_NAMES = {"евгений": ("silero", "eugene"), "eugene": ("silero", "eugene"), "айдар": ("silero", "aidar"), "aidar": ("silero", "aidar"),
                "бая": ("silero", "baya"), "baya": ("silero", "baya"), "ксения": ("silero", "kseniya"), "kseniya": ("silero", "kseniya"),
                "ксения 2": ("silero", "xenia"), "ксения-2": ("silero", "xenia"), "xenia": ("silero", "xenia"),
                "дмитрий": ("edge", "ru-RU-DmitryNeural"), "светлана": ("edge", "ru-RU-SvetlanaNeural"),
                "мужской": ("silero", "eugene"), "женский": ("silero", "baya")}
_VOICE_ORDER = [("silero", "eugene"), ("silero", "aidar"), ("silero", "baya"), ("silero", "kseniya"), ("silero", "xenia"), ("edge", "ru-RU-DmitryNeural"), ("edge", "ru-RU-SvetlanaNeural")]
_VOICE_TITLE = {"eugene": "Евгений", "aidar": "Айдар", "baya": "Бая", "kseniya": "Ксения", "xenia": "Ксения-2", "ru-RU-DmitryNeural": "Дмитрий (Microsoft)", "ru-RU-SvetlanaNeural": "Светлана (Microsoft)"}


def _change_voice(name: str | None) -> str:
    from ..voice import tts
    from ..config import write_settings
    cur = (tts.ENGINE, tts.SPEAKER if tts.ENGINE == "silero" else tts.EDGE_VOICE)
    if name and name.strip().lower() in _VOICE_NAMES:
        eng, vid = _VOICE_NAMES[name.strip().lower()]
    elif name and name.strip() and name.strip().lower() not in ("другой", "следующий", "новый", "ещё", "еще"):
        return "Такого голоса нет, сэр. Есть: Евгений, Айдар, Бая, Ксения, Ксения-2, Дмитрий, Светлана. Скажите «поменяй голос» — переключу на следующий."
    else:
        i = _VOICE_ORDER.index(cur) if cur in _VOICE_ORDER else -1
        eng, vid = _VOICE_ORDER[(i + 1) % len(_VOICE_ORDER)]
    tts.ENGINE = eng
    changes = {"voice.tts.engine": eng}
    if eng == "silero":
        tts.SPEAKER = vid; changes["voice.tts.speaker"] = vid
    else:
        tts.EDGE_VOICE = vid; changes["voice.tts.edge_voice"] = vid
    try:
        write_settings(changes)
    except Exception as e:
        log.debug("save voice: %s", e)
    return f"Теперь говорю голосом «{_VOICE_TITLE[vid]}», сэр. Не нравится — «поменяй голос» ещё раз или выберите в настройках."


# журнал работы: «как ты работал», «отчёт о себе», «где ты ошибался», «где ты тупил»
SELFREPORT_RX = re.compile(r"^\s*(?:[а-яё]+,\s*)?(?:как\s+ты\s+(?:работал\w*|справля\w*|себя\s+вёл)|"
                           r"отч[её]т\s+о\s+(?:себе|работе|своей\s+работе)|сам\w*\s+отч[её]т|"
                           r"где\s+ты\s+(?:ошиб\w*|тупил\w*|косячил\w*|подвёл|облажал\w*)|"
                           r"журнал\s+работы|тво[яи]\s+статистик\w*|как\s+часто\s+ты\s+ошиб\w*)"
                           r"(?:\s+(?:за\s+)?(?:сегодня|вчера|день|неделю|месяц|эту\s+неделю|этот\s+месяц|последн\w+\s+[а-яё]+))?\s*[?.!]*\s*$", re.I)

GAME_ON_RX = re.compile(r"^(игров(ой|ый) режим|иду играть|пошёл играть|пошел играть|играю|game mode|игра)\W*(вкл\w*|on)?\W*$", re.I)
GAME_OFF_RX = re.compile(r"^(игра окончена|наигрался|отыграл|поиграл|конец игры|игров(ой|ый) режим (выкл\w*|off)|game over|game mode off)\W*$", re.I)


WAKE_RX = identity.WAKE_RX
_SPOKEN_MARK_RX = re.compile(r"^\s*(задача|таск|мысль|идея|заметка|запиши|напомни|событие|встреча|мозг)\s*,\s*", re.I)


def normalize_spoken(text: str) -> str:
    """Распознанная речь → текст как если бы напечатали: убрать «<имя>,», «задача, …» → «задача: …»,
    финальную точку/вопрос (Whisper их ставит, а правила ждут чистую фразу)."""
    t = WAKE_RX.sub("", text).strip()
    if not t:
        t = text.strip()
    t = _SPOKEN_MARK_RX.sub(lambda m: m.group(1) + ": ", t)
    t = re.sub(r"[.!]+$", "", t).strip()
    return t or text


_MONEY_MARK_RX = re.compile(r"\d\s*(?:к|k|тыс|руб|р\.?(?:\s|$)|₽|\$|€)", re.I)


def _money_like(body: str) -> bool:
    """«300к», «50 000 руб», «1500» — деньги (конверт goals); «5 кг», «10 клиентов» — нет (это цель aims)."""
    amount, _ = parse_amount(body)
    if not amount:
        return False
    return bool(_MONEY_MARK_RX.search(body)) or amount >= 1000


STOP_JOB_RX = re.compile(r"^\s*(?:стоп|останови(?:сь)?|хватит|прекрати|отмени\s+(?:это|работу|фон\w*))\s*[.!]?\s*$", re.I)
WHATS_UP_RX = re.compile(r"^\s*(?:что\s+(?:сейчас\s+)?(?:происходит|делаешь)|чем\s+(?:ты\s+)?занят\w*|ты\s+(?:тут|здесь|живой|на месте)|статус)\s*\??\s*$", re.I)


async def _presence_rules(text: str, channel: str) -> Reply | None:
    """Правила 0.10: цели (aims), решения, лента, самопроверка, стоп фоновой работы, «что происходит».
    Всё без модели — это команды к своим данным, а не разговор."""
    from ..services import aims, decisions, health, state, timeline
    t = text.strip()
    # --- цели --- («цель: подушка 300к к марту» с суммой — это денежный конверт, его берёт GOAL_RX ниже по цепочке)
    ma = aims.AIM_RX.match(t)
    if ma and _money_like(ma.group(2)):
        return None
    m = aims.AIM_CLOSE_RX.match(t)
    if m:
        name = (m.group(1) or m.group(3) or "").strip()
        aim = aims.find_aim(name)
        if not aim:
            return Reply(f"Цели «{name}» не нашёл. «Мои цели» — покажу, какие есть.", [], "rules")
        drop = bool(m.group(1)) and m.group(2).lower() in ("отбой", "отменяется", "больше не актуальна") or bool(m.group(3)) and re.match(r"^\s*(убери|отмени)", t, re.I)
        aims.close_aim(aim, "dropped" if drop else "done")
        return Reply((f"Цель «{aim.title}» снята. Без драмы — не всё, что начал, надо дожимать." if drop else f"Цель «{aim.title}» закрыта. Это не задача из списка — это то, ради чего список был."), ["close_aim"], "rules")
    m = re.match(r"^\s*цель\s+[«\"]?(.+?)[»\"]?\s+(?:активна|снова в работе|возобновляется|продолжаем)\s*[.!]?\s*$", t, re.I)
    if m:
        aim = aims.find_aim(m.group(1), any_status=True)
        if aim:
            aims.update_aim(aim.id, status="active")
            return Reply(f"«{aim.title}» снова в работе.", ["reopen_aim"], "rules")
    a = aims.detect_aim_phrase(t)
    if a:
        existing = aims.find_aim(a["title"])
        if existing and existing.title.lower() == a["title"].lower():
            return Reply(f"Такая цель уже есть: «{existing.title}» ({int(aims.progress(existing) * 100)}%).", [], "rules")
        aim = aims.add_aim(a["title"], why=a["why"], due=a["due"], source=channel)
        tail = f", к {aim.due:%d.%m.%Y}" if aim.due else ""
        why = "" if aim.why else " Зачем она тебе — скажи, запишу: через месяц это единственное, что удержит."
        return Reply(f"Цель поставлена: «{aim.title}»{tail}. Теперь «веха: …» — первый ощутимый рубеж, а задачи к ней я подтяну сам.{why}", ["add_aim"], "rules")
    m = aims.MS_RX.match(t)
    if m and not _is_analysis(t):
        title, aim_q = m.group(1).strip(" .«»\""), (m.group(2) or "").strip()
        aim = aims.find_aim(aim_q) if aim_q else None
        if aim is None:
            active = aims.list_aims()
            if len(active) == 1:
                aim = aims.find_aim(active[0]["id"])
            elif not active:
                return Reply("Вех без цели не бывает. Сначала «цель: …».", [], "rules")
            else:
                return Reply("К какой цели? " + "; ".join(f"«{x['title']}»" for x in active[:4]) + ". Скажи «веха: … к цели <название>».", [], "rules")
        ms = aims.add_milestone(aim, title)
        return Reply(f"Веха «{ms.title}» — в цели «{aim.title}». Задачи к ней: «задача: … к вехе {ms.title[:20]}» или просто закрывай дела — я сам спрошу, если похоже.", ["add_milestone"], "rules")
    if aims.FOCUS_RX.match(t):
        return Reply(aims.text_focus(), ["focus"], "rules")
    if aims.AIMS_RX.match(t):
        # «цели» — и долгосрочные (aims), и денежные конверты (goals) одним ответом: человек не обязан помнить разницу
        from ..services import goals as _goals
        parts, acts = [], ["aims"]
        if aims.list_aims():
            parts.append(aims.text_aims())
        if _goals.list_goals():
            parts.append(_goals.goals_text()); acts.append("list_goals")
        if not parts:
            parts.append(aims.text_aims())
        return Reply("\n\n".join(parts), acts, "rules")
    m = aims.BLOCK_RX.match(t)
    if m and len(m.group(2).strip()) >= 3 and not _is_analysis(t):
        tk = tasks.find_task(m.group(1).strip())
        if tk:
            aims.set_blocked(tk.id, m.group(2).strip())
            return Reply(f"«{tk.title}» — стоит: {m.group(2).strip()}. Из фокуса убрал, в «мешает» добавил. Скажи «разблокирована», когда сдвинется.", ["block_task"], "rules")
    m = re.match(r"^\s*(?:задача\s+)?[«\"]?(.+?)[»\"]?\s+(?:разблокирован\w*|сдвинулась|пошла|больше не стоит)\s*[.!]?\s*$", t, re.I)
    if m:
        tk = tasks.find_task(m.group(1).strip())
        if tk and tk.blocked_by:
            aims.set_blocked(tk.id, "")
            return Reply(f"«{tk.title}» снова в работе.", ["unblock_task"], "rules")
    # --- рутины ---
    from ..services import routines
    rt = routines.chat_rule(t)
    if rt:
        return Reply(rt, ["routines"], "rules")
    # --- доски: «доска: …», «раскадровка: … на 8 кадров», «на доску: мысль», «что по доске …» ---
    if not _is_analysis(t):
        from ..services import boards
        try:
            br = boards.chat_rule(t, channel)
        except ValueError as e:
            return Reply(str(e), [], "rules")
        if br:
            return Reply(br[0], br[1], "rules")
    # --- решения ---
    d = decisions.chat_rule(t, channel)
    if d:
        return Reply(d, ["decision"], "rules")
    # --- лента ---
    tl = timeline.chat_rule(t)
    if tl:
        return Reply(tl, ["timeline"], "rules")
    # --- самопроверка ---
    if health.SELF_RX.match(t):
        res = await health.diagnose()
        health.record(res)
        return Reply(res["text"], ["diagnose"], "rules")
    # --- фоновые работы ---
    if STOP_JOB_RX.match(t):
        job = state.running_job()
        if job:
            state.job_fail(job["name"], "остановлено по команде")
            return Reply(f"Остановил «{job['name']}».", ["stop_job"], "rules")
        return None   # обычный «стоп» (например, голосу) — дальше по цепочке
    if WHATS_UP_RX.match(t):
        sn = state.snapshot()
        parts = []
        line = state.line()
        if line:
            parts.append(line)
        if sn["jobs"]:
            parts.append("Фон: " + ", ".join(f"{j['name']} {int((j['progress'] or 0) * 100)}%" for j in sn["jobs"]))
        if sn["pending"]:
            parts.append("Жду ответа: " + sn["pending"])
        from . import attention
        left = attention.budget_left()
        parts.append(f"Инициатив на сегодня осталось {left}" + (f", отложено {attention.queue_size()}" if attention.queue_size() else "") + ".")
        return Reply(" ".join(parts) if parts else "Тихо. ПК не на связи, фоновых работ нет, жду.", ["state"], "rules")
    return None


async def handle(text: str, channel: str = "tg") -> Reply:
    """Единственный вход для всех каналов. Никогда не бросает исключений: любая ошибка → понятная реплика + лог."""
    text = (text or "").strip()
    if not text:
        return Reply("Я вас слушаю, сэр.")
    if len(text) > 8000:
        text = text[:8000]
    trace.start(text, channel)   # журнал работы: строка в базе на каждый ход (services/trace.py)
    try:
        r = await _handle(text, channel)
        trace.finish(r.via, r.actions, ok=r.via != "none")
        return r
    except Exception as e:  # noqa: BLE001 — последний рубеж: каналы (TG/сайт/голос) не должны падать из-за одной фразы
        log.exception("handle(%s) failed: %s", channel, e)
        trace.finish("none", [], ok=False, error=f"{type(e).__name__}: {e}")
        r = Reply("Что-то пошло не так на моей стороне, сэр. Ничего не записал — попробуйте ещё раз или загляните в лог.", [], "none")
        _log_chat("assistant", r.text, channel)
        return r


async def _handle(text: str, channel: str) -> Reply:
    llm.mark_user_active()   # фоновые задачи на локальной модели (уборка заметок, связи) уступают дорогу
    try:
        from ..services import state as _state
        _state.mark_conversation()
    except Exception:  # pragma: no cover
        pass
    # голос: короткие ответы (1–2 фразы), меньше токенов — быстрее генерация и озвучка
    llm.short_mode.set(channel.endswith("voice"))
    if channel.endswith("voice") or WAKE_RX.match(text):
        text = normalize_spoken(text)
    _log_chat("user", text, channel)

    # «облако сброс» / «проверь облако» — перечитать ключ/модель, сбросить кэш и сделать живой запрос
    if re.match(r"^\s*(облако\W*(сброс|проверь|проверка|статус|тест)|(проверь|сбрось|перезапусти)\W*облако)\W*$", text, re.I):
        info = llm.reload_cloud_settings()
        res = await llm.cloud_check()
        r = Reply((f"☁️ {info}\n" + (f"Отвечает ✅ ({res.get('model')})" if res.get("ok") else f"Не отвечает ❌\n{res.get('detail')}")), [], "none")
        _log_chat("assistant", r.text, channel)
        return r

    # «проверь характер» — пять сценариев через облако/ПК, чтобы подкрутить тон, не дожидаясь настоящего повода
    if persona.CHARACTER_CHECK_RX.match(text):
        r = Reply(await persona.character_check(), ["character_check"], "rules")
        _log_chat("assistant", r.text, channel)
        return r

    # «как ты работал», «отчёт о себе», «где ты ошибался» — журнал работы словами (services/trace.py)
    ms = SELFREPORT_RX.match(text)
    if ms:
        days = 30 if re.search(r"месяц", text, re.I) else 1 if re.search(r"сегодня|за день", text, re.I) else 7
        txt = trace.report_text(days)
        r = Reply(txt or f"За {days} дн. обращений ко мне не было, сэр — докладывать не о чем.", ["self_report"], "rules")
        _log_chat("assistant", r.text, channel)
        return r

    # смена голоса: «поменяй голос», «другой голос», «голос ксения»
    mv = VOICE_RX.match(text)
    if mv:
        r = Reply(_change_voice(mv.group(2)), ["voice"], "rules")
        _log_chat("assistant", r.text, channel)
        return r

    # присутствие/цели/решения/лента/самопроверка (0.10) — правила без модели
    r = await _presence_rules(text, channel)
    if r is not None:
        _log_chat("assistant", r.text, channel)
        _changed(channel, r.actions)
        return r

    # игровой режим: выгрузить модель из видеопамяти, отвечать через облако
    if GAME_ON_RX.match(text) or GAME_OFF_RX.match(text):
        r = Reply(await llm.set_game_mode(bool(GAME_ON_RX.match(text))), ["game_mode"], "rules")
        _log_chat("assistant", r.text, channel)
        return r

    # ссылки
    urls = brain_notes.extract_urls(text)
    if urls:
        comment = text
        for u in urls:
            comment = comment.replace(u, "")
        comment = comment.strip(" -—:,") or None
        saved = []
        for u in urls:
            saved.append(await brain_notes.add_link(u, comment, source=channel))
        count = len(brain_notes.list_links(10_000))
        r = Reply(say("link", title=saved[0].title or saved[0].domain, count=count), ["add_link"])
        _log_chat("assistant", r.text, channel)
        _changed(channel, r.actions)
        return r

    # явное обращение к облаку: «гемини, объясни …»
    m = CLOUD_RX.match(text)
    if m and text[m.end():].strip():
        q = text[m.end():].strip()
        if not llm.cloud_enabled():
            r = Reply("Облако выключено, сэр: выберите провайдера и вставьте ключ в Настройки → облако (или brain.mode = local).", [], "none")
        else:
            r = await via_gemini(q, channel, explicit=True) or Reply(llm.LAST_CLOUD_ERROR or f"{llm.cloud_title()} не ответил. Причина неизвестна — смотрите лог.", [], "none")
            if r.via == "local_needed":
                r = (await via_ollama(q, channel)) or Reply("Это про ваши данные, сэр — облаку их не даю, а локальный мозг сейчас не отвечает.", [], "none")
        _log_chat("assistant", r.text, channel)
        return _mark(r)

    # явно «локально, …» — минуя облако
    force_local = False
    m = LOCAL_RX.match(text)
    if m and text[m.end():].strip():
        text, force_local = text[m.end():].strip(), True

    try:
        r = await _resolve_sorter_draft(text, channel)
        if r is None:
            r = _resolve_bulk(text, channel)
        if r is None:
            r = _resolve_confirm(text, channel)
        if r is None:
            r = _resolve_pending(text, channel)
        if r is None:
            r = _bulk_rule(text, channel)
        if r is None and not force_local and sorter.looks_like_batch(text):
            # список из нескольких дел/записей: сначала нейронка раскладывает по типам (JSON), потом каждая запись — своим
            # сервисом. Иначе шаблон схватит первое время («в 15:00») как одно событие, а модель с инструментами
            # положит весь список одной заметкой.
            t0 = time.monotonic()
            log.info("[%s] СПИСОК → сортировщик: %r", channel, text[:60])
            r = await sorter.sort(text, channel, CONFIRM_AMOUNT)
            log.info("[%s] сортировщик %s за %.1f с", channel, "разобрал" if r else "не справился — обычный путь", time.monotonic() - t0)
            if r is None and sorter.HARD_SPLIT_RX.search(text) and not llm.cloud_enabled() and not await llm.ollama_available():
                # многострочный список, а разбирать некому — честно сказать, а не хватать первое время как одно событие
                r = Reply("Вижу список из нескольких пунктов, но сейчас нет ни локальной модели, ни облака, чтобы его разобрать. "
                          "Включите Ollama или ключ облака в настройках — или пришлите пункты по одному.", [], "rules")
        if r is None and not force_local:
            r = await _judge_disputed(text, channel)
        if r is None:
            r = rules(text, channel)
    except finance.FinanceError as e:
        # «потратил 0 на кофе», «баланс -abc»: ошибка ввода — это ответ, а не падение (раньше веб получал 500, TG — «ошибка»)
        r = Reply(f"Не записал: {e}", [], "rules")
    # Разговор и общие вопросы («привет, как дела», «что такое инфляция», «напиши поздравление») → облако.
    # Всё личное (деньги, календарь, задачи, заметки, файлы, даты) → локальная модель с инструментами.
    cloud_tried = False
    t0 = time.monotonic()
    if r is not None:
        log.info("[%s] ПРАВИЛО → %s", channel, r.actions or "ответ")
    # В режиме cloud с инструментами не гадаем «личное/общее»: всё, кроме явной болтовни, идёт одним путём — облако + инструменты
    # (модель сама решит, звать ли search_notes). Так «где лежит паспорт?» найдётся в памяти, а не получит общий ответ.
    cloud_direct = _cloud_tools_mode() and not SMALLTALK_RX.match(text)
    if r is None and not force_local and not cloud_direct and llm.cloud_enabled() and llm.GEMINI_AUTO and not is_personal(text):
        cloud_tried = True
        log.info("[%s] ОБЛАКО: общий вопрос → %s: %r", channel, llm.cloud_title(), text[:60])
        r = await via_gemini(text, channel, explicit=True)
        log.info("[%s] ОБЛАКО: %s %s за %.1f с", channel, llm.cloud_title(), "ответил" if r else f"НЕ ответил ({llm.LAST_CLOUD_ERROR})", time.monotonic() - t0)
        if r is not None and r.via == "local_needed":
            r, cloud_tried = None, False   # облако отказалось: вопрос личный → локальная модель с инструментами
    if r is None:
        t1 = time.monotonic()
        who = f"ОБЛАКО+инструменты: {llm.cloud_title()}" if _cloud_tools_mode() else f"ЛОКАЛЬНО: Ollama ({llm.OLLAMA_MODEL})"
        log.info("[%s] %s: %r", channel, who, text[:60])
        r = await via_ollama(text, channel, with_tools=not cloud_tried)
        log.info("[%s] %s %s за %.1f с", channel, who, "ответил" if r else "недоступен", time.monotonic() - t1)
    if r is None:
        # моделей нет (Ollama спит после игры/сна ПК), а вопрос — о своих данных: инструмент отвечает и без модели
        forced = _forced_tool(text)
        if forced:
            tr = registry.call(forced[0], forced[1], channel)
            if tr.ok:
                log.info("[%s] модели недоступны → инструмент %s напрямую", channel, forced[0])
                r = Reply(tr.text, [forced[0]], "rules")
    if r is None and not cloud_tried and llm.cloud_enabled():
        cloud_tried = True
        log.info("[%s] ОБЛАКО: запасной путь → %s", channel, llm.cloud_title())
        r = await via_gemini(text, channel, explicit=True)   # запасной путь: Ollama лежит
        if r is not None and r.via == "local_needed":
            # облако честно сказало «это личное», а локальная только что не ответила — раньше тут уходило пустое «…»
            log.info("[%s] облако отказалось (личное), локальная недоступна — говорю прямо", channel)
            why = await llm.ollama_diagnose() if not llm.GAME_MODE else "игровой режим"
            r = Reply(f"Это про ваши данные — облаку их не даю, а локальный мозг сейчас не отвечает ({why[:120]}). "
                      "Ничего не записал. Повторите через минуту — или скажите шаблоном: «задача: …», «встреча … в …», «что сегодня».", [], "none")
    if r is None and llm.GAME_MODE:
        r = Reply("Игровой режим, сэр: локальный мозг спит, а это личный вопрос — он для локального. "
                  "Команды-шаблоны («потратил 700 на такси», «задача: …») работают; остальное — после «игра окончена».", [], "none")
    if r is None:
        if (cloud_tried or _cloud_tools_mode()) and llm.LAST_CLOUD_ERROR:
            r = Reply(f"Облако не ответило: {llm.LAST_CLOUD_ERROR}", [], "none")
        else:
            r = Reply("Локальный мозг (Ollama) не запущен, а облако выключено. Без него я понимаю команды: «потратил 700 на такси», "
                      "«встреча в среду в 15:00», «что завтра», «сколько потратил на еду за неделю», «заплатил Ване 2000», "
                      "«задача: …», «мысль: …» — а вот свободный разговор подождёт, сэр.", [], "none")
    # триггер «карточки людей»: в реплике всплыл известный человек → строка контекста (неоплата, долг, встреча).
    # Не для голоса (лишние слова) и не для ответов, где карточка уже показана.
    if r.via != "none" and not channel.endswith("voice") and "person_card" not in r.actions and "add_person" not in r.actions:
        hint = people_hint(text, r.text)
        if hint:
            r.text = r.text.rstrip() + "\n\n" + hint
    _log_chat("assistant", r.text, channel)
    _changed(channel, r.actions)
    _extract_memory_bg(text, r.actions, channel)
    if r.via in ("gemini", "ollama"):
        persona.remember_images(r.text)   # чтобы кот из памяти не всплывал в каждом ответе — общий список с проактивными
    return _mark(r)


async def _judge_disputed(text: str, channel: str) -> Reply | None:
    """Спорная фраза («сайт 15000») → урок или судья решают тип до того, как шаблон схватит её как трату.
    Судья не уверен — один вопрос с вариантами. Судьи нет (ни модели, ни облака) — поведение как раньше (шаблон)."""
    options = _disputed(text)
    if not options:
        return None
    kind, via = await judge.decide(text, options)
    if kind is None:
        if via == "none":
            return None   # судья выключен или решать некому — шаблон работает, как до судьи
        log.info("[%s] СУДЬЯ не уверен (%s) → спрашиваю: %r", channel, via, text[:60])
        return _judge_question(text.strip(), channel, options)
    log.info("[%s] СУДЬЯ (%s) → %s: %r", channel, via, kind, text[:60])
    try:
        r = _write_as(kind, text, channel)
    except finance.FinanceError as e:
        return Reply(f"Не записал: {e}", [], "rules")
    if r is None:
        return None
    if via != "lesson":
        r.text += f" (Понял как {judge.KIND_RU[kind].split()[0]} — если не то, скажите «это заказ» или «это трата».)"
    r.actions = r.actions + ["judge"]
    return r


def _extract_memory_bg(text: str, actions: list[str], channel: str = "tg") -> None:
    """Память учится из реплики в фоне — ответ пользователю не ждёт нейронку."""
    if not memory.enabled() or not memory.worth_extracting(text, actions):
        return
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    async def run():
        try:
            res = await memory.extract(text)
            if res.get("added") or res.get("updated"):
                _changed("memory", ["memory"])
            rm = res.get("remind")
            if rm:
                # предложил сам — говорим об этом отдельным сообщением, откат одним словом
                msg = f"Кстати, поставил напомнить: «{rm['title']}»" + (f" — {fmt_dt(rm['due'])}" if rm.get("due") else ", срок не понял — скажете") + ". Лишнее — «отмени»."
                _log_chat("assistant", msg, channel)
                _changed(channel, ["add_task"])
                if notify and channel.startswith("tg"):
                    await notify(msg)
                elif on_change:
                    on_change("reminder", {"text": msg, "id": f"suggest-{rm['id']}"})
        except Exception as e:  # pragma: no cover
            log.warning("memory extract: %s", e)
    loop.create_task(run())
