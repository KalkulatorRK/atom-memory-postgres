# 🧠 Atom Memory for Agents — атомная память на PostgreSQL

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%2B-336791.svg)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-0.5%2B%20(%E2%89%A50.8%20rec.)-316192.svg)](https://github.com/pgvector/pgvector)

**База знаний для LLM-агента, где документы хранятся атомами, а не «целыми книгами».**
Агент отвечает точно, со ссылкой на источник (документ + пункт/страница), и ничего не выдумывает.

> Это скилл Hermes: готовый стек (схема БД + скрипты + процедура) для развёртывания у себя.
> Данные не входят — каждый наполняет базу своими документами.

---

## Установка

### Вариант A — архивом (рекомендуется, работает всегда)

Скачать архив из [последнего релиза](https://github.com/KalkulatorRK/atom-memory-postgres/releases) и распаковать в каталог скиллов:

```bash
curl -L -o ~/atom-memory-skill.tar.gz https://github.com/KalkulatorRK/atom-memory-postgres/releases/latest/download/atom-memory-postgres-skill.tar.gz
tar -xzf ~/atom-memory-skill.tar.gz -C ~/.hermes/skills/
# → ~/.hermes/skills/data-science/atom-memory-postgres/
```

### Вариант B — `hermes skills install` по URL

```bash
hermes skills install https://raw.githubusercontent.com/KalkulatorRK/atom-memory-postgres/main/SKILL.md
```

> ⚠️ Встроенный сканер безопасности (tirith) может заблокировать установку этого скилла из community-источника: скрипт развёртывания легально использует `sudo apt` / `pip install` для подготовки PostgreSQL. Это ложное срабатывание для установочного скилла — используйте вариант A или проверьте источник и доверьтесь ему самостоятельно.

---


> **Поиск.** По умолчанию — **гибрид**: FTS (`ru_en`) + ILIKE + семантика (pgvector). Режим `--mode fts` оставляет только полнотекстовый поиск, как в v1.7. Без `EMBED_API_KEY` (и без явного `EMBED_PROVIDER=local`) векторная ветка выключается с предупреждением. Эмбеддинги считаются отдельным ключом `EMBED_API_KEY`, не через `LLM_API_KEY`. См. `.env.example` и раздел «Приватность» ниже.

## Зачем

Обычный RAG по «чанкам» режет текст вслепую и теряет таблицы, схемы и перекрёстные ссылки («см. рисунок 3» — а он на стр. 20). Итог: агент отвечает «примерно».

Атомная память решает три проблемы сразу:

- ✅ **Точность** — атом = 1–2 целых предложения, таблица или схема целиком; ответ всегда со ссылкой на источник
- ✅ **Связность** — перекрёстные ссылки превращаются в реальные связи между атомами (`atom_links`)
- ✅ **Надёжность** — версии документов, аудит, контроль целостности (sha256)

## Возможности

| Возможность | Как работает |
|---|---|
| Импорт PDF | Конвейер: нормализация → умная резка по предложениям → таблицы/схемы целиком → LLM-обогащение → запись |
| Поиск по-русски | Гибрид FTS `ru_en` + ILIKE + вектор (RRF); точные номера (статья, ГОСТ) не проигрывают семантике |
| Связи атомов | «см. рисунок 3» → `atom_links`, поиск дотягивает схему к ответу |
| Версионирование | Переимпорт = новая версия, старые атомы `superseded` (история сохраняется) |
| Целостность | `content_sha` (sha256) — ответ не соберётся из атомов разных редакций |
| Триггеры Hermes | `память: вопрос`, `#память вопрос`, `memory: вопрос`, `#memory question` — скрипт `memory_trigger.py` распознаёт и запускает поиск |

## Быстрый старт

### 1. Установка БД (PostgreSQL 16+ + pgvector + схема)

```bash
sudo bash scripts/setup_memory_db.sh memory hermes your_password
export PG_DSN="postgresql://hermes:your_password@localhost:5432/memory"
```

> ⚙️ Для слабых VPS скрипт применяет эконом-конфиг (`shared_buffers=128MB` и т.д.).
> Вручную — см. [SKILL.md](SKILL.md), раздел «Развёртывание».

### 2. Зависимости Python

```bash
pip install pymupdf psycopg2 requests
```

### 3. Импорт документа

```bash
python3 scripts/import_document.py --file document.pdf --project "my-project"
# → ✅ Импортировано атомов: 235, связей: 6
```

Без LLM-ключа атомы импортируются без тегов (работает). С ключом — автогаги, сущности, аннотации:

```bash
export LLM_API_KEY="..."   # любой OpenAI-совместимый ключ
export LLM_MODEL="deepseek/deepseek-v4-flash"   # по умолчанию
```

### 4. Поиск

```bash
python3 scripts/memory_query.py "чувствительность ИКИ" --limit 5
```

## Как это работает

```
PDF → [1] разбор (pymupdf) → [2] таблицы/схемы целиком (table_no/fig_no)
    → [3] умная резка по предложениям (300–500 знаков) → [4] quality gate
    → [5] LLM-обогащение (теги, сущности, refs) → [6] транзакция
        sources → versions (sha256) → atoms (+ atom_links)
```

Поиск: гибрид FTS + ILIKE + вектор (RRF) → связанные атомы. Backfill: `python3 scripts/embed_atoms.py --dry-run` (оценка), затем без `--dry-run`.

### Приватность эмбеддингов

Облачный провайдер получает тексты атомов (backfill/импорт) и **текст поискового запроса** в режимах `hybrid`/`vector`. Ключ — только `EMBED_API_KEY`. Для чувствительных проектов: `python3 scripts/embed_atoms.py --set-policy my-project local_only` или `none`. Loopback `EMBED_BASE_URL` (vLLM/Ollama на localhost) не считается внешней отправкой.

## Архитектура БД

```
projects ─┬─ sources ── versions ── atoms (content, metadata jsonb, status)
          │                                │
          │                                ├── atom_links (from_atom → to_atom, rel_type)
          │                                └── embeddings (опционально, vector)
          └── journal (журнал операций)
```

Схема целиком: [`references/schema.sql`](references/schema.sql).

## Стоимость и размеры (реальные замеры)

- 40-страничный ГОСТ → ~235 атомов (149 текст + 24 таблицы + 62 рисунка) за ~1 минуту
- Обогащение DeepSeek: **~0,3 цента за ГОСТ** (кэширование токенов)
- База ~15 МБ на 7 источников — компактно даже для маленького VPS

## Интеграция с Hermes

Скилл ставится как любой другой:

```bash
hermes skills install <url/SKILL.md или архив>
```

После установки агент сам распознаёт триггеры `память:`, `#память`, `memory:` в начале сообщения, выполняет поиск и отвечает со ссылкой на источник.

## Требования

- Linux (Ubuntu 24.04 проверен), Python 3.10+
- PostgreSQL 16+ + pgvector
- LLM API ключ — опционально (для обогащения метаданных)

## Лицензия

MIT
