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
if [ "$DIMS" -gt 2000 ] 2>/dev/null; then
  echo "dims > 2000: нужен halfvec (pgvector ≥ 0.7)"
  exit 1
fi

slug=$(echo "$MODEL" | tr ':/.' '_' | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9_]/_/g;s/__*/_/g;s/^_\|_$//g')
IDX="idx_emb_hnsw_${slug}_${DIMS}"

if [ -n "${ADMIN_DSN:-}" ]; then
  PSQL=(psql "$ADMIN_DSN")
elif [ "$(id -u)" -eq 0 ]; then
  PSQL=(sudo -u postgres psql -d "${PGDATABASE:-memory}")
else
  echo "Задайте ADMIN_DSN или запускайте от root/postgres"
  exit 1
fi

if [ "$DROP" -eq 1 ]; then
  "${PSQL[@]}" -v ON_ERROR_STOP=1 -c "DROP INDEX IF EXISTS public.\"$IDX\";"
fi

SQL="SET maintenance_work_mem = '${MEM}'; SET max_parallel_maintenance_workers = ${MPW}; CREATE INDEX CONCURRENTLY IF NOT EXISTS ${IDX} ON public.embeddings USING hnsw ((vector::public.vector(${DIMS})) public.vector_cosine_ops) WITH (m = ${M}, ef_construction = ${EFC}) WHERE model = '${MODEL}' AND dims = ${DIMS};"

"${PSQL[@]}" -v ON_ERROR_STOP=1 -c "$SQL"
echo "готово: $IDX"
