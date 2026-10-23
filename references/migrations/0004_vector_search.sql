-- Миграция 0004: векторный поиск (pgvector HNSW, политика embed_policy)
DO $$
DECLARE
  v_ver text;
  v_num numeric;
  v_del int;
BEGIN
  SELECT extversion INTO v_ver FROM pg_extension WHERE extname = 'vector';
  IF v_ver IS NULL THEN
    RAISE EXCEPTION 'расширение vector не установлено; см. README';
  END IF;
  v_num := split_part(v_ver, '.', 1)::numeric + split_part(v_ver, '.', 2)::numeric / 10;
  IF v_num < 0.5 THEN
    RAISE EXCEPTION 'нужен pgvector ≥ 0.5.0; установлено %; см. README', v_ver;
  ELSIF v_num < 0.8 THEN
    RAISE NOTICE 'pgvector %: рекомендуется ≥ 0.8.0 для hnsw.iterative_scan', v_ver;
  END IF;

  DELETE FROM public.embeddings WHERE atom_id IS NULL OR vector IS NULL;
  GET DIAGNOSTICS v_del = ROW_COUNT;
  IF v_del > 0 THEN
    RAISE NOTICE '0004: удалено % строк embeddings без atom_id/vector', v_del;
  END IF;

  DELETE FROM public.embeddings e
  USING public.embeddings e2
  WHERE e.atom_id = e2.atom_id AND e.model = e2.model AND e.dims = e2.dims AND e.id < e2.id;

  ALTER TABLE public.embeddings ALTER COLUMN atom_id SET NOT NULL;
  ALTER TABLE public.embeddings ALTER COLUMN vector SET NOT NULL;
  ALTER TABLE public.embeddings ALTER COLUMN vector TYPE public.vector;

  ALTER TABLE public.embeddings ADD COLUMN IF NOT EXISTS content_hash text NOT NULL DEFAULT '';
  ALTER TABLE public.embeddings ADD COLUMN IF NOT EXISTS embed_meta jsonb NOT NULL DEFAULT '{}'::jsonb;
  ALTER TABLE public.embeddings ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'embeddings_dims_check'
  ) THEN
    ALTER TABLE public.embeddings
      ADD CONSTRAINT embeddings_dims_check CHECK (dims > 0 AND vector_dims(vector) = dims);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'embeddings_atom_space_key'
  ) THEN
    ALTER TABLE public.embeddings
      ADD CONSTRAINT embeddings_atom_space_key UNIQUE (atom_id, model, dims);
  END IF;

  ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS embed_policy text NOT NULL DEFAULT 'inherit';
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'projects_embed_policy_check'
  ) THEN
    ALTER TABLE public.projects
      ADD CONSTRAINT projects_embed_policy_check
      CHECK (embed_policy IN ('inherit', 'cloud', 'local_only', 'none'));
  END IF;

  CREATE INDEX IF NOT EXISTS idx_emb_hnsw_cloud_te3s_768
    ON public.embeddings
    USING hnsw ((vector::public.vector(768)) public.vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE model = 'cloud:text-embedding-3-small' AND dims = 768;

  CREATE INDEX IF NOT EXISTS idx_emb_hnsw_fake_hash_v1_768
    ON public.embeddings
    USING hnsw ((vector::public.vector(768)) public.vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE model = 'fake:hash-v1' AND dims = 768;

  IF NOT EXISTS (
    SELECT 1 FROM public.journal
    WHERE op_type = 'migration' AND details->>'name' = '0004_vector_search'
  ) THEN
    INSERT INTO public.journal (op_type, details)
    VALUES ('migration', '{"name":"0004_vector_search"}'::jsonb);
  END IF;
END $$;
