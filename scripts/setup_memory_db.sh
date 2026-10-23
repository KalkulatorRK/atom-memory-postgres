#!/usr/bin/env bash
# Развёртывание атомной памяти агента: PostgreSQL 16+ + pgvector + БД + схема + права.
# Использование: sudo bash setup_memory_db.sh [db_name] [db_user] [db_password]
# CI: SETUP_SKIP_INSTALL=1 и ADMIN_DSN=postgresql://postgres:pass@localhost:5432/postgres
set -euo pipefail

DB_NAME="${1:-memory}"
DB_USER="${2:-hermes}"
DB_PASS="${3:-}"

if [ -n "$DB_PASS" ]; then
    echo "Предупреждение: пароль в argv ($0 … [db_password]) виден в ps; используйте MEMORY_DB_PASSWORD." >&2
elif [ -n "${MEMORY_DB_PASSWORD:-}" ]; then
    DB_PASS="$MEMORY_DB_PASSWORD"
else
    echo "Использование: MEMORY_DB_PASSWORD=… $0 [db_name] [db_user]"
    echo "  (устарело: третий аргумент [db_password] — только для совместимости)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ident='^[a-zA-Z_][a-zA-Z0-9_]*$'
if ! [[ "$DB_NAME" =~ $ident && "$DB_USER" =~ $ident ]]; then
    echo "Имя БД и пользователя: только латиница, цифры и подчёркивание."
    exit 1
fi
if [[ "$DB_USER" == pg_* ]] || [[ "$DB_USER" == PG_* ]]; then
    echo "Имя пользователя не может начинаться с pg_/PG_ (зарезервировано PostgreSQL)."
    exit 1
fi

# DSN суперпользователя для конкретной базы (CI: ADMIN_DSN; иначе peer через postgres OS user).
admin_psql() {
    local db="${1:-postgres}"
    shift
    if [ -n "${ADMIN_DSN:-}" ]; then
        local url
        url="$(DB_NAME="$db" ADMIN_DSN="$ADMIN_DSN" python3 "$SCRIPT_DIR/db_dsn.py" admin-url)"
        psql "$url" "$@"
    elif [ "$(id -un)" = "postgres" ]; then
        psql -d "$db" "$@"
    else
        sudo -u postgres env PGHOST="${PGHOST:-}" PGPORT="${PGPORT:-}" psql -d "$db" "$@"
    fi
}

set_db_role_password() {
  local sql
  sql="$(DB_USER="$DB_USER" MEMORY_DB_PASSWORD="$DB_PASS" python3 "$SCRIPT_DIR/render_role_password_sql.py")"
  # SET LOCAL может быть недоступен CREATEROLE — не роняем setup; SCRAM уже без plaintext.
  if ! printf '%s\n' "$sql" | admin_psql postgres -v ON_ERROR_STOP=1 -f -; then
    printf '%s\n' "$sql" | admin_psql postgres -f - || return 1
  fi
}

# postgres OS user (sudo) не читает файлы в $HOME runner — подаём SQL через stdin.
admin_psql_file() {
  local db="$1"
  local file="$2"
  cat "$file" | admin_psql "$db" -v ON_ERROR_STOP=1 -f -
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
set_db_role_password
if ! admin_psql postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  admin_psql postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${DB_NAME}\""
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
SCHEMA="$SCRIPT_DIR/../references/schema.sql"
if admin_psql "$DB_NAME" -tAc "SELECT to_regclass('public.atoms') IS NOT NULL" | grep -q t; then
  echo "      База уже инициализирована — пропуск schema.sql (без потери данных)"
else
  admin_psql_file "$DB_NAME" "$SCHEMA"
fi
for MIGRATION in "$SCRIPT_DIR"/../references/migrations/*.sql; do
    [ -f "$MIGRATION" ] || continue
    case "$MIGRATION" in
      *_down.sql) continue ;;
    esac
    admin_psql_file "$DB_NAME" "$MIGRATION"
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
