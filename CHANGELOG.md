# Журнал изменений

## 1.10.0

- **VS-14:** модуль `scripts/structure.py` — структурная нарезка кодексов и ГОСТ/СДАНК (`--doc-kind auto|code|gost|sdank|none`); жёсткие границы статьи/пункта/раздела; колонтитулы не становятся заголовками.
- **VS-15:** метаданные `law`, `article`, `point`, `section_path`, `redaction`, `effective_date`; параметры импорта `--redaction`, `--effective-date`; формат цитаты в CLI/MCP JSON; фильтры поиска `--law`, `--doc-kind`, `--as-of`.
- **Security:** отклонение имён ролей `pg_*` и NUL в `render_role_password_sql.py`; `SET log_statement = none` на сеанс CREATE/ALTER ROLE; проверка в setup.
- **Note:** `embed_atoms.py --prune-superseded` удаляет эмбеддинги superseded-версий; `--as-of` в режиме `vector` по старым редакциям может ничего не найти без повторного embed.

## 1.9.1

- **Fix:** `setup_memory_db.sh` без `ADMIN_DSN` снова создаёт роль через `admin_psql` + `render_role_password_sql.py` (stdlib), без psycopg2 от root.
- **Security:** пароль роли — `format()`/`\gexec` без `DO $$` (инъекция psql `\!`); тесты `test_setup_role_security.py`.
- **Security:** `vector_index_admin.sh` — единицы `kB`/MB/GB/TB и диапазон mem; DROP только после успешного SET в одном сеансе.
- Третий аргумент пароля setup — deprecated; удалён неиспользуемый `set_db_role_password.py`.
- `db_dsn.py`: DSN с query-string (`?sslmode=`) для admin/migration/vector_index.
- `vector_index_admin.sh`: строгая проверка `--mem`/`--dims`; DROP только после валидации.
- Зависимость `mcp>=1,<2`; migration-тесты в CI не skip при ошибке ADMIN_DSN; CI job setup без ADMIN_DSN.
- MCP JSON-RPC `memory_search`: **всегда JSON-массив** по умолчанию; warnings в stderr или opt-in `include_warnings` / `ATOM_MEMORY_MCP_INCLUDE_WARNINGS=1`.
- `vector_index_admin.sh`: SET и CREATE INDEX в одном сеансе psql; валидация `--m`, `--ef-construction`, `--mem`.
- Откат `0004_vector_search_down.sql` идемпотентен; снимок `content_hash`/`embed_meta` — без лишнего re-embed после повторного 0004.
- `setup_memory_db.sh`: повторный запуск пропускает `schema.sql`, если есть `atoms`; пароль роли через `render_role_password_sql.py` + `MEMORY_DB_PASSWORD`.
- CLI `--json` / `--explain` работают в режиме `--mode fts`.
- FastMCP: восстановлены docstring инструментов; `scripts/calibrate_min_sim.py` и `docs/SECURITY.md` (ротация пароля).

## 1.9.0

- Семантический поиск: провайдеры эмбеддингов (облако OpenAI-compatible по умолчанию, local по объявлению, fake в тестах).
- Миграция `0004_vector_search.sql` (HNSW, `embed_policy`, откат `0004_vector_search_down.sql`).
- `scripts/embed_atoms.py` (backfill, dry-run, политика проектов), интеграция с импортом (`--no-embed`).
- Гибридный поиск `scripts/search_core.py` (FTS + ILIKE + vector, RRF, ярус точных идентификаторов).
- CLI `--mode fts|vector|hybrid`, MCP-параметр `mode`, расширенный `memory_stats`.
- MCP JSON-RPC `memory_search`: массив хитов по умолчанию (1.8); объект с warnings — opt-in (см. 1.9.1).
- `scripts/eval_search.py`, `scripts/bench_search.py`, `scripts/vector_index_admin.sh`, CI с `EMBED_PROVIDER=fake`.

## 1.8.0

- P0-1: таблицы вырезаются из текста по позиции строк, а не через `str.replace` по содержимому — ячейка «2» больше не стирает числа из обычного текста страницы.
- P0-2: `reenrich_atoms` находит атомы с отсутствующим ключом `tags` (`metadata IS NULL`, `tags: null`, `tags: []`).
- P0-3: резолвер ссылок учитывает тип: «таблица 1» привязывается только к атому-таблице, «рис. 1» — только к рисунку, детерминированно.
- P0-4: охрана разрушающих тестов `scripts/tests/_db_guard.py` — явный opt-in, строгое имя базы, сравнение с рабочей БД по фактам сервера, а не по строке DSN.
- P1-1: MCP-фолбэк соблюдает JSON-RPC 2.0 (коды -32700/-32600/-32601/-32602/-32603, уведомления без ответа, `ping`).
- P1-2: один список стоп-слов и одна функция токенизации в `_common.py`.
- P1-3: версия из одного источника — файл `VERSION`, `serverInfo.version` и User-Agent читают его.
- P1-4: убраны жёсткие «PostgreSQL 16», версия определяется автоматически.
- P1-5: связи между атомами подтягиваются одним запросом (не N+1); резолвинг ссылок при импорте — одной картой на версию и пакетной вставкой.
- CI: `scripts/build_skill_archive.sh`, `scripts/check_version.py`, `pyproject.toml`, `requirements-dev.txt`.

## 1.7.0

- Регрессия CLI-поиска (TypeError в ILIKE-доборе). Пустой tsquery не вызывает FTS. Точное сравнение имени проекта в MCP.

## 1.6.0

- Подписи рисунков по строке, а не по блоку. Поиск учитывает `--project` в доборе. Убраны `.pyc`, добавлен `.gitignore`.

## 1.5.0

- Установка по README без двойной вложенности. Импорт файла в другой проект — понятная ошибка. Версия Postgres, права роли, логирование ошибок, поиск по индексу.