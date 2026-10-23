DO $$
DECLARE
  bad int;
BEGIN
  SELECT count(*) INTO bad FROM public.embeddings WHERE dims <> 768;
  IF bad > 0 THEN
    RAISE EXCEPTION 'есть векторы с dims≠768: удалите их (DELETE FROM embeddings WHERE dims<>768) или не откатывайтесь';
  END IF;

  DROP INDEX IF EXISTS public.idx_emb_hnsw_cloud_te3s_768;
  DROP INDEX IF EXISTS public.idx_emb_hnsw_fake_hash_v1_768;
  DROP INDEX IF EXISTS public.idx_emb_hnsw_local_multilingual_e5_base_768;

  ALTER TABLE public.embeddings DROP CONSTRAINT IF EXISTS embeddings_dims_check;
  ALTER TABLE public.embeddings DROP CONSTRAINT IF EXISTS embeddings_atom_space_key;

  ALTER TABLE public.embeddings DROP COLUMN IF EXISTS content_hash;
  ALTER TABLE public.embeddings DROP COLUMN IF EXISTS embed_meta;
  ALTER TABLE public.embeddings DROP COLUMN IF EXISTS updated_at;

  DROP TABLE IF EXISTS public._0004_embed_policy_snapshot;
  CREATE TABLE public._0004_embed_policy_snapshot AS
    SELECT id AS project_id, embed_policy FROM public.projects;

  ALTER TABLE public.projects DROP CONSTRAINT IF EXISTS projects_embed_policy_check;
  ALTER TABLE public.projects DROP COLUMN IF EXISTS embed_policy;

  ALTER TABLE public.embeddings ALTER COLUMN vector TYPE public.vector(768);
  ALTER TABLE public.embeddings ALTER COLUMN atom_id DROP NOT NULL;
  ALTER TABLE public.embeddings ALTER COLUMN vector DROP NOT NULL;

  DELETE FROM public.journal
  WHERE op_type = 'migration' AND details->>'name' = '0004_vector_search';
  RAISE NOTICE '0004 откат: запись journal для 0004_vector_search удалена';
END $$;
