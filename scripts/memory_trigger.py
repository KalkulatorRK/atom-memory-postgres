#!/usr/bin/env python3
"""Триггер вызова атомной памяти: #memory, #память, память:, memory:, Память:.

Сообщения, начинающиеся с триггера, автоматически считаются запросом к базе:
  python3 memory_trigger.py "#memory чувствительность прибора"
  python3 memory_trigger.py "#память расшифровка обозначения"
  python3 memory_trigger.py "память: какой метод контроля"
  python3 memory_trigger.py "memory: поиск по документу"

Не-триггерный текст → подсказка по триггерам (полезно для агента-обработчика).
Режим --check возвращает 0/1 (триггер найден/нет) — для автоматизации.
"""
import argparse
import os
import subprocess
import sys

TRIGGERS = ("#memory", "#память", "память:", "Память:", "memory:", "Memory:")


def detect(message: str):
    """Возвращает (триггер, запрос) или (None, None), если сообщение не триггер."""
    text = (message or "").strip()
    for trig in TRIGGERS:
        if text.startswith(trig):
            return trig, text[len(trig):].strip()
    return None, None


def main():
    ap = argparse.ArgumentParser(description="Триггер вызова атомной памяти")
    ap.add_argument("message", help="сообщение пользователя (или запрос)")
    ap.add_argument("--check", action="store_true",
                    help="режим проверки: exit 0 если триггер, 1 если нет (без поиска)")
    ap.add_argument("--project", default="",
                    help="фильтр проекта (передаётся в поиск)")
    ap.add_argument("--limit", type=int, default=5,
                    help="сколько атомов вернуть (по умолчанию 5)")
    args = ap.parse_args()

    trig, query = detect(args.message)

    if args.check:
        print(1 if trig else 0)
        sys.exit(0 if trig else 1)

    if not trig:
        print("Сообщение не является триггером. Начните с: #memory, #память, память:, memory:")
        return

    if not query:
        print(f"Триггер «{trig}» найден, но запрос пуст. Пример: {trig} чувствительность прибора")
        return

    # Поиск по базе — тот же скрипт, что и напрямую
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory_query.py")
    cmd = [sys.executable, script, query]
    if args.project:
        cmd += ["--project", args.project]
    cmd += ["--limit", str(args.limit)]
    subprocess.run(cmd)


if __name__ == "__main__":
    main()
