"""Проверка аргументов vector_index_admin.sh (вызывается из bash)."""
from __future__ import annotations

import re
import sys

_MEM = re.compile(r"^([0-9]+)\s*(KB|MB|GB|TB)$")


def normalize_mem(raw: str) -> str:
    m = _MEM.match(raw.strip())
    if not m:
        raise ValueError(
            "maintenance_work_mem: нужен формат 128MB, 1GB, 512KB или 1TB "
            "(заглавные KB/MB/GB/TB; без 1gb, 5, 1kB)"
        )
    n = int(m.group(1))
    if n < 1:
        raise ValueError("maintenance_work_mem: число должно быть ≥ 1")
    return f"{n}{m.group(2)}"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: vector_index_validate.py <mem>", file=sys.stderr)
        return 2
    try:
        print(normalize_mem(argv[1]))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
