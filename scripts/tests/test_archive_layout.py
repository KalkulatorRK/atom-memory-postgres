#!/usr/bin/env python3
"""Структура архива релиза согласована с командой установки из README.

Архив содержит вложенный каталог data-science/atom-memory-postgres/, а README
распаковывает его в ~/.hermes/skills/. Проверяем оба условия на собранном
архиве: SKILL.md оказывается ровно по нужному пути и нигде глубже.
"""
import os
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ARCHIVE = os.environ.get("SKILL_ARCHIVE", os.path.join(ROOT, "atom-memory-postgres-skill.tar.gz"))
EXPECTED = "data-science/atom-memory-postgres/SKILL.md"


def main():
    if not os.path.exists(ARCHIVE):
        print(f"skip: архив не собран ({ARCHIVE})")
        return 0
    with tarfile.open(ARCHIVE) as tar:
        names = [m.name.lstrip("./") for m in tar.getmembers()]
    assert EXPECTED in names, f"{EXPECTED} нет в архиве"
    deeper = [n for n in names if n.count("atom-memory-postgres") > 1]
    assert not deeper, f"двойная вложенность: {deeper}"
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    assert "tar -xzf ~/atom-memory-skill.tar.gz -C ~/.hermes/skills/" in readme
    assert "-C ~/.hermes/skills/data-science" not in readme, "README снова пакует в каталог скилла"
    print("ok  archive layout matches README")
    return 0


if __name__ == "__main__":
    sys.exit(main())
