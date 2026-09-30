"""Проверка перед публикацией: не устарел ли web/site относительно исходников web/src.

Сборка на GitHub делается заново, и если хэши файлов в web/site не совпадут с ней — проверка «web/site up to date»
покраснеет. Собрать сайт без Node здесь нельзя, но можно поймать очевидное: исходники новее сборки.
Код выхода 1 = похоже, что устарел.
"""
import os
import sys
from pathlib import Path


def newest(p: Path) -> float:
    return max((f.stat().st_mtime for f in p.rglob("*") if f.is_file()), default=0.0)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    site, src = root / "web" / "site", root / "web" / "src"
    if not site.exists() or not (site / "index.html").exists():
        print("[!] web/site отсутствует — нужен собранный сайт (возьмите папку web/site из архива релиза)")
        return 1
    if not src.exists():
        return 0
    if newest(src) > newest(site) + 1:
        print("[!] web/src новее web/site: сборка сайта устарела.")
        print("    Замените папку web/site ЦЕЛИКОМ на web/site из свежего архива (старую удалить), либо соберите: build_web.bat")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
