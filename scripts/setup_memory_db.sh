#!/usr/bin/env bash
# Развёртывание атомной памяти агента: PostgreSQL 16+ + pgvector + БД + схема + права.
# Использование: sudo bash setup_memory_db.sh [db_name] [db_user] [db_password]
# Пример:        sudo bash setup_memory_db.sh memory hermes my_secret_pass
#
# Пароль передаётся аргументом (виден в `ps` на время выполнения) — для продакшена
# лучше задавать его через .pgpass. В SQL он уходит параметром, не конкатенацией.
set -euo pipefail

DB_NAME="${1:-memory}"
DB_USER="${2:-hermes}"
DB_PASS="${3:-}"

if [ -z "$DB_PASS" ]; then
    echo "Использование: $0 [db_name] [db_user] [db_password]"
    exit 1
fi

# Имена — только буквы/цифры/подчёркивание: они идут в SQL как идентификаторы.
ident='^[a-zA-Z_][a-zA-Z0-9_]*$'
if ! [[ "$DB_NAME" =~ $ident && "$DB_USER" =~ $ident ]]; then
    echo "Имя БД и пользователя: только латиница, цифры и подчёркивание."
    exit 1
fi

if [ -n "${ADMIN_DSN:-}" ]; then
  PSQL_ADMIN=(psql "$ADMIN_DSN")
elif [ "$(id -un)" = "postgres" ]; then
  PSQL_ADMIN=(psql)
else
  PSQL_ADMIN=(sudo -u postgres psql)
fi
if [ -n "${SETUP_SKIP_INSTALL:-}" ]; then
  if [ -z "$DB_PASS" ] && [ -n "${MEMORY_DB_PASSWORD:-}" ]; then
    DB_PASS="$MEMORY_DB_PASSWORD"
  fi
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
# Расширение vector — в целевой БД от суперпользователя; роль приложения CREATE не получает.
if ! "${PSQL_ADMIN[@]}" -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  "${PSQL_ADMIN[@]}" -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${DB_NAME}\""
fi
if ! "${PSQL_ADMIN[@]}" -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
  "${PSQL_ADMIN[@]}" -v ON_ERROR_STOP=1 \
    -v db_user="$DB_USER" -v db_pass="$DB_PASS" \
    -c "CREATE ROLE \"${DB_USER}\" LOGIN PASSWORD '${DB_PASS}'"
else
  "${PSQL_ADMIN[@]}" -v ON_ERROR_STOP=1 -c "ALTER ROLE \"${DB_USER}\" PASSWORD '${DB_PASS}'"
fi
"${PSQL_ADMIN[@]}" -v ON_ERROR_STOP=1 \
  -v db_name="$DB_NAME" -v db_user="$DB_USER" <<'SQL'
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', :'db_name', :'db_user') \gexec
SQL
"${PSQL_ADMIN[@]}" -d "$DB_NAME" -v ON_ERROR_STOP=1 -v db_user="$DB_USER" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'db_user') \gexec
SQL

echo "[4/4] Применение схемы..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA="$SCRIPT_DIR/../references/schema.sql"
# Схему применяет суперпользователь: в дампе есть CREATE EXTENSION и объекты,
# которые роль приложения создать не может. -v ON_ERROR_STOP=1 обязателен —
# без него psql возвращает 0 даже при ошибках, и set -e их не ловит.
"${PSQL_ADMIN[@]}" -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$SCHEMA"
for MIGRATION in "$SCRIPT_DIR"/../references/migrations/*.sql; do
    [ -f "$MIGRATION" ] || continue
    case "$MIGRATION" in
      *_down.sql) continue ;;
    esac
    "${PSQL_ADMIN[@]}" -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$MIGRATION"
done

# Права на созданные объекты — отдельным шагом, после того как таблицы есть.
"${PSQL_ADMIN[@]}" -d "$DB_NAME" -v ON_ERROR_STOP=1 -v db_user="$DB_USER" <<'SQL'
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', :'db_user') \gexec
SELECT format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', :'db_user') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', :'db_user') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO %I', :'db_user') \gexec
SQL

echo ""
echo "Готово. Задайте строку подключения (пароль в неё подставьте сами):"
echo "  export PG_DSN=\"postgresql://$DB_USER@localhost:5432/$DB_NAME\""
echo "Проверка: psql \"\$PG_DSN\" -c \"SELECT count(*) FROM pg_tables WHERE schemaname='public'\""

# Доп. HNSW для не-дефолтного пространства (если задано в окружении)
if [ -n "${EMBED_PROVIDER:-}" ] && [ "${EMBED_PROVIDER}" = "local" ] && [ -n "${EMBED_LOCAL_MODEL:-}" ]; then
  bash "$SCRIPT_DIR/vector_index_admin.sh" --model "local:multilingual-e5-base" --dims "${EMBED_DIMS:-768}" || true
fi
