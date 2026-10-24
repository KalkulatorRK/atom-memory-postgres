#!/usr/bin/env bash
# Сборка архива скилла для релиза. Результат: atom-memory-postgres-skill.tar.gz
# с префиксом data-science/atom-memory-postgres/, без .git, .github, __pycache__, *.pyc.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/atom-memory-postgres-skill.tar.gz}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# git archive отдаёт только отслеживаемые файлы (без .git/.github/pyc, если не в git)
if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    # .github/ лежит в git (workflows), но в архиве скилла ему не место —
    # без --exclude проверка ниже валит сборку на собственном архиве.
    git -C "$ROOT" archive --format=tar HEAD \
        | tar -x -C "$STAGE" --transform 's,^,data-science/atom-memory-postgres/,' \
            --exclude='.github' --exclude='.github/*'
else
    tar -C "$ROOT" \
        --exclude .git --exclude .github --exclude __pycache__ --exclude '*.pyc' \
        -cf - . | tar -x -C "$STAGE" --transform 's,^\./,data-science/atom-memory-postgres/,'
fi

tar -czf "$OUT" -C "$STAGE" .

if tar -tzf "$OUT" | grep -qE '\.pyc$|__pycache__|/\.git/|/\.github/'; then
    echo "архив содержит недопустимые файлы" >&2
    exit 1
fi
echo "архив собран: $OUT"