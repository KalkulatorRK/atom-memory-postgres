"""Проверка аргументов vector_index_admin.sh (вызывается из bash)."""
from __future__ import annotations

import re
import sys

# PostgreSQL: kB с маленькой k (не KB).
_MEM = re.compile(r"^([0-9]+)\s*(kB|MB|GB|TB)$")

# Диапазон maintenance_work_mem (в kB), ~128 GB верхняя граница для админ-скрипта.
_MIN_KB = 64
_MAX_KB = 128 * 1024 * 1024


def _to_kb(n: int, unit: str) -> int:
    if unit == "kB":
        return n
    if unit == "MB":
        return n * 1024
    if unit == "GB":
        return n * 1024 * 1024
    if unit == "TB":
        return n * 1024 * 1024 * 1024
    raise ValueError(unit)


def normalize_mem(raw: str) -> str:
    s = raw.strip()
    if re.match(r"^[0-9]+\s*KB$", s):
        raise ValueError(
            "maintenance_work_mem: PostgreSQL принимает kB (маленькая k), не KB; "
            "например 512kB, 128MB, 1GB"
        )
    m = _MEM.match(s)
    if not m:
        raise ValueError(
            "maintenance_work_mem: формат 64kB, 128MB, 1GB или 1TB "
            "(kB/MB/GB/TB как в PostgreSQL; без 1gb, 5, 512KB)"
        )
    n = int(m.group(1))
    unit = m.group(2)
    kb = _to_kb(n, unit)
    if kb < _MIN_KB or kb > _MAX_KB:
        raise ValueError(
            f"maintenance_work_mem: вне диапазона {_MIN_KB}kB–{_MAX_KB // (1024 * 1024)}GB"
        )
    return f"{n}{unit}"


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
