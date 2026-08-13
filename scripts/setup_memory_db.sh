#!/usr/bin/env bash
# Развёртывание атомной памяти агента: Postgres 16 + pgvector + БД + схема + права.
# Использование: sudo bash setup_memory_db.sh [db_name] [db_user] [db_password]
# Пример:        sudo bash setup_memory_db.sh memory hermes my_secret_pass
set -euo pipefail

DB_NAME="${1:-memory}"
DB_USER="${2:-hermes}"
DB_PASS="${3:-}"

if [ -z "$DB_PASS" ]; then
    echo "Использование: $0 [db_name] [db_user] [db_password]"
    exit 1
fi

echo "[1/4] Установка PostgreSQL 16 + pgvector..."
apt-get update -y
apt-get install -y postgresql-16 postgresql-16-pgvector

echo "[2/4] Эконом-конфиг (для слабых VPS; на мощных машинах можно пропустить)..."
CONF=/etc/postgresql/16/main/postgresql.conf
sed -i "s/^#*shared_buffers.*/shared_buffers = 128MB/" $CONF
sed -i "s/^#*work_mem.*/work_mem = 4MB/" $CONF
sed -i "s/^#*maintenance_work_mem.*/maintenance_work_mem = 64MB/" $CONF
sed -i "s/^#*max_connections.*/max_connections = 20/" $CONF
sed -i "s/^#*effective_cache_size.*/effective_cache_size = 512MB/" $CONF
systemctl restart postgresql

echo "[3/4] Создание БД $DB_NAME и пользователя $DB_USER..."
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
CREATE DATABASE $DB_NAME;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASS';
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
SQL
sudo -u postgres psql -d $DB_NAME -v ON_ERROR_STOP=1 <<SQL
GRANT USAGE ON SCHEMA public TO $DB_USER;
GRANT ALL ON ALL TABLES IN SCHEMA public TO $DB_USER;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DB_USER;
SQL

echo "[4/4] Применение схемы (7 таблиц)..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA="$SCRIPT_DIR/../references/schema.sql"
PGPASSWORD="$DB_PASS" psql -h localhost -U "$DB_USER" -d "$DB_NAME" -f "$SCHEMA"

echo ""
echo "Готово. Теперь экспортируйте в окружение:"
echo "  export PG_DSN=\"postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME\""
echo "Проверка: psql \"\$PG_DSN\" -c \"SELECT 1\""
