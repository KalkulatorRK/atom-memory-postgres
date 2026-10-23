# Безопасность

## Пароли и секреты

- Не коммитьте реальные пароли БД, `EMBED_API_KEY` и другие секреты в репозиторий.
- Строка подключения `PG_DSN` храните в `~/.hermes/.env` или переменных окружения на сервере.
- Установка БД: задайте пароль приложения через **`MEMORY_DB_PASSWORD`**, а не третьим аргументом в shell (чтобы не попадал в history):

```bash
export MEMORY_DB_PASSWORD='ваш_секрет'
sudo -E env SETUP_SKIP_INSTALL=1 bash scripts/setup_memory_db.sh memory hermes
```

Пароль роли записывается через временный SQL-файл и `admin_psql` (суперпользователь), без `-v db_pass` в argv `psql`.

### Ротация пароля

Если пароль production-БД когда-либо попадал в git (в том числе в старых коммитах), **смените пароль роли PostgreSQL** и обновите `PG_DSN` на всех хостах. Переписывать историю git не требуется.

Интерактивно (пароль не попадает в argv и history):

```bash
sudo -u postgres psql -d postgres
# в psql:
\password hermes
```
