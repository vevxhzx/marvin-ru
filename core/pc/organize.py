"""Безопасная организация монтажных и звуковых папок.
Сначала план, потом подтверждение. Ничего не удаляется; журнал позволяет отменить перенос.
"""
from __future__ import annotations
import json, time, uuid, os, logging, re, urllib.request
from pathlib import Path

log = logging.getLogger("jarvis.organize")
SKIP_DIRS = {"SFX", "01_Архивы", "02_Музыка", "03_Голоса", "04_Атмосферы", "05_Шаги", "06_Удары", "07_Переходы", "08_Интерфейс", "09_Фоли", "10_Природа", "11_Транспорт", "12_Оружие", "13_Магия", "14_Реверсы", "15_Рендеры", "99_Прочее", "Организовано"}
VIDEO={".mp4",".mov",".mkv",".avi",".webm",".mxf",".mts",".m4v",".wmv"}
AUDIO={".wav",".mp3",".flac",".m4a",".aac",".aiff",".aif",".ogg",".opus"}
IMAGE={".jpg",".jpeg",".png",".tif",".tiff",".psd",".psb",".ai",".svg",".webp",".dng",".raw"}
PROJECT={".prproj",".aep",".drp",".fcpxml",".fcpbundle",".veg",".c4d",".blend"}

# Порядок важен: сначала узкие названия, потом общие. Поддерживаются ru/en и разделители _-.
SOUND_RULES = [
 ("02_Музыка", r"music|музык|song|track|theme|score|мелод|саундтрек|ost|loop|луп"),
 ("03_Голоса", r"voice|vox|speech|dialog|dialogue|vocal|говор|голос|реплик|фраз|шёпот|шепот|laugh|смех|cry|крик"),
 ("05_Шаги", r"footstep|foot.?step|walk|run|sprint|step|шаг|бег|ходьб|движени[ея].*ног"),
 ("08_Интерфейс", r"ui[ _-]|interface|button|menu|notification|notify|select|hover|click|tap|keyboard|mouse|кноп|интерфейс|клавиатур|мыш"),
 ("06_Удары", r"impact|hit|punch|slam|thud| удар|удар[а-я]*|столкнов|crash|бум|boom|хлоп|snap|knock"),
 ("07_Переходы", r"whoosh|woosh|swish|swoosh|transition|sweep|pass.?by|переход|свип|свуш|пролёт|пролет"),
 ("09_Фоли", r"foley|cloth|clothes|fabric|leather|paper|book|door|drawer|ключ|key|бумаг|ткан|одежд|двер|ящик|шаг"),
 ("10_Природа", r"nature|wind|rain|water|fire|thunder|bird|animal|forest|ocean|дожд|ветер|вода|огонь|гром|птиц|лес|море|животн"),
 ("11_Транспорт", r"car|truck|engine|motor|vehicle|train|plane|helicopter|машин|двигател|мотор|поезд|самол[её]т|вертол[её]т"),
 ("12_Оружие", r"gun|rifle|pistol|shot|reload|bullet|weapon|выстрел|пистолет|винтов|оруж|перезаряд|пул"),
 ("13_Магия", r"magic|spell|fantasy|power|energy|laser|плазм|маг|заклин|энерги|лазер"),
 ("14_Реверсы", r"reverse|реверс|backward|назад"),
 ("04_Атмосферы", r"ambience|ambient|atmo|roomtone|background|atmos|атмосфер|фон|комнат|окруж|шум"),
]

def _category(p: Path, profile: str = "auto") -> str:
    n=p.name.lower(); e=p.suffix.lower()
    if e in PROJECT: return "05_Проекты"
    if profile == "sound" and e in AUDIO:
        for cat, rx in SOUND_RULES:
            if re.search(rx, n, re.I): return cat
        if any(x in n for x in ("sfx", "fx", "sound", "зву")): return "04_Атмосферы"
        return "99_Прочее"
    if any(x in n for x in ("proxy","прокси","_prx","-prx")): return "06_Прокси"
    if any(x in n for x in ("render","рендер","export","экспорт","final","master")): return "07_Рендеры"
    if e in VIDEO: return "02_Исходники/Видео"
    if e in AUDIO: return "02_Исходники/Аудио"
    if e in IMAGE: return "03_Графика"
    if e in {".srt",".ass",".vtt",".otf",".ttf"}: return "03_Графика"
    return "99_Прочее"

def detect_profile(root: Path, files: list[Path]) -> str:
    path = str(root).lower()
    audio = sum(p.suffix.lower() in AUDIO for p in files)
    if audio >= 5 or any(x in path for x in ("sfx", "sound", "звук", "звуки", "музык")): return "sound"
    return "montage"

def _safe_name(value: str, fallback: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', str(value)).strip().strip('.')
    return (value[:80] or fallback)


def _ai_pack_names(root: Path, packs: dict[str, list[str]]) -> tuple[dict[str, str], str]:
    """Qwen только предлагает названия крупных исходных паков; правила и безопасность остаются локальными."""
    if not packs:
        return {}, "не требовался"
    model = os.environ.get("JARVIS_OLLAMA_MODEL") or os.environ.get("OLLAMA_MODEL") or "qwen3.5:4b"
    payload = {"model": model, "stream": False, "format": "json", "prompt": (
        "Ты помощник по организации библиотеки SFX. Верни только JSON вида "
        "{\\\"names\\\":{\\\"исходная папка\\\":\\\"короткое понятное имя\\\"}}. "
        "Не переименовывай смысл в другой пак и не используй слэши. Сохраняй оригинальное имя как часть результата. "
        f"Паки и примеры файлов: {json.dumps(packs, ensure_ascii=False)[:12000]}"
    )}
    try:
        req=urllib.request.Request(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip('/')+"/api/generate", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req, timeout=15) as r: raw=json.loads(r.read().decode())
        data=json.loads(raw.get("response", "{}")); names=data.get("names", {}) if isinstance(data,dict) else {}
        return {k: _safe_name(v, k) for k,v in names.items() if k in packs and isinstance(v,str)}, f"Qwen {model}"
    except Exception as e:
        log.info("Qwen для организации недоступен: %s", str(e)[:120])
        return {}, "правила без Qwen"


def scan(root: Path, rules_file: Path | None = None) -> dict:
    root=root.expanduser().resolve()
    if not root.exists() or not root.is_dir(): return {"ok":False,"root":str(root),"error":"Папка не найдена","moves":[],"total":0}
    skip_names=SKIP_DIRS|{".git","node_modules","__pycache__",".venv","venv","cache","превью","previews"}
    candidates=[]; count=0
    for base,dirs,files in os.walk(root,topdown=True,followlinks=False):
        dirs[:]=[d for d in dirs if d not in skip_names and not d.startswith(".")]
        for name in files:
            count+=1
            if count>100000: return {"ok":False,"root":str(root),"error":"В папке больше 100 000 файлов — остановил сканирование","moves":[],"total":0}
            p=Path(base)/name
            try: p.relative_to(root); p.stat(); candidates.append(p)
            except OSError: continue
    profile=detect_profile(root,candidates)
    custom={}
    if rules_file and rules_file.exists():
        try: custom=json.loads(rules_file.read_text(encoding="utf-8"))
        except (OSError,ValueError): pass
    packs={}
    for p in candidates:
        rel=p.relative_to(root)
        if len(rel.parts) > 1 and rel.parts[0] not in SKIP_DIRS:
            packs.setdefault(rel.parts[0], []).append(p.name)
    large_packs={k: v[:20] for k,v in packs.items() if len(v) >= 8}
    ai_names, ai_status = _ai_pack_names(root, large_packs) if profile == "sound" else ({}, "не звуковой профиль")
    moves=[]
    source_dirs = sorted({p.parent for p in candidates if p.parent != root}, key=lambda x: len(x.parts), reverse=True)
    for p in candidates:
        rel=p.relative_to(root)
        if rel.parts and rel.parts[0] in SKIP_DIRS: continue
        cat=None
        if profile=="sound" and p.suffix.lower() in AUDIO:
            for key,value in custom.get("keywords",{}).items():
                if any(w.lower() in p.name.lower() for w in value): cat=key; break
        cat=cat or _category(p,profile)
        dest_root = root / "SFX" if profile == "sound" and root.name.lower() != "sfx" else root
        # Большие паки не смешиваем: каждый верхний исходный пак получает собственную папку.
        rel = p.relative_to(root)
        pack = rel.parts[0] if len(rel.parts) > 1 else "Корень"
        if profile == "sound" and pack in large_packs:
            label = ai_names.get(pack)
            pack_name = _safe_name(f"{pack} — {label}", pack) if label and label.lower() != pack.lower() else _safe_name(pack, "Пак")
            dst = dest_root / pack_name / cat / p.name
        else:
            dst=dest_root/cat/p.name
        if p.parent==dst.parent: continue
        moves.append({"src":str(p),"dst":str(dst),"cat":cat,"size":p.stat().st_size})
    # Старые каталоги после переноса не оставляем: удаляются только пустые каталоги,
    # попавшие в план, и только после подтверждения. Файлы и непустые папки не трогаем.
    cleanup=[]
    for d in source_dirs:
        if d.name in SKIP_DIRS or d.parts[:len(root.parts)] != root.parts: continue
        cleanup.append(str(d))
    by={}
    for m in moves: by[m["cat"]]=by.get(m["cat"],0)+1
    return {"ok":True,"root":str(root),"profile":profile,"moves":moves,"total":len(moves),"by_category":by,"files_scanned":count,"cleanup_dirs":cleanup,"large_packs":sorted(large_packs),"ai_status":ai_status}

def _plan_path(data_dir:Path)->Path:return data_dir/"organize_plan.json"
def _journal_path(data_dir:Path)->Path:return data_dir/"organize_journal.json"
def make_plan(root:Path,data_dir:Path,rules_file:Path|None=None)->dict:
    plan=scan(root,rules_file); plan.update({"id":uuid.uuid4().hex[:10],"at":time.time()}); _plan_path(data_dir).parent.mkdir(parents=True,exist_ok=True); _plan_path(data_dir).write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding="utf-8"); return plan
def load_plan(data_dir:Path,plan_id:str|None=None)->dict|None:
    try:p=json.loads(_plan_path(data_dir).read_text(encoding="utf-8"))
    except(OSError,ValueError):return None
    return p if not plan_id or p.get("id")==plan_id else None
def apply_plan(plan:dict,data_dir:Path)->dict:
    moved=[]; skipped=[]
    for m in plan.get("moves",[]):
        src,dst=Path(m["src"]),Path(m["dst"])
        if not src.exists():skipped.append({**m,"reason":"нет исходника"});continue
        dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists():
            stem,suf=dst.stem,dst.suffix;i=2
            while dst.exists():dst=dst.with_name(f"{stem} ({i}){suf}");i+=1
        try:src.rename(dst);moved.append({"src":str(src),"dst":str(dst),"cat":m["cat"]})
        except OSError as e:skipped.append({**m,"reason":str(e)})
    removed=[]
    for raw in sorted(plan.get("cleanup_dirs", []), key=lambda x: len(Path(x).parts), reverse=True):
        d=Path(raw)
        if d == Path(plan.get("root", "")) or d.name in SKIP_DIRS: continue
        try:
            d.rmdir(); removed.append(str(d))
        except OSError:
            pass
    journal={"id":uuid.uuid4().hex[:10],"plan_id":plan.get("id"),"at":time.time(),"root":plan.get("root"),"moved":moved,"removed_dirs":removed,"skipped":skipped};_journal_path(data_dir).write_text(json.dumps(journal,ensure_ascii=False,indent=2),encoding="utf-8");return journal
def undo(data_dir:Path)->dict:
    try:j=json.loads(_journal_path(data_dir).read_text(encoding="utf-8"))
    except(OSError,ValueError):return {"moved":[],"skipped":[{"reason":"журнал не найден"}]}
    back=[];skipped=[]
    for m in reversed(j.get("moved",[])):
        src,dst=Path(m["src"]),Path(m["dst"])
        if not dst.exists():skipped.append({**m,"reason":"файл уже отсутствует"});continue
        if src.exists():skipped.append({**m,"reason":"исходное имя уже занято"});continue
        src.parent.mkdir(parents=True,exist_ok=True)
        try:dst.rename(src);back.append(m)
        except OSError as e:skipped.append({**m,"reason":str(e)})
    return {"moved":back,"skipped":skipped}
def text(plan:dict)->str:
    if not plan.get("ok"):return f"Не могу открыть папку: {plan.get('root')} — {plan.get('error')}"
    lines=[f"📁 Папка: {plan['root']}",f"🧠 Профиль: {'звуки по названиям' if plan.get('profile')=='sound' else 'монтаж'}","🧭 Предпросмотр организации — ничего ещё не перемещаю:"]
    for cat,n in sorted(plan.get("by_category",{}).items()):lines.append(f"• {cat}: {n} файл(ов)")
    lines.append(f"Просмотрено файлов: {plan.get('files_scanned',0)}. К перемещению: {plan.get('total',0)}.")
    if plan.get("profile") == "sound":
        lines.append("Звуки будут собраны отдельно в папке SFX с подпапками по смыслу.")
        lines.append(f"Крупные паки не смешиваются: {len(plan.get('large_packs', []))}. Умная разметка: {plan.get('ai_status', 'правила')}.")
    if plan.get("cleanup_dirs"):  lines.append(f"Пустые старые папки после переноса будут удалены: до {len(plan['cleanup_dirs'])} (непустые останутся).")
    lines.append("Разложить? Напишите «да» или внесите правки.")
    if not plan.get("total"):lines.insert(3,"Папка уже организована или подходящих файлов нет.")
    return "\n".join(lines)
