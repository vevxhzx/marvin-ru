# -*- coding: utf-8 -*-
"""Обучение английскому: встроенный корпус по направлениям + «абзац дня» + прогресс.

Зачем: практический английский для монтажёров и техдокументации (timeline, cut, keyframe, proxy,
codec, LUT, waveform, render, ingest, A-roll/B-roll, deliverables) плюс общий уровень A2–B1 и
свои тексты. Каждый день — один абзац с переводом и ключевыми словами с транскрипцией.

Направления (переключаются в настройках, запоминаются):
    video    — техдокументация для монтажёров (по умолчанию)
    general  — общий английский (A2–B1)
    custom   — свои тексты пользователя (+ перевод)

Всё состояние — ТОЛЬКО в settings KV (`core.db.get_setting/set_setting`), новых таблиц и
миграций НЕТ:
    english.track          — выбранное направление (video|general|custom)
    english.llm            — "1"/"0": генерировать абзац нейросетью (по умолчанию ВЫКЛ)
    english:progress       — JSON: {"days": {"ГГГГ-ММ-ДД": {"track":…, "title":…, "at":…}}, "by_track": …}
    english:custom         — JSON-список своих текстов: [{"text_en","text_ru","note","at"}], лимит 200
    english:llm_cache      — JSON: {"ГГГГ-ММ-ДД|track": {…}} — кэш абзаца дня от LLM

Выбор абзаца ДЕТЕРМИНИРОВАННЫЙ по дате: `(номер дня от эпохи + crc32(направление)) % len(corpus)`
(см. `pick_index`). В течение дня абзац не меняется, каждый день — новый, и переключение
направления тоже даёт свой абзац, но всё равно детерминированно.

Поведение по умолчанию НЕ меняется: `english.llm` выключен — абзац всегда из встроенного
корпуса, сеть не нужна. Если флаг включён, но модель недоступна/ответила мусором — тихо
отдаём встроенный корпус (без ошибки в API), в ответе честно `source: "builtin"`.
"""
from __future__ import annotations

import json as _json
import logging
import re as _re
import zlib
from datetime import date as _date, datetime, timedelta

from ..db import get_setting, set_setting

log = logging.getLogger("jarvis.learn_en")

TRACKS: dict[str, str] = {
    "video": "Техдокументация для монтажёров",
    "general": "Общий английский (A2–B1)",
    "custom": "Свои тексты",
}
DEFAULT_TRACK = "video"
CUSTOM_LIMIT = 200          # больше 200 своих текстов не храним — база не должна расти без границ
_CUSTOM_MAX_LEN = 4000      # обрезка одного текста

K_TRACK = "english.track"
K_LLM = "english.llm"
K_PROGRESS = "english:progress"
K_CUSTOM = "english:custom"
K_CACHE = "english:llm_cache"


# ------------------------------------------------------------------ встроенный корпус
# Формат: ("тема", "английский текст", "перевод", [(слово, транскрипция, пояснение), …])
_CORPUS_VIDEO: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    ("timeline", (
        "Before you touch the cut, build the timeline. A rough assembly is fine — the goal is to see the whole story. "
        "Lock the A-roll first, then cut around it, because the interview drives the structure of everything else. "
        "Turn snapping off, so your clips stay where you put them."
    ), (
        "Прежде чем браться за склейку, соберите таймлайн. Черновой монтаж — тоже монтаж: задача увидеть всю историю целиком. "
        "Сначала закрепите A-roll (основной кадр), потом режьте вокруг него — интервью задаёт структуру всего остального. "
        "Выключите привязку (snapping), иначе клипы будут примагничиваться к соседним."
    ), [
        ("assembly", "əˈsembli", "черновой монтаж: нарезка без финальной работы над звуком и цветом"),
        ("A-roll", "ei rol", "основной кадр — то, что снято «в кадр», без перебивок"),
        ("B-roll", "biː rol", "перебивка: кадры-вставки поверх основного (складают звук, реакции, детали)"),
        ("cut around", "kʌt əˈraʊnd", "резать вокруг чего-то: подгонять монтаж по опорному фрагменту"),
        ("snapping", "ˈsnæpɪŋ", "автопривязка: клипы сами «прилипают» к краям соседних"),
    ]),
    ("color pipeline", (
        "Shoot flat and grade later. A log profile keeps the highlights from clipping, so you have real room to correct. "
        "Build a LUT for the look, but check it on a calibrated screen — a LUT that looks right on a laptop can be wrong everywhere else."
    ), (
        "Снимайте в flat-профиле и делайте грейд позже. Log-профиль не «выжигает» света в светах, и остаётся запас для коррекции. "
        "Соберите LUT под нужный вид, но проверяйте его на калиброванном экране: LUT, который «красиво» смотрится на ноутбуке, "
        "на другом мониторе уедет."
    ), [
        ("flat profile", "flæt ˈprəʊfаɪl", "профиль камеры «без обработки» — максимум запаса в тенях и светах"),
        ("clipping", "ˈklɪpɪŋ", "срез: значения выше максимума, детали в светах потеряны безвозвратно"),
        ("grade", "ɡreɪd", "грейд — цветокоррекция по всему кадру (look, contrast, skin tones)"),
        ("calibrated", "ˈkælɪbreɪtɪd", "откалиброванный: экран с верной яркостью и цветом"),
    ]),
    ("sound sync", (
        "Sync the external track first, because a cut made against a bad reference will not survive the mix. "
        "Normalize the loudness, then set the music around -18 LUFS so the dialogue always stays on top of it."
    ), (
        "Сначала синхронизируйте внешнюю дорожку: склейка, сделанная под плохой референс, не выдержит сведения. "
        "Выровняйте громкость, а затем подложите музыку так, чтобы диалог оставался поверх неё, и не поднимайте музыку выше примерно -18 LUFS."
    ), [
        ("sync", "sɪŋk", "синхронизировать звук с картинкой по вспышке, клип-аппарату или коду камеры"),
        ("reference", "ˈrefrəns", "референс — дорожка, на которую держится монтаж по времени"),
        ("normalize", "ˈnɔːməlaɪz", "нормализовать громкость: привести все клипы к одному уровню"),
        ("mix", "mɪks", "сведение: итоговый баланс голоса, музыки и эффектов"),
    ]),
    ("codecs and proxies", (
        "Work with proxies while editing: they are small, they decode fast, and your laptop stays cool. "
        "Render the final in a high bitrate codec, and check that the client can actually play it before you deliver."
    ), (
        "Монтируйте на прокси: они маленькие, декодируются быстро, и ноутбук не перегревается. "
        "Финал рендерите в кодеке с высоким битрейтом и перед сдачей убедитесь, что клиент вообще может его воспроизвести."
    ), [
        ("proxy", "ˈprɒksi", "лёгкая копия файла для монтажа вместо тяжёлого оригинала"),
        ("decode", "diːˈkəʊd", "декодировать: превращать сжатый видеопоток в кадры для просмотра и монтажа"),
        ("bitrate", "ˈbɪtreɪt", "битрейт: сколько данных в секунду отдаёт кодек — выше значит качественнее и тяжелее"),
        ("deliver", "dɪˈlɪvə", "сдать/передать заказ клиенту"),
    ]),
    ("keyframes and animation", (
        "A keyframe tells the software where a value is at a moment; between two keyframes it calculates everything in between. "
        "Ease in and ease out on your keyframes — straight linear motion looks robotic and nobody believes it."
    ), (
        "Ключевой кадр говорит программе, какое значение параметра в этот момент; между двумя ключевыми кадрами она сама считает промежуточные. "
        "Добавьте на ключевые кадры плавное ускорение и замедление — линейное движение выглядит механическим и в это никто не поверит."
    ), [
        ("keyframe", "ˈkiːfreɪm", "ключевой кадр: точка, где задан параметр (масштаб, прозрачность, позиция)"),
        ("in between", "ɪn bɪˈtwiːn", "промежуточные значения, которые программа сама достраивает между ключами"),
        ("ease in / ease out", "iːz ɪn", "плавное начало и замедление в конце движения"),
        ("linear motion", "ˈlɪniə", "равномерное, «механическое» движение без ускорений"),
    ]),
    ("review and feedback", (
        "Export a rough cut before the client sees the final. Notes on the timeline are better than notes in an email: "
        "write the frame, not the paragraph. Then export a new version instead of overwriting the old one."
    ), (
        "Отдайте клиенту черновой монтаж до финала. Правки на таймлайне понятнее, чем правки в письме: "
        "пишите привязку к кадру, а не абзац. И выгружайте новую версию, а не перезаписывайте старую."
    ), [
        ("rough cut", "rʌf kʌt", "черновой монтаж — рабочая версия для обсуждения"),
        ("frame", "freɪm", "кадр (или его таймкод) — точная ссылка на место правки"),
        ("overwrite", "ˌəʊvəˈraɪt", "перезаписать файл, потеряв прежнюю версию"),
        ("version", "ˈvɜːʃn", "версия: отдельный файл каждой итерации"),
    ]),
    ("waveform and levels", (
        "Read the waveform before you move the clip: white peaks mean loud, flat black means silence. "
        "Keep dialogue above -6 dBFS on peaks, otherwise clients will call it quiet even when it is technically fine."
    ), (
        "Прочитайте форму волны, прежде чем двигать клип: белые пики — громко, ровная чёрная полоса — тишина. "
        "Держите пики речи выше -6 dBFS, иначе клиент назовёт запись тихой, даже если формально всё в норме."
    ), [
        ("waveform", "ˈweɪvfɔːm", "форма волны: график громкости звука во времени"),
        ("peak", "piːk", "пик — самая громкая точка сигнала (не средний уровень)"),
        ("loudness", "ˈlaʊdnəs", "громкость; в монтаже важнее воспринимаемая, чем пиковая"),
        ("dBFS", "dibi ef es", "децибелы полной шкалы: 0 dBFS — предел, выше клиппируется"),
    ]),
    ("ingest and media management", (
        "Ingest copies everything into your project folder first, then relink to the camera originals. "
        "Name your bins and folders by client and date — a project you cannot find is a project you cannot finish."
    ), (
        "Сначала залейте (импортируйте) всё в папку проекта, а потом перелинкуйте на оригиналы с камеры. "
        "Называйте папки и бины по клиенту и дате — проект, который не найти, это проект, который не закончить."
    ), [
        ("ingest", "ˈɪndʒest", "импорт исходников в проект — первый шаг сборки материала"),
        ("relink", "riːˈlɪŋk", "перепривязать файлы к оригиналам, когда монтируете на прокси"),
        ("bin", "bɪn", "контейнер/папка с клипами внутри программы монтажа"),
        ("original", "əˈrɪdʒɪnl", "оригинал — исходный файл камеры, а не копия в проекте"),
    ]),
    ("LUTs and looks", (
        "A LUT is a table of colours: it maps one colour to another and applies instantly. "
        "Mix it with your grade instead of stacking it at full strength — two heavy corrections fight each other."
    ), (
        "LUT — это таблица цветов: она сопоставляет один цвет другому и применяется мгновенно. "
        "Смешивайте её с грейдом, а не кладите в полную силу — две тяжёлые коррекции спорят друг с другом."
    ), [
        ("LUT", "lʌt", "таблица цветов: быстрый «фирменный вид», но без гибкости грейда"),
        ("map", "mæp", "сопоставлять: переводить одно значение в другое по таблице"),
        ("stack", "stæk", "накладывать несколько эффектов/коррекций друг на друга"),
        ("full strength", "ˌfʊl ˈstreŋθ", "в полную силу, на 100 %"),
    ]),
    ("exports and deliverables", (
        "Ask for the delivery spec in writing before you export: container, codec, resolution, bitrate, audio. "
        "Naming matters — use the version name and date in the file name, not «final_final_2»."
    ), (
        "Попросите требования к сдаче в письменном виде до рендера: контейнер, кодек, разрешение, битрейт, звук. "
        "Имена файлов имеют значение — впишите версию и дату, а не «final_final_2»."
    ), [
        ("delivery spec", "dɪˈlɪvəri spek", "требования к сдаче (deliverables): контейнер, кодек, разрешение, битрейт, аудио"),
        ("container", "kənˈteɪnə", "контейнер — файл-обёртка: mp4, mov, mkv и т. п."),
        ("resolution", "ˌrezəˈluːʃn", "разрешение: сколько пикселей по горизонтали и вертикали"),
        ("export", "ˈekspɔːt", "выгрузка/рендер готового файла"),
    ]),
]

_CORPUS_GENERAL: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    ("a busy week", (
        "My week is quite full, but that is fine. I work in the morning and finish the important things before lunch. "
        "In the evening I try to keep two hours free for reading, because tired eyes make everything harder."
    ), (
        "У меня неделя довольно плотная, но это нормально. Я работаю утром и заканчиваю важное до обеда. "
        "Вечером стараюсь оставить два часа на чтение: усталые глаза делают всё тяжелее."
    ), [
        ("quite full", "kwaɪt fʊl", "довольно плотный (о времени, графике)"),
        ("finish", "ˈfɪnɪʃ", "закончить, доделать"),
        ("free", "friː", "свободный (о времени) — здесь это «свободный от дел»"),
        ("tired eyes", "ˈtaɪəd aɪz", "усталые глаза: слишком много экрана за день"),
    ]),
    ("public transport", (
        "I take the metro every morning. It takes forty minutes, and in the morning you can always find a seat. "
        "The only problem is the signal — sometimes the train stops between two stations for ten minutes."
    ), (
        "Каждое утро я езжу на метро. Это занимает сорок минут, и утром там всегда находится место. "
        "Единственная проблема — связь: иногда поезд стоит между двумя станциями по десять минут."
    ), [
        ("take the metro", "teɪk ðə ˈmetrə", "ездить на метро"),
        ("find a seat", "faɪnd ə siːt", "найти место (в вагоне, в зале)"),
        ("signal", "ˈsɪɡnəl", "связь (мобильная/радиосигнал), а не «сигнал» в смысле знака"),
        ("between two stations", "bɪˈtwiːn", "между двумя станциями"),
    ]),
    ("looking for a flat", (
        "We are looking for a small flat with two rooms and a kitchen. It should be close to the metro, "
        "but not on a noisy street. The price matters, of course, so we are looking at several places at once."
    ), (
        "Мы ищем небольшую квартиру с двумя комнатами и кухней. Желательно недалеко от метро, "
        "но не на шумной улице. Цена, конечно, важна, поэтому мы смотрим сразу несколько вариантов."
    ), [
        ("flat", "flæt", "квартира (британский вариант; американское слово — apartment)"),
        ("as soon as", "əz suːn əz", "как можно скорее"),
        ("noisy", "ˈnɔɪzi", "шумный"),
        ("price", "praɪs", "цена, стоимость"),
    ]),
    ("a small kitchen", (
        "The kitchen is very small, but we cook almost every day. I bought a cutting board and a good knife, "
        "and that is really all I need. Washing up takes ten minutes, so we eat and clean straight away."
    ), (
        "Кухня совсем маленькая, но мы готовим почти каждый день. Я купил разделочную доску и хороший нож, "
        "и больше мне ничего не нужно. Мыть посуду занимает десять минут, поэтому мы едим и сразу убираем."
    ), [
        ("cutting board", "ˈkʌtɪŋ bɔːd", "разделочная доска"),
        ("knife", "naɪf", "нож"),
        ("washing up", "ˈwɒʃɪŋ ʌp", "мыть посуду (не «стирка» — это washing the clothes)"),
        ("straight away", "streɪt əˈweɪ", "сразу, не откладывая"),
    ]),
    ("learning English", (
        "I am learning English, and I read a little every day. The hardest part is listening: I understand the words, "
        "but the speed is the problem. Now I watch short videos about my work instead of films."
    ), (
        "Я учу английский и каждый день читаю немного. Самая трудная часть — аудирование: слова я понимаю, "
        "но проблема в скорости. Теперь я смотрю короткие видео про свою работу вместо фильмов."
    ), [
        ("hardest part", "ˈhɑːdɪst pɑːt", "самая трудная часть"),
        ("speed", "spiːd", "скорость (речи, темп)"),
        ("instead of", "ɪnˈsted əv", "вместо (чего-то)"),
        ("watch", "wɒtʃ", "смотреть (видео)"),
    ]),
    ("a dentist appointment", (
        "I have a dentist appointment on Thursday, so I will finish work early. I am not afraid of dentists, "
        "but I always forget to say which tooth hurts."
    ), (
        "У меня в четверг приём у стоматолога, поэтому я закончу работу пораньше. Я не боюсь стоматологов, "
        "но всегда забываю сказать, какой именно зуб болит."
    ), [
        ("appointment", "əˈpɔɪntmənt", "приём, запись к врачу"),
        ("finish work early", "ˈfɪnɪʃ wɜːk ˈɜːtli", "закончить работу пораньше"),
        ("afraid of", "əˈfreɪd əv", "бояться кого-то/чего-то"),
        ("tooth", "tuːθ", "зуб (мн. teeth)"),
    ]),
    ("learning to cook", (
        "Last month I learned to cook, or at least to cook five dishes properly. Now I make lunch for the office on Fridays. "
        "My colleagues say the soup is too salty, but nobody has asked me to stop."
    ), (
        "В прошлом месяце я научился готовить — ну, по крайней мере, пять блюд как следует. Теперь по пятницам делаю обед в офис. "
        "Коллеги говорят, что суп слишком солёный, но никто не просил перестать."
    ), [
        ("properly", "ˈprɒpəli", "как следует, правильно"),
        ("make lunch", "meɪk lʌntʃ", "готовить обед (make — готовить еду, cook — варить/жарить)"),
        ("salty", "ˈsɔːlti", "солёный"),
        ("stop", "stɒp", "перестать (делать что-то)"),
    ]),
    ("weekend plans", (
        "This weekend I am staying home, because there is a lot of rain outside. I will finally fix the bicycle "
        "and read the book I started in March. On Sunday I will call my parents."
    ), (
        "На этих выходных я остаюсь дома — на улице сильный дождь. Наконец починю велосипед и дочитаю книгу, "
        "которую начал в марте. В воскресенье позвоню родителям."
    ), [
        ("weekend", "ˌwiːkˈend", "выходные (суббота и воскресенье)"),
        ("staying home", "ˈsteɪɪŋ həʊm", "оставаться дома (staying — форма от stay)"),
        ("finally", "ˈfaɪnəli", "наконец-то"),
        ("fix the bicycle", "fɪks", "починить велосипед"),
    ]),
    ("the first interview", (
        "I had my first job interview last week, and I was very nervous. They asked three questions about my experience, "
        "and I answered all of them. On Monday they will call me, but I am trying not to wait for the phone."
    ), (
        "На прошлой неделе у меня было первое собеседование, и я очень нервничал. Меня спросили о моём опыте три раза, "
        "и я ответил на все вопросы. В понедельник они мне позвонят, но я стараюсь не сидеть и не ждать звонка."
    ), [
        ("interview", "ˈɪntəvjuː", "собеседование (из интервьюера) — не «интервью» в телевизоре"),
        ("nervous", "ˈnɜːvəs", "нервничающий, нервный"),
        ("experience", "ɪkˈspɪəriəns", "опыт (рабочий опыт)"),
        ("answer", "ˈɑːnsə", "отвечать (на вопрос)"),
    ]),
    ("helping a friend", (
        "My friend moved to another city, so we spent the weekend carrying boxes. We took a break every hour, "
        "because the stairs in his building are very old. In the evening we drank tea and ate pizza."
    ), (
        "Мой друг переехал в другой город, поэтому мы целые выходные таскали коробки. Каждый час делали перерыв, "
        "потому что лестница в его доме очень старая. Вечером пили чай и ели пиццу."
    ), [
        ("move to", "muːv tuː", "переехать (в) — без предлога в отрицаниях: did not move"),
        ("carry boxes", "ˈkæri", "таскать коробки"),
        ("take a break", "teɪk ə breɪk", "делать перерыв"),
        ("pizza", "ˈpiːtsə", "пицца"),
    ]),
]

CORPUS: dict[str, list[tuple[str, str, str, list[tuple[str, str, str]]]]] = {
    "video": _CORPUS_VIDEO,
    "general": _CORPUS_GENERAL,
}
BUILTIN_SIZES = {k: len(v) for k, v in CORPUS.items()}


# ------------------------------------------------------------------ ключи/настройки
def _jload(key: str, default):
    raw = get_setting(key)
    if not raw:
        return default
    try:
        out = _json.loads(raw)
    except (ValueError, TypeError):
        log.debug("ключ %s битый — беру значения по умолчанию", key)
        return default
    return out if isinstance(out, type(default)) else default


def _jsave(key: str, value) -> None:
    set_setting(key, _json.dumps(value, ensure_ascii=False))


def get_track() -> str:
    """Выбранное направление. Неизвестное/битое значение — дефолт."""
    t = (get_setting(K_TRACK) or "").strip().lower()
    return t if t in TRACKS else DEFAULT_TRACK


def settings() -> dict:
    """Настройки блока обучения для API (без секретов, секретов тут нет)."""
    return {"track": get_track(), "llm": llm_enabled(), "tracks": [{"id": k, "title": v} for k, v in TRACKS.items()],
            "tracks_count": {k: BUILTIN_SIZES.get(k, 0) for k in TRACKS},
            "custom_count": len(custom_list()), "custom_limit": CUSTOM_LIMIT, "default_track": DEFAULT_TRACK}


def llm_enabled() -> bool:
    return (get_setting(K_LLM) or "").strip().lower() in ("1", "true", "yes", "on", "да")


def save_settings(changes: dict) -> dict:
    """Сохранить направление и флаг «генерировать нейросетью». Неизвестные поля — ValueError → 400."""
    ch = changes or {}
    known = {"track", "llm"}
    unknown = sorted(set(ch) - known)
    if unknown:
        raise ValueError("неизвестные поля настроек английского: " + ", ".join(unknown))
    # поле со значением None («фронт это не прислал») не меняется — частичное сохранение
    # не должно затирать второе поле
    ch = {k: v for k, v in ch.items() if v is not None}
    if "track" in ch:
        t = str(ch.get("track") or "").strip().lower()
        if t not in TRACKS:
            raise ValueError("направление должно быть одним из: " + ", ".join(TRACKS))
        set_setting(K_TRACK, t)
    if "llm" in ch:
        set_setting(K_LLM, "1" if _truthy(ch.get("llm")) else "0")
    return settings()


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on", "да")
    return bool(v)


def today() -> str:
    """Сегодняшняя дата по локальной зоне (owner.timezone), строка ГГГГ-ММ-ДД."""
    try:
        from zoneinfo import ZoneInfo

        from ..config import TZ
        return datetime.now(ZoneInfo(TZ or "Europe/Moscow")).strftime("%Y-%m-%d")
    except Exception:  # pragma: no cover — нет tzdata или неверная зона
        log.debug("локальная зона недоступна, беру время сервера")
        return datetime.now().strftime("%Y-%m-%d")


def _day_no(date: str) -> int:
    """Номер дня от эпохи для строки ГГГГ-ММ-ДД (битая строка — сегодняшний день)."""
    try:
        return _date.fromisoformat(str(date)).toordinal()
    except (ValueError, TypeError):
        return _date.today().toordinal()


def pick_index(date: str, track: str) -> int:
    """Детерминированный номер абзаца: (номер дня от эпохи + соль направления) % len(corpus).

    Почему не просто `hash(дата) % n` (как в ТЗ): встроенный `hash()` для строк
    рандомизируется при старте интерпретатора (PYTHONHASHSEED) и абзац «прыгал» бы между
    перезапусками ядра, а crc32 % 10 на соседних днях повторялся (проверено: 3 раза из 60) —
    «каждый день новый абзац» тогда не выполняется. Номер дня от эпохи растёт ровно на 1
    в сутки, поэтому соседние дни дают заведомо разные абзацы, а корпус проходится целиком
    и повторяется по кругу. Соль трека (crc32 от его id) разводит направления между собой.
    """
    n = len(CORPUS.get(track) or _CORPUS_VIDEO)
    salt = zlib.crc32(str(track).encode("utf-8"))
    return (_day_no(date) + salt) % max(1, n)


def builtin(track: str, date: str) -> dict:
    """Абзац дня из встроенного корпуса (без обращения к сети)."""
    body = CORPUS.get(track) or CORPUS[DEFAULT_TRACK]
    t = track if track in CORPUS else DEFAULT_TRACK
    topic, text_en, text_ru, words = body[pick_index(date, t)]
    return {"date": date, "track": t, "title": topic, "text_en": text_en, "text_ru": text_ru,
            "words": [{"word": w, "phonetic": p, "note": n} for w, p, n in words],
            "source": "builtin", "is_new": True}


# ------------------------------------------------------------------ свои тексты (settings KV)
def custom_list() -> list[dict]:
    """Свои тексты: новые сверху. Старые/битые записи молча пропускаем."""
    rows = _jload(K_CUSTOM, [])
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        en = str(r.get("text_en") or "").strip()
        if not en:
            continue
        out.append({"text_en": en[:_CUSTOM_MAX_LEN], "text_ru": str(r.get("text_ru") or "").strip()[:_CUSTOM_MAX_LEN],
                    "note": str(r.get("note") or "").strip()[:300], "at": str(r.get("at") or "")})
    return out[:CUSTOM_LIMIT]


def add_custom(text_en: str, text_ru: str = "", note: str = "") -> dict:
    """Добавить свой текст + перевод. ValueError → 400 в API."""
    en = (text_en or "").strip()
    if not en:
        raise ValueError("текст на английском пустой")
    rows = custom_list()
    row = {"text_en": en[:_CUSTOM_MAX_LEN], "text_ru": (text_ru or "").strip()[:_CUSTOM_MAX_LEN],
           "note": (note or "").strip()[:300], "at": datetime.now().isoformat(timespec="seconds")}
    rows.insert(0, row)
    _jsave(K_CUSTOM, rows[:CUSTOM_LIMIT])
    return row


def delete_custom(idx: int) -> bool:
    """Удалить свой текст по индексу в текущем списке. False — нечего удалять."""
    rows = custom_list()
    if not (0 <= idx < len(rows)):
        return False
    rows.pop(idx)
    _jsave(K_CUSTOM, rows)
    return True


def _custom_today(date: str) -> dict:
    """Абзац дня из своих текстов: детерминированно по дате, без LLM."""
    rows = custom_list()
    if not rows:
        return {"date": date, "track": "custom", "title": "", "text_en": "", "text_ru": "", "words": [],
                "source": "custom", "is_new": False, "empty": True}
    row = rows[(_day_no(date) + zlib.crc32(b"custom")) % len(rows)]
    return {"date": date, "track": "custom", "title": row.get("note") or "свой текст", "text_en": row["text_en"],
            "text_ru": row.get("text_ru", ""), "words": [], "source": "custom", "is_new": True}


# ------------------------------------------------------------------ абзац дня
async def today_paragraph(track: str | None = None, day: str | None = None, use_llm: bool | None = None) -> dict:
    """Абзац дня для направления.

    * направление из настроек (или переопределено аргументом — так работает превью `?track=`);
    * дата — сегодняшняя по локальной зоне (или переопределена аргументом);
    * `use_llm=None` → решает настройка `english.llm` (по умолчанию выключена);
    * LLM недоступна/ответила мусором — тихо отдаём встроенный корпус, ошибки наружу не идут.
    """
    tr = (track or get_track()).strip().lower()
    tr = tr if tr in TRACKS else DEFAULT_TRACK
    d = (day or "").strip() or today()
    try:
        _date.fromisoformat(d)      # мусор в ?day= — тихо берём сегодняшний день
    except (ValueError, TypeError):
        d = today()
    if tr == "custom":
        return _custom_today(d)
    want = llm_enabled() if use_llm is None else bool(use_llm)
    if want:
        cached = _cache_get(d, tr)
        if cached:
            return cached
        gen = await _llm_paragraph(d, tr)
        if gen:
            # ответ LLM приводим к той же форме, что и встроенный корпус: даты и флаги
            # в кэш не кладём, они всё равно проставляются при отдаче
            out = {"title": gen.get("title") or "", "text_en": gen.get("text_en") or "",
                   "text_ru": gen.get("text_ru") or "", "words": gen.get("words") or [],
                   "source": "llm", "is_new": True}
            _cache_put(d, tr, out)
            return {**out, "date": d, "track": tr}
        log.info("LLM для абзаца дня недоступна — отдаю встроенный корпус (%s)", d)
    return builtin(tr, d)


def _cache_key(day: str, track: str) -> str:
    return f"{day}|{track}"


def _cache_get(day: str, track: str) -> dict | None:
    row = (_jload(K_CACHE, {}) or {}).get(_cache_key(day, track))
    if not isinstance(row, dict) or not (row.get("text_en") or "").strip():
        return None
    return {**row, "date": day, "track": track, "source": row.get("source") or "llm"}


def _cache_put(day: str, track: str, row: dict) -> None:
    cache = _jload(K_CACHE, {})
    if not isinstance(cache, dict):
        cache = {}
    # храним только последние 7 дней — иначе ключ в базе растёт бесконечно
    keys = [k for k in cache if k.split("|")[0] < (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")]
    for k in keys:
        cache.pop(k, None)
    cache[_cache_key(day, track)] = row
    _jsave(K_CACHE, cache)


_PROMPT = (
    "Ты — учитель английского для видеомонтажёра. Напиши ОДИН абзац на 60–90 слов на тему ниже.\n"
    "Требования: живой рабочий английский (A2–B1), без перевода внутри, 3–6 коротких предложений, "
    "используй реальную терминологию монтажа и поста. Никаких markdown-заголовков и списков.\n\n"
    "Ответь СТРОГО в JSON без пояснений:\n"
    '{"title": "тема 2–4 слова на английском", "text_en": "абзац на английском", '
    '"text_ru": "перевод абзаца на русский", "words": [{"word": "слово", "phonetic": "транскрипция", '
    '"note": "короткое пояснение по-русски"}]}\n'
    "words — 3–5 ключевых слов ИЗ текста."
)

_CORPUS_TOPICS = ("timeline, cut and keyframes", "sound sync and levels", "codecs and proxies",
                  "colour grading and LUTs", "exports and deliverables", "client feedback on a rough cut")


async def _llm_paragraph(day: str, track: str) -> dict | None:
    """Свежий абзац от LLM под направление. None — модель недоступна или ответ не разобрали."""
    topic = _CORPUS_TOPICS[zlib.crc32(day.encode("utf-8")) % len(_CORPUS_TOPICS)]
    user = f"Сегодня {day}. Тема дня: {topic}."
    system = _PROMPT
    try:
        from ..brain import llm
        raw = None
        if await llm.local_available():
            out = await llm.ollama_chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                       temperature=0.4, json_mode=True)
            raw = out.get("content") or ""
        elif llm.MODE == "cloud" and llm.cloud_enabled():
            raw = await llm.cloud_chat(system + "\nОтвечай только JSON, без markdown и пояснений.", user) or ""
    except Exception as e:  # pragma: no cover — сеть/модель
        log.info("абзац дня от LLM не получился: %s", e)
        return None
    d = _parse_json(raw)
    en = str((d or {}).get("text_en") or "").strip()
    if not en:
        return None
    return {"title": str(d.get("title") or topic)[:80], "text_en": en,
            "text_ru": str(d.get("text_ru") or "").strip(), "words": _clean_words(d.get("words")),
            "source": "llm", "is_new": True}


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    m = _re.search(r"\{.*\}", text.strip(), _re.S)
    if not m:
        return None
    try:
        out = _json.loads(m.group(0))
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def _clean_words(words) -> list[dict]:
    out: list[dict] = []
    for w in (words or [])[:5]:
        if not isinstance(w, dict):
            continue
        word = str(w.get("word") or "").strip()
        if not word:
            continue
        out.append({"word": word[:60], "phonetic": str(w.get("phonetic") or "").strip()[:60],
                    "note": str(w.get("note") or "").strip()[:160]})
    return out


# ------------------------------------------------------------------ прогресс и стрик
def _progress_raw() -> dict:
    d = _jload(K_PROGRESS, {})
    days = d.get("days") if isinstance(d, dict) else None
    return {"days": days if isinstance(days, dict) else {}}


def mark_done(track: str | None = None, day: str | None = None) -> dict:
    """Отметить день прочитанным. Повтор в тот же день — не накручивает счётчик (идемпотентно)."""
    tr = (track or get_track()).strip().lower()
    tr = tr if tr in TRACKS else DEFAULT_TRACK
    d = (day or "").strip() or today()
    try:
        _date.fromisoformat(d)      # мусор в параметре — тихо берём сегодняшний день
    except (ValueError, TypeError):
        d = today()
    raw = _progress_raw()
    days = raw["days"]
    row = days.get(d) if isinstance(days.get(d), dict) else {}
    already = bool(row)
    days[d] = {"track": tr, "title": str(row.get("title") or "")[:120],
               "at": (row.get("at") if already else datetime.now().isoformat(timespec="seconds"))}
    _jsave(K_PROGRESS, {"days": days})
    out = progress()
    out["already"] = already
    return out


def progress() -> dict:
    """Стрик, всего дней, последний день и разбивка по направлениям.

    Стрик — сколько дней подряд (по локальной дате) отмечено, включая сегодня; если сегодня
    ещё не отмечено, но вчера был — стрик не рвётся (день ведь не закончился).
    """
    raw = _progress_raw()
    days = {k: v for k, v in raw["days"].items() if _valid_day(k)}
    keys = sorted(days)
    by_track: dict[str, dict] = {}
    for k in keys:
        t = (days[k] or {}).get("track") if isinstance(days[k], dict) else None
        t = t if t in TRACKS else "—"
        by_track.setdefault(t, {"days": 0, "last_date": None})
        by_track[t]["days"] += 1
        if not by_track[t]["last_date"] or k > by_track[t]["last_date"]:
            by_track[t]["last_date"] = k
    return {"streak": _streak(keys), "total_days": len(keys), "last_date": keys[-1] if keys else None,
            "by_track": by_track, "today_done": today() in days}


def _valid_day(k) -> bool:
    try:
        _date.fromisoformat(str(k))
        return True
    except (ValueError, TypeError):
        return False


def _streak(keys: list[str]) -> int:
    """Дни подряд назад от последней отмеченной даты (с допуском «вчера»)."""
    if not keys:
        return 0
    try:
        last = _date.fromisoformat(keys[-1])
        cur = _date.fromisoformat(today())
    except (ValueError, TypeError):  # pragma: no cover
        return 0
    if cur - last > timedelta(days=1):
        return 0            # пропустил дни — серия прервана
    n = 0
    d = last
    while True:
        if d.isoformat() not in keys:
            break
        n += 1
        d -= timedelta(days=1)
    return n
