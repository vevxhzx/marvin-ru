"""Заметки к релизу из CHANGELOG.md.

Между релизами на GitHub может пройти несколько версий (сначала обкатка у себя, потом публикация),
поэтому берём не одну секцию «## <версия>», а все секции от текущей версии до предыдущего
опубликованного тега (не включая его). Если тегов ещё нет — только текущую секцию.

Использование: release_notes.py <версия> <файл_вывода> [предыдущий_тег, напр. v0.9.15]
Если предыдущий тег не передан — берётся старший тег v* в репозитории, отличный от текущей версии.
"""
import re
import subprocess
import sys


def _ver(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


def main() -> None:
    ver, out = sys.argv[1], sys.argv[2]
    prev = sys.argv[3].lstrip("v") if len(sys.argv) > 3 and sys.argv[3] else ""
    if not prev:
        try:
            tags = subprocess.run(["git", "tag", "--list", "v*"], capture_output=True, text=True, check=False).stdout.split()
            older = sorted((t for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+", t) and _ver(t) < _ver(ver)), key=_ver)
            prev = older[-1].lstrip("v") if older else ""
        except OSError:
            prev = ""
    text = open("CHANGELOG.md", encoding="utf-8").read()
    bodies = re.split(r"^(?=## \d+\.\d+\.\d+\b)", text, flags=re.M)
    bodies = [b for b in bodies if re.match(r"## \d+\.\d+\.\d+\b", b)]
    cur, low = _ver(ver), _ver(prev) if prev else None
    picked = [b for b in bodies if (low is None and _ver(re.match(r"## (\S+)", b).group(1)) == cur)
              or (low is not None and low < _ver(re.match(r"## (\S+)", b).group(1)) <= cur)]
    if not picked:
        picked = [b for b in bodies if _ver(re.match(r"## (\S+)", b).group(1)) == cur] or [text]
    head = ""
    if prev and len(picked) > 1:
        head = f"_Изменения с v{prev} по v{ver} — {len(picked)} версий._\n\n"
    open(out, "w", encoding="utf-8").write(head + "\n".join(b.rstrip() + "\n" for b in picked))


if __name__ == "__main__":
    main()
