-- Для баз, развёрнутых до v1.3.0: UNIQUE на sources.location.
-- Идемпотентно. Применять от суперпользователя:
--   sudo -u postgres psql -d <db> -v ON_ERROR_STOP=1 -f references/migrations/0003_location_unique.sql
-- Если команда падает с duplicate key, в базе есть два источника с одним путём —
-- их надо слить вручную до повторного прогона.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'sources_location_key'
    ) THEN
        ALTER TABLE public.sources
            ADD CONSTRAINT sources_location_key UNIQUE (location);
    END IF;
END $$;
