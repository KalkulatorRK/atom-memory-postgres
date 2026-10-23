#!/usr/bin/env bash
# Создание HNSW-индекса для пространства эмбеддингов (postgres / ADMIN_DSN).
set -euo pipefail

MODEL=""
DIMS=""
M=16
EFC=64
MEM="1GB"
MPW=2
DROP=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "Usage: $0 --model cloud:text-embedding-3-small --dims 768 [--m 16] [--ef-construction 64] [--mem 1GB] [--drop]"
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --dims) DIMS="$2"; shift 2 ;;
    --m) M="$2"; shift 2 ;;
    --ef-construction) EFC="$2"; shift 2 ;;
    --mem) MEM="$2"; shift 2 ;;
    --drop) DROP=1; shift ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1"; usage ;;
  esac
done

[ -n "$MODEL" ] && [ -n "$DIMS" ] || usage

if ! [[ "$MODEL" =~ ^[a-z]+:[A-Za-z0-9._/-]+$ ]]; then
  echo "model не прошёл проверку regex"
  exit 1
fi
if ! [[ "$DIMS" =~ ^[0-9]+$ ]]; then
  echo "dims должен быть целым числом"
  exit 1
fi
if [ "$DIMS" -lt 1 ] 2>/dev/null || [ "$DIMS" -gt 2000 ] 2>/dev/null; then
  echo "dims: целое от 1 до 2000"
  exit 1
fi
if ! [[ "$M" =~ ^[0-9]+$ ]] || [ "$M" -lt 2 ] || [ "$M" -gt 100 ]; then
  echo "--m: целое от 2 до 100"
  exit 1
fi
if ! [[ "$EFC" =~ ^[0-9]+$ ]] || [ "$EFC" -lt 4 ] || [ "$EFC" -gt 1000 ]; then
  echo "--ef-construction: целое от 4 до 1000"
  exit 1
fi
if ! [[ "$MPW" =~ ^[0-9]+$ ]]; then
  echo "max_parallel_maintenance_workers: целое"
  exit 1
fi

MEM="$(python3 "$SCRIPT_DIR/vector_index_validate.py" "$MEM")" || exit 1

IDX=$(MODEL="$MODEL" DIMS="$DIMS" SCRIPT_DIR="$SCRIPT_DIR" python3 -c "
import os, sys
sys.path.insert(0, os.environ['SCRIPT_DIR'])
from vector_index import hnsw_index_name
print(hnsw_index_name(os.environ['MODEL'], int(os.environ['DIMS'])))
")

if [ -n "${ADMIN_DSN:-}" ]; then
  psql_admin() {
    local db="$1"
    shift
    local url
    url="$(DB_NAME="$db" ADMIN_DSN="$ADMIN_DSN" python3 "$SCRIPT_DIR/db_dsn.py" admin-url)"
    psql "$url" "$@"
  }
elif [ "$(id -un)" = "postgres" ]; then
  psql_admin() { psql -d "$1" "${@:2}"; }
else
  psql_admin() { sudo -u postgres psql -d "$1" "${@:2}"; }
fi

DB="${PGDATABASE:-memory}"

if [ "$DROP" -eq 1 ]; then
  psql_admin "$DB" -v ON_ERROR_STOP=1 -c "DROP INDEX IF EXISTS public.\"$IDX\";"
fi

psql_admin "$DB" -v ON_ERROR_STOP=1 \
  -v model="$MODEL" -v dims="$DIMS" -v m="$M" -v efc="$EFC" -v idx="$IDX" <<SQL
SET maintenance_work_mem = '${MEM}';
SET max_parallel_maintenance_workers = ${MPW};
SELECT format(
  'CREATE INDEX CONCURRENTLY IF NOT EXISTS %I ON public.embeddings USING hnsw ((vector::public.vector(%s)) public.vector_cosine_ops) WITH (m = %s, ef_construction = %s) WHERE model = %L AND dims = %s',
  :'idx', :'dims', :'m', :'efc', :'model', :'dims'
) \\gexec
SQL

echo "готово: $IDX"
