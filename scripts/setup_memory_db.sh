#!/usr/bin/env bash
# Развёртывание атомной памяти агента: PostgreSQL 16+ + pgvector + БД + схема + права.
# Использование: sudo bash setup_memory_db.sh [db_name] [db_user] [db_password]
# CI: SETUP_SKIP_INSTALL=1 и ADMIN_DSN=postgresql://postgres:pass@localhost:5432/postgres
set -euo pipefail

DB_NAME="${1:-memory}"
DB_USER="${2:-hermes}"
DB_PASS="${3:-}"

if [ -z "$DB_PASS" ]; then
    if [ -n "${MEMORY_DB_PASSWORD:-}" ]; then
        DB_PASS="$MEMORY_DB_PASSWORD"
    else
        echo "Использование: $0 [db_name] [db_user] [db_password]"
        exit 1
    fi
fi

ident='^[a-zA-Z_][a-zA-Z0-9_]*$'
if ! [[ "$DB_NAME" =~ $ident && "$DB_USER" =~ $ident ]]; then
    echo "Имя БД и пользователя: только латиница, цифры и подчёркивание."
    exit 1
fi

# DSN суперпользователя для конкретной базы (в CI — TCP, без unix-socket).
admin_psql() {
    local db="${1:-postgres}"
    shift
    if [ -n "${ADMIN_DSN:-}" ]; then
        local base="${ADMIN_DSN%/*}"
        psql "${base}/${db}" "$@"
    elif [ "$(id -un)" = "postgres" ]; then
        psql -d "$db" "$@"
    else
        sudo -u postgres psql -d "$db" "$@"
    fi
}

if [ -n "${SETUP_SKIP_INSTALL:-}" ]; then
  echo "[1/4] Пропуск установки (SETUP_SKIP_INSTALL=1)"
  echo "[2/4] Пропуск тюнинга конфига"
else
  echo "[1/4] Установка PostgreSQL + pgvector..."
  PG_VERSION="${PG_VERSION:-}"
  if [ -z "$PG_VERSION" ] && command -v pg_lsclusters >/dev/null; then
    PG_VERSION=$(pg_lsclusters --no-header | awk '{print $1; exit}')
  fi
  apt-get update -y
  if [ -z "$PG_VERSION" ]; then
    apt-get install -y postgresql
    PG_VERSION=$(pg_lsclusters --no-header | awk '{print $1; exit}')
  else
    apt-get install -y "postgresql-$PG_VERSION"
  fi
  apt-get install -y "postgresql-$PG_VERSION-pgvector" || {
    echo "Собрать pgvector вручную: https://github.com/pgvector/pgvector"; exit 1; }
  echo "      PostgreSQL $PG_VERSION"

  echo "[2/4] Эконом-конфиг (для слабых VPS; на мощных машинах можно пропустить)..."
  CONF="/etc/postgresql/$PG_VERSION/main/postgresql.conf"
  if [ -f "$CONF" ]; then
    sed -i "s/^#*shared_buffers.*/shared_buffers = 128MB/" "$CONF"
    sed -i "s/^#*work_mem.*/work_mem = 4MB/" "$CONF"
    sed -i "s/^#*maintenance_work_mem.*/maintenance_work_mem = 64MB/" "$CONF"
    sed -i "s/^#*max_connections.*/max_connections = 20/" "$CONF"
    sed -i "s/^#*effective_cache_size.*/effective_cache_size = 512MB/" "$CONF"
  fi
  if command -v systemctl >/dev/null && systemctl is-system-running >/dev/null 2>&1; then
    systemctl restart postgresql
  elif command -v pg_ctlcluster >/dev/null; then
    pg_ctlcluster "$PG_VERSION" main restart
  fi
fi

echo "[3/4] Создание БД $DB_NAME и пользователя $DB_USER..."
if ! admin_psql postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  admin_psql postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${DB_NAME}\""
fi
if ! admin_psql postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
  admin_psql postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE \"${DB_USER}\" LOGIN PASSWORD '${DB_PASS}'"
else
  admin_psql postgres -v ON_ERROR_STOP=1 -c "ALTER ROLE \"${DB_USER}\" PASSWORD '${DB_PASS}'"
fi
admin_psql postgres -v ON_ERROR_STOP=1 \
  -v db_name="$DB_NAME" -v db_user="$DB_USER" <<'SQL'
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', :'db_name', :'db_user') \gexec
SQL
admin_psql "$DB_NAME" -v ON_ERROR_STOP=1 -v db_user="$DB_USER" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'db_user') \gexec
SQL

echo "[4/4] Применение схемы..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA="$SCRIPT_DIR/../references/schema.sql"
admin_psql "$DB_NAME" -v ON_ERROR_STOP=1 -f "$SCHEMA"
for MIGRATION in "$SCRIPT_DIR"/../references/migrations/*.sql; do
    [ -f "$MIGRATION" ] || continue
    case "$MIGRATION" in
      *_down.sql) continue ;;
    esac
    admin_psql "$DB_NAME" -v ON_ERROR_STOP=1 -f "$MIGRATION"
done

admin_psql "$DB_NAME" -v ON_ERROR_STOP=1 -v db_user="$DB_USER" <<'SQL'
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', :'db_user') \gexec
SELECT format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', :'db_user') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', :'db_user') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO %I', :'db_user') \gexec
SQL

echo ""
echo "Готово. Задайте строку подключения (пароль в неё подставьте сами):"
echo "  export PG_DSN=\"postgresql://$DB_USER@localhost:5432/$DB_NAME\""
echo "Проверка: psql \"\$PG_DSN\" -c \"SELECT count(*) FROM pg_tables WHERE schemaname='public'\""

if [ -n "${EMBED_PROVIDER:-}" ] && [ "${EMBED_PROVIDER}" = "local" ] && [ -n "${EMBED_LOCAL_MODEL:-}" ]; then
  bash "$SCRIPT_DIR/vector_index_admin.sh" --model "local:multilingual-e5-base" --dims "${EMBED_DIMS:-768}" || true
fi
