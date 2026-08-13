---
name: atom-memory-postgres
description: "Развернуть атомную память агента на PostgreSQL 16 + pgvector: схема (7 таблиц), импорт документов (PDF → атомы, таблицы/схемы целиком, LLM-обогащение), поиск FTS по-русски, версионирование и аудит. Загружать, когда пользователь просит развернуть/настроить атомную базу знаний («память агента») на своей машине, перенести стек атомной памяти, или объяснить архитектуру (атомы, atom_links, версии, триггеры поиска)."
version: 1.0.0
author: Hermes Agent + Андрей К
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [память, memory, атомы, postgresql, pgvector, rag, база-знаний]
---

# Атомная память агента (PostgreSQL)

## Overview

База знаний для LLM-агента, где документы (ГОСТы, инструкции, статьи) не хранятся целиком, а **нарезаются на атомы** — неделимые смысловые куски (1–2 предложения, таблица целиком, изображение). Каждый атом — контент + бирка-метаданные (JSONB: страница, пункт, теги, сущности, номера таблиц/рисунков) + статус (`active` / `superseded`). Связи между атомами («см. рисунок 3») — таблица `atom_links`. Поиск: морфология русского и английского (FTS `ru_en`) + фильтры по метаданным. Ответ агента всегда со ссылкой на источник (документ + пункт/страница).

Этот скилл — **переносимый дистрибутив стека**: схема БД + скрипты импорта/поиска + процедура развёртывания. Данные (сами документы) не входят — каждый разворачивает свою базу.

## When to Use

- Пользователь просит «развернуть атомную память / базу знаний агента» на своей машине.
- Нужен точный поиск по 100+ документам с ответами, ссылающимися на источник.
- Перенос стека атомной памяти на другой сервер (не данные, а схему + скрипты).

**НЕ применять** для малых корпусов (<100 документов) — Obsidian + чтение файлов проще и дешевле (оверинжиниринг).

## Требования

- Linux, Python 3.10+, PostgreSQL 16 + pgvector (`sudo apt-get install -y postgresql-16 postgresql-16-pgvector`)
- `pip install pymupdf psycopg2 requests` (в venv агента)
- LLM-ключ для обогащения метаданных — опционально: без него импорт работает, атомы просто остаются без тегов (рекомендуется DeepSeek-совместимый OpenAI endpoint)

## Развёртывание

### 1. Postgres (эконом-конфиг для слабого VPS — проверено)

```bash
sudo apt-get install -y postgresql-16 postgresql-16-pgvector
CONF=/etc/postgresql/16/main/postgresql.conf
sudo sed -i "s/^#*shared_buffers.*/shared_buffers = 128MB/; s/^#*work_mem.*/work_mem = 4MB/; s/^#*maintenance_work_mem.*/maintenance_work_mem = 64MB/; s/^#*max_connections.*/max_connections = 20/; s/^#*effective_cache_size.*/effective_cache_size = 512MB/" $CONF
sudo systemctl restart postgresql
```

### 2. БД + пользователь + права (PG15+: GRANT USAGE — ОБЯЗАТЕЛЕН)

```bash
sudo -u postgres psql -c "CREATE DATABASE memory;"
sudo -u postgres psql -d memory -c "CREATE EXTENSION IF NOT EXISTS vector;"
sudo -u postgres psql <<'EOF'
CREATE ROLE hermes LOGIN PASSWORD 'ваш_пароль';
GRANT ALL PRIVILEGES ON DATABASE memory TO hermes;
GRANT USAGE ON SCHEMA public TO hermes;
GRANT ALL ON ALL TABLES IN SCHEMA public TO hermes;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO hermes;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO hermes;
EOF
```

### 3. Схема (7 таблиц)

```bash
psql "postgresql://hermes:пароль@localhost:5432/memory" -f references/schema.sql
```

Таблицы: `projects → sources → versions → atoms` + `atom_links` + `embeddings` (опц.) + `journal`. Индексы: GIN по `metadata`, GIN FTS `to_tsvector('ru_en', content)` (RU+EN морфология), `idx_links_to`.

### 4. Переменные окружения

```bash
export PG_DSN="postgresql://hermes:пароль@localhost:5432/memory"
# опционально (LLM-обогащение):
export LLM_API_KEY="..."            # или NOUS_API_KEY / ключ любого OpenAI-совместимого API
export LLM_BASE_URL="https://inference-api.nousresearch.com/v1"   # по умолчанию
export LLM_MODEL="deepseek/deepseek-v4-flash"                     # по умолчанию
export MEMORY_ASSETS_DIR="$HOME/memory_import/assets"             # куда класть картинки
```

## Импорт документа

```bash
python3 scripts/import_document.py --file document.pdf --project "my-project"
```

Конвейер: PDF → нормализация (склейка колонок) → таблицы/изображения ЦЕЛИКОМ (с `table_no`/`fig_no`) → умная резка по границам предложений (300–500 симв) → quality gate → LLM-обогащение (батчи, контекст-приписка) → запись одной транзакцией + резолвинг `refs` → `atom_links` (+`normalize_links.py` для сложных ссылок).

Повторный импорт того же файла = **новая версия** (`version_no+1`), старые атомы → `superseded` (не удаляются — история).

## Поиск

```bash
python3 scripts/memory_query.py "чувствительность ИКИ" --limit 5
python3 scripts/memory_query.py "метод контроля" --project "my-project"
```

Логика: FTS по русским и английским стемам (`ru_en`) → если мало результатов, fallback ILIKE по значимым токенам (включая числа). Вывод компактный — агент собирает из него ответ со ссылками.

Интеграция с Hermes: сообщения, начинающиеся с **триггера**, автоматически считаются запросом к базе:

| Триггер | Пример |
|---|---|
| `память:` | `память: чувствительность прибора` |
| `#память` | `#память расшифровка обозначения` |
| `memory:` | `memory: поиск по документу` |
| `#memory` | `#memory sensitivity of the indicator` |

**Код:** `python3 scripts/memory_trigger.py "<сообщение>"` распознаёт триггер и запускает поиск (любой язык: RU/EN); режим `--check` возвращает exit 0/1 — для автоматизации. Слэш-формы `/память` перехватывает шлюз — НЕ работают.

## Версионирование и аудит

- Атомы привязаны к `version_id`; `content_sha` = sha256(content+metadata) — контроль «ответ не собран из атомов разных версий» (`SELECT count(DISTINCT version_id) FROM atoms WHERE id IN (...)` должно быть 1).
- Проверка здоровья базы (вручную или cron):
  - дубликаты контента → смёрджить;
  - битые `atom_links` (`to_atom` не найден) → пересоздать;
  - атомы без тегов, начинающиеся с середины слова → проблема резки, не LLM;
  - осиротевшие атомы (0 запросов за N дней) → кандидаты на удаление.
- Журнал операций — таблица `journal` (кто/что/когда импортировал).

## Common Pitfalls

1. **PG15+ без `GRANT USAGE ON SCHEMA public`** → `permission denied for table atoms` даже после `GRANT ALL ON DATABASE`.
2. **Таблицы/схемы резать нельзя** — извлекать целиком с `table_no`/`fig_no`, иначе перекрёстные ссылки «см. рисунок 3» теряются.
3. **Твёрдая резка по символам даёт обрывки** («рован...») — резать только по границам предложений; атомы <300 симв мёрджить с соседом.
4. **Пустой ответ LLM на больших батчах** — модель тратит токены на reasoning и не дописывает JSON: батчи по 3–5, `max_tokens=2500`, ретрай 3×, проверка `isinstance(parsed, list)`.
5. **Docling (IBM) на слабом VPS умирает** — тянет CUDA/трансформеры и OOM. Использовать pymupdf; Docling — только на машинах с GPU/большой RAM.
6. **DeepSeek без браузерного User-Agent** → Cloudflare 403. В скрипте UA уже стоит; при своём endpoint проверяйте.
7. **fallback без LLM-ключа** — атомы импортируются без тегов; после получения ключа дообогащение: `python3 scripts/reenrich_atoms.py --source <id> --batch 3`.
8. **Секреты** — никогда не хардкодить пароль БД в скриптах, только `PG_DSN` в env.

## Verification Checklist

- [ ] `psql "$PG_DSN" -c "SELECT 1"` — подключение работает
- [ ] `\dt` показывает 7 таблиц (projects, sources, versions, atoms, atom_links, embeddings, journal)
- [ ] Импорт: «✅ Импортировано атомов: N, связей: M»
- [ ] Поиск: `memory_query.py "тест"` возвращает атомы со ссылкой на источник
- [ ] Повторный импорт: `version_no` увеличился, старые атомы `superseded`
- [ ] `free -h` — Postgres не съел всю память (эконом-конфиг)

## Связь с другими скиллами

- `memory-atom-import` / `memory-query` — рабочие скиллы этой же системы в нашем окружении (с хардкодом путей)
- `agent-memory-architecture` — теория: почему атомы, метаданные-first, ёмкость, RAG 3.0
