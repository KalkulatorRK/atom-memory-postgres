#!/usr/bin/env bash
# Развёртывание атомной памяти агента: Postgres 16 + pgvector + БД + схема + права.
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

echo "[1/4] Установка PostgreSQL 16 + pgvector..."
apt-get update -y
apt-get install -y postgresql-16 postgresql-16-pgvector

echo "[2/4] Эконом-конфиг (для слабых VPS; на мощных машинах можно пропустить)..."
CONF=/etc/postgresql/16/main/postgresql.conf
sed -i "s/^#*shared_buffers.*/shared_buffers = 128MB/" "$CONF"
sed -i "s/^#*work_mem.*/work_mem = 4MB/" "$CONF"
sed -i "s/^#*maintenance_work_mem.*/maintenance_work_mem = 64MB/" "$CONF"
sed -i "s/^#*max_connections.*/max_connections = 20/" "$CONF"
sed -i "s/^#*effective_cache_size.*/effective_cache_size = 512MB/" "$CONF"
systemctl restart postgresql

echo "[3/4] Создание БД $DB_NAME и пользователя $DB_USER..."
# Расширение vector — в целевой БД и от суперпользователя: pgvector не trusted,
# роль приложения его не создаст. CREATE на public выдаётся явно — с PG15 схема
# public принадлежит pg_database_owner, и GRANT USAGE одной недостаточно.
sudo -u postgres psql -v ON_ERROR_STOP=1 \
    -v db_name="$DB_NAME" -v db_user="$DB_USER" -v db_pass="$DB_PASS" <<'SQL'
SELECT format('CREATE DATABASE %I', :'db_name') \gexec
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'db_user', :'db_pass') \gexec
SELECT format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', :'db_name', :'db_user') \gexec
SQL
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -v db_user="$DB_USER" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
SELECT format('GRANT USAGE, CREATE ON SCHEMA public TO %I', :'db_user') \gexec
SQL

echo "[4/4] Применение схемы..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA="$SCRIPT_DIR/../references/schema.sql"
# Схему применяет суперпользователь: в дампе есть CREATE EXTENSION и объекты,
# которые роль приложения создать не может. -v ON_ERROR_STOP=1 обязателен —
# без него psql возвращает 0 даже при ошибках, и set -e их не ловит.
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$SCHEMA"

# Права на созданные объекты — отдельным шагом, после того как таблицы есть.
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -v db_user="$DB_USER" <<'SQL'
SELECT format('GRANT ALL ON ALL TABLES IN SCHEMA public TO %I', :'db_user') \gexec
SELECT format('GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO %I', :'db_user') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO %I', :'db_user') \gexec
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO %I', :'db_user') \gexec
SQL

echo ""
echo "Готово. Задайте строку подключения (пароль в неё подставьте сами):"
echo "  export PG_DSN=\"postgresql://$DB_USER@localhost:5432/$DB_NAME\""
echo "Проверка: psql \"\$PG_DSN\" -c \"SELECT count(*) FROM pg_tables WHERE schemaname='public'\""
