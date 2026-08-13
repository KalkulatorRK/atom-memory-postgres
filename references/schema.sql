--
-- PostgreSQL database dump
--


-- Dumped from database version 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: atom_links; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.atom_links (
    id bigint NOT NULL,
    from_atom bigint,
    to_atom bigint,
    rel_type text DEFAULT 'reference'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);



--
-- Name: atom_links_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.atom_links_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: atom_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.atom_links_id_seq OWNED BY public.atom_links.id;


--
-- Name: atoms; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.atoms (
    id bigint NOT NULL,
    version_id bigint,
    document_id bigint,
    atom_type text DEFAULT 'text'::text NOT NULL,
    ordinal integer NOT NULL,
    content text NOT NULL,
    content_sha text,
    metadata jsonb DEFAULT '{}'::jsonb,
    status text DEFAULT 'active'::text,
    created_at timestamp with time zone DEFAULT now()
);



--
-- Name: atoms_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.atoms_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: atoms_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.atoms_id_seq OWNED BY public.atoms.id;


--
-- Name: embeddings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.embeddings (
    id bigint NOT NULL,
    atom_id bigint,
    model text NOT NULL,
    dims integer NOT NULL,
    vector public.vector(768),
    created_at timestamp with time zone DEFAULT now()
);



--
-- Name: embeddings_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.embeddings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: embeddings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.embeddings_id_seq OWNED BY public.embeddings.id;


--
-- Name: journal; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.journal (
    id bigint NOT NULL,
    op_type text NOT NULL,
    details jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);



--
-- Name: journal_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.journal_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: journal_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.journal_id_seq OWNED BY public.journal.id;


--
-- Name: projects; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.projects (
    id bigint NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text,
    created_at timestamp with time zone DEFAULT now()
);



--
-- Name: projects_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.projects_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: projects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.projects_id_seq OWNED BY public.projects.id;


--
-- Name: sources; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.sources (
    id bigint NOT NULL,
    project_id bigint,
    title text NOT NULL,
    source_type text NOT NULL,
    location text NOT NULL,
    content_sha text,
    content_size bigint,
    created_at timestamp with time zone DEFAULT now()
);



--
-- Name: sources_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.sources_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: sources_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.sources_id_seq OWNED BY public.sources.id;


--
-- Name: versions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.versions (
    id bigint NOT NULL,
    source_id bigint,
    version_no integer NOT NULL,
    sha256 text NOT NULL,
    snapshot_at timestamp with time zone DEFAULT now(),
    change_log text
);



--
-- Name: versions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;



--
-- Name: versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.versions_id_seq OWNED BY public.versions.id;


--
-- Name: atom_links id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atom_links ALTER COLUMN id SET DEFAULT nextval('public.atom_links_id_seq'::regclass);


--
-- Name: atoms id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atoms ALTER COLUMN id SET DEFAULT nextval('public.atoms_id_seq'::regclass);


--
-- Name: embeddings id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.embeddings ALTER COLUMN id SET DEFAULT nextval('public.embeddings_id_seq'::regclass);


--
-- Name: journal id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.journal ALTER COLUMN id SET DEFAULT nextval('public.journal_id_seq'::regclass);


--
-- Name: projects id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.projects ALTER COLUMN id SET DEFAULT nextval('public.projects_id_seq'::regclass);


--
-- Name: sources id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sources ALTER COLUMN id SET DEFAULT nextval('public.sources_id_seq'::regclass);


--
-- Name: versions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.versions ALTER COLUMN id SET DEFAULT nextval('public.versions_id_seq'::regclass);


--
-- Name: atom_links atom_links_from_atom_to_atom_rel_type_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atom_links
    ADD CONSTRAINT atom_links_from_atom_to_atom_rel_type_key UNIQUE (from_atom, to_atom, rel_type);


--
-- Name: atom_links atom_links_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atom_links
    ADD CONSTRAINT atom_links_pkey PRIMARY KEY (id);


--
-- Name: atoms atoms_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atoms
    ADD CONSTRAINT atoms_pkey PRIMARY KEY (id);


--
-- Name: embeddings embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.embeddings
    ADD CONSTRAINT embeddings_pkey PRIMARY KEY (id);


--
-- Name: journal journal_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.journal
    ADD CONSTRAINT journal_pkey PRIMARY KEY (id);


--
-- Name: projects projects_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_name_key UNIQUE (name);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: sources sources_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_pkey PRIMARY KEY (id);


--
-- Name: versions versions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.versions
    ADD CONSTRAINT versions_pkey PRIMARY KEY (id);


--
-- Name: versions versions_source_id_version_no_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.versions
    ADD CONSTRAINT versions_source_id_version_no_key UNIQUE (source_id, version_no);


--
-- Name: idx_atoms_fts; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_atoms_fts ON public.atoms USING gin (to_tsvector('russian'::regconfig, content));


--
-- Name: idx_atoms_metadata_gin; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_atoms_metadata_gin ON public.atoms USING gin (metadata);


--
-- Name: idx_atoms_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_atoms_status ON public.atoms USING btree (status);


--
-- Name: idx_atoms_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_atoms_type ON public.atoms USING btree (atom_type);


--
-- Name: idx_atoms_version; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_atoms_version ON public.atoms USING btree (version_id);


--
-- Name: idx_emb_atom; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_emb_atom ON public.embeddings USING btree (atom_id);


--
-- Name: idx_links_to; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_links_to ON public.atom_links USING btree (to_atom);


--
-- Name: idx_sources_project; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_sources_project ON public.sources USING btree (project_id);


--
-- Name: atom_links atom_links_from_atom_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atom_links
    ADD CONSTRAINT atom_links_from_atom_fkey FOREIGN KEY (from_atom) REFERENCES public.atoms(id) ON DELETE CASCADE;


--
-- Name: atom_links atom_links_to_atom_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atom_links
    ADD CONSTRAINT atom_links_to_atom_fkey FOREIGN KEY (to_atom) REFERENCES public.atoms(id) ON DELETE CASCADE;


--
-- Name: atoms atoms_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.atoms
    ADD CONSTRAINT atoms_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.versions(id) ON DELETE CASCADE;


--
-- Name: embeddings embeddings_atom_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.embeddings
    ADD CONSTRAINT embeddings_atom_id_fkey FOREIGN KEY (atom_id) REFERENCES public.atoms(id) ON DELETE CASCADE;


--
-- Name: sources sources_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: versions versions_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.versions
    ADD CONSTRAINT versions_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id) ON DELETE CASCADE;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: pg_database_owner
--

GRANT USAGE ON SCHEMA public TO hermes;


--
-- Name: TABLE atom_links; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.atom_links TO hermes;


--
-- Name: SEQUENCE atom_links_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.atom_links_id_seq TO hermes;


--
-- Name: TABLE atoms; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.atoms TO hermes;


--
-- Name: SEQUENCE atoms_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.atoms_id_seq TO hermes;


--
-- Name: TABLE embeddings; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.embeddings TO hermes;


--
-- Name: SEQUENCE embeddings_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.embeddings_id_seq TO hermes;


--
-- Name: TABLE journal; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.journal TO hermes;


--
-- Name: SEQUENCE journal_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.journal_id_seq TO hermes;


--
-- Name: TABLE projects; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.projects TO hermes;


--
-- Name: SEQUENCE projects_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.projects_id_seq TO hermes;


--
-- Name: TABLE sources; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.sources TO hermes;


--
-- Name: SEQUENCE sources_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.sources_id_seq TO hermes;


--
-- Name: TABLE versions; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.versions TO hermes;


--
-- Name: SEQUENCE versions_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.versions_id_seq TO hermes;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: postgres
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO hermes;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: postgres
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO hermes;


--
-- PostgreSQL database dump complete
--

\unrestrict qiC4WJWJSatzAAqlp1h01xtJIKjPW9dS02MxFvNXgTlnsaxuvsjFafadGcObmVO

