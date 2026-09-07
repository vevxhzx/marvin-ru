"""Имя ассистента. Задаётся пользователем в мастере первого запуска (assistant.name в config.yaml).

Всё, что зависит от имени — обращение в промпте, слово-пробуждение для голоса, подпись на карточках, —
берётся отсюда, а не из захардкоженных строк.
"""
from __future__ import annotations

import re

from .config import cfg

_a = getattr(cfg, "assistant", None)
NAME: str = str(getattr(_a, "name", "") or "Марвин").strip()
# имя латиницей — для логов, имён файлов, заголовков окон
NAME_LATIN: str = str(getattr(_a, "name_latin", "") or "").strip() or NAME
# как ассистент обращается к хозяину («сэр», «босс», по имени…)
OWNER: str = str(getattr(getattr(cfg, "owner", None), "name", "") or "Сэр").strip()

_ALIASES = [x.strip() for x in str(getattr(_a, "aliases", "") or "").split(",") if x.strip()]


def _forms(name: str) -> list[str]:
    """Простейшие падежные формы русского имени: Марвин → марвин, марвина, марвину, марвином, марвине."""
    n = name.lower()
    out = {n}
    if re.search(r"[бвгджзклмнпрстфхцчшщ]$", n):
        out |= {n + "а", n + "у", n + "ом", n + "е"}
    elif n.endswith("а"):
        out |= {n[:-1] + "ы", n[:-1] + "е", n[:-1] + "у", n[:-1] + "ой"}
    elif n.endswith("я"):
        out |= {n[:-1] + "и", n[:-1] + "е", n[:-1] + "ю", n[:-1] + "ей"}
    return sorted(out, key=len, reverse=True)


NAMES: list[str] = sorted({*_forms(NAME), *(a.lower() for a in _ALIASES), NAME_LATIN.lower()}, key=len, reverse=True)
NAME_RX_SRC: str = "(?:" + "|".join(re.escape(x) for x in NAMES) + ")"
NAME_RX = re.compile(NAME_RX_SRC, re.I)

# «Эй, Марвин, …» в начале фразы → срезаем
WAKE_RX = re.compile(r"^\s*(?:эй|окей|ок|слушай|привет)?\s*,?\s*" + NAME_RX_SRC + r"\s*[,!.:\-—]*\s*", re.I)


def _fuzzy(name: str) -> str:
    """Regex «как Vosk может расслышать имя»: каждая буква — класс похожих звуков, гласные необязательны.
    Для «Марвин» получится что-то вроде  м[ао]?р?в[иеы]н...  — ловит «марвин», «марвен», «морвин»."""
    n = name.lower()
    sim = {"а": "[ао]", "о": "[ао]", "е": "[еиэя]", "и": "[иеы]", "э": "[еиэя]", "я": "[еиэя]", "ы": "[иеы]", "у": "[ую]", "ю": "[ую]",
           "з": "[зсж]", "с": "[зсш]", "ж": "[жшз]", "ш": "[шжс]", "в": "[вф]", "ф": "[вф]", "б": "[бп]", "п": "[бп]", "д": "[дт]", "т": "[дт]",
           "г": "[гк]", "к": "[гк]", "ч": "[чщтс]", "щ": "[чщш]", "ц": "[цтс]"}
    parts = []
    for i, ch in enumerate(n):
        if ch in "аоеиэяыую" and 0 < i < len(n) - 1:
            parts.append(sim.get(ch, re.escape(ch)) + "?")
        else:
            parts.append(sim.get(ch, re.escape(ch)))
    return r"\b" + "".join(parts) + r"\w*"


VOSK_WAKE_RX = re.compile("|".join(_fuzzy(x) for x in [NAME, *_ALIASES] if x), re.I)


def title() -> str:
    """Имя с большой буквы для интерфейса."""
    return NAME[:1].upper() + NAME[1:]
