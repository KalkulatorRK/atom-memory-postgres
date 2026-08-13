# 🧠 Atom Memory for Agents — атомная память на PostgreSQL

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%2B-336791.svg)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-0.7%2B-316192.svg)](https://github.com/pgvector/pgvector)

**База знаний для LLM-агента, где документы хранятся атомами, а не «целыми книгами».**
Агент отвечает точно, со ссылкой на источник (документ + пункт/страница), и ничего не выдумывает.

> Это скилл Hermes: готовый стек (схема БД + скрипты + процедура) для развёртывания у себя.
> Данные не входят — каждый наполняет базу своими документами.

---

## Установка

### Вариант A — архивом (рекомендуется, работает всегда)

Скачать архив из [последнего релиза](https://github.com/KalkulatorRK/atom-memory-postgres/releases) и распаковать в каталог скиллов:

```bash
curl -L -o ~/atom-memory-skill.tar.gz https://github.com/KalkulatorRK/atom-memory-postgres/releases/download/v1.0.0/atom-memory-postgres-skill.tar.gz
tar -xzf ~/atom-memory-skill.tar.gz -C ~/.hermes/skills/
# → ~/.hermes/skills/data-science/atom-memory-postgres/
```

### Вариант B — `hermes skills install` по URL

```bash
hermes skills install https://raw.githubusercontent.com/KalkulatorRK/atom-memory-postgres/main/SKILL.md
```

> ⚠️ Встроенный сканер безопасности (tirith) может заблокировать установку этого скилла из community-источника: скрипт развёртывания легально использует `sudo apt` / `pip install` для подготовки PostgreSQL. Это ложное срабатывание для установочного скилла — используйте вариант A или проверьте источник и доверьтесь ему самостоятельно.

---

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
| Поиск по-русски | Морфология (FTS `to_tsvector('russian')`) + fallback по числам/токенам |
| Связи атомов | «см. рисунок 3» → `atom_links`, поиск дотягивает схему к ответу |
| Версионирование | Переимпорт = новая версия, старые атомы `superseded` (история сохраняется) |
| Целостность | `content_sha` (sha256) — ответ не соберётся из атомов разных редакций |
| Триггеры Hermes | `память: вопрос`, `#память вопрос`, `memory: вопрос`, `#memory question` — скрипт `memory_trigger.py` распознаёт и запускает поиск |

## Быстрый старт

### 1. Установка БД (Postgres 16 + pgvector + схема)

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

Поиск: фильтры по метаданным (проект/теги/тип) → FTS русская морфология → связанные атомы.

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
- PostgreSQL 16 + pgvector
- LLM API ключ — опционально (для обогащения метаданных)

## Лицензия

MIT
