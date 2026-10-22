-- Дополнительные индексы поверх схемы 0001. Идемпотентно: можно гонять повторно.
-- Применять от суперпользователя: роль приложения не владеет таблицами.
--   sudo -u postgres psql -d <db> -v ON_ERROR_STOP=1 -f references/migrations/0002_indexes.sql
-- setup_memory_db.sh применяет этот файл сам.

-- Хранимый tsvector: ts_rank перестаёт пересчитывать вектор на каждую строку.
ALTER TABLE public.atoms
    ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('public.ru_en'::regconfig, content)) STORED;
CREATE INDEX IF NOT EXISTS idx_atoms_tsv ON public.atoms USING gin (tsv);

-- Частичный индекс по активным атомам версии: статус низкоселективен сам по себе.
CREATE INDEX IF NOT EXISTS idx_atoms_active_version
    ON public.atoms USING btree (version_id) WHERE status = 'active';

-- document_id участвует во всех поисковых JOIN, индекса по нему не было.
CREATE INDEX IF NOT EXISTS idx_atoms_document ON public.atoms USING btree (document_id);

-- ILIKE-фолбэк поиска без seq scan на больших корпусах.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_atoms_content_trgm
    ON public.atoms USING gin (content gin_trgm_ops);
