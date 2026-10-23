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

  ALTER TABLE public.projects DROP CONSTRAINT IF EXISTS projects_embed_policy_check;
  ALTER TABLE public.projects DROP COLUMN IF EXISTS embed_policy;

  ALTER TABLE public.embeddings ALTER COLUMN vector TYPE public.vector(768);
  ALTER TABLE public.embeddings ALTER COLUMN atom_id DROP NOT NULL;
  ALTER TABLE public.embeddings ALTER COLUMN vector DROP NOT NULL;
END $$;
