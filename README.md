# 🧠 Atom Memory for Agents

**Precise long-term memory for LLM agents on PostgreSQL — documents stored as atoms, answers always cited.**

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%2B-336791.svg)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-0.7%2B-316192.svg)](https://github.com/pgvector/pgvector)

A self-contained **Hermes skill** (schema + scripts + deployment procedure) that turns any PostgreSQL into a knowledge base your agent can actually rely on. Instead of storing documents as whole "books", it cuts them into **atoms** — indivisible units of meaning — so retrieval is precise, answers are sourced, and nothing gets invented.

> This is the *stack*, not the data: anyone can deploy it and fill the base with their own documents.

---

## Installation

### Option A — manual tarball (recommended, always works)

Download the archive from the [latest release](https://github.com/KalkulatorRK/atom-memory-postgres/releases) and unpack it into the skills directory:

```bash
curl -L -o ~/atom-memory-skill.tar.gz https://github.com/KalkulatorRK/atom-memory-postgres/releases/latest/download/atom-memory-postgres-skill.tar.gz
mkdir -p ~/.hermes/skills/data-science/atom-memory-postgres
tar -xzf ~/atom-memory-skill.tar.gz -C ~/.hermes/skills/data-science/atom-memory-postgres
# → ~/.hermes/skills/data-science/atom-memory-postgres/
```

### Option B — `hermes skills install` from URL

```bash
hermes skills install https://raw.githubusercontent.com/KalkulatorRK/atom-memory-postgres/main/SKILL.md
```

> ⚠️ The built-in security scanner (tirith) may block this skill from *community sources* because its setup script legitimately uses `sudo apt` / `pip install` to provision PostgreSQL. That is a false positive for a provisioning skill — use Option A, or review and trust the source yourself.

---


> **What is and is not implemented.** Search is full-text (`ru_en` stemming) plus an ILIKE fallback. The `embeddings` table and the pgvector badge are a placeholder: no script writes or reads vectors yet. The `journal` table records imports. Document text is sent to an external LLM only when `LLM_API_KEY` is set; without it import works and atoms simply have no tags.

## Why

Naive chunk-based RAG splits text blindly and destroys what matters most in technical documents:

- tables and diagrams get torn apart,
- cross-references ("see Figure 3" — which lives on page 20) become dead text,
- answers come back "approximately right" with no way to check.

Atom Memory solves all three:

| Problem | Solution |
|---|---|
| ❌ Blind chunking loses meaning | ✅ Atoms = 1–2 **complete sentences**, tables and figures kept **whole** |
| ❌ "See Figure 3" is dead text | ✅ Cross-references become real links (`atom_links`) — search pulls the figure into the answer |
| ❌ Answers without sources | ✅ Every atom carries its passport: document, clause, page — the agent always cites |
| ❌ Docs get re-edited, answers go stale | ✅ Versioned imports: old atoms are `superseded`, never deleted |
| ❌ Mixed-version answers | ✅ `content_sha` (sha256) guarantees an answer is never stitched from different editions |

## Features

- **📄 Document pipeline** — PDF → normalization → smart sentence-boundary splitting (300–500 chars) → quality gate → LLM enrichment → single-transaction write.
- **📊 Tables & figures stay intact** — extracted whole with `table_no` / `fig_no` as stable cross-reference IDs.
- **🔗 Atom links** — "see Table 5" in text becomes a real edge in `atom_links`; `deep` retrieval walks the graph.
- **🌍 Multilingual search (RU + EN)** — morphological FTS (`to_tsvector('ru_en')`): Russian stemming for Cyrillic, English stemming for Latin, stop-words handled; numeric fallback ("12", "0.4").
- **🧬 Versioning & audit** — `sources → versions (sha256) → atoms`; re-import = new version, history preserved.
- **💰 Cheap enrichment** — LLM tagging costs ~**$0.003 per document** (40 pages) thanks to cached token pricing.
- **🤖 Hermes triggers** — type `память: question`, `#память question`, `memory: question` or `#memory question` in chat; the bundled `memory_trigger.py` detects the trigger and runs the search — answers come with citations.

## Quick Start

### 1. Deploy the database (PostgreSQL 16 + pgvector + schema)

```bash
sudo bash scripts/setup_memory_db.sh memory hermes your_password
export PG_DSN="postgresql://hermes:your_password@localhost:5432/memory"
```

> The script applies a memory-lean config (`shared_buffers=128MB`, …) — proven on a 3.7 GB VPS.
> Manual steps are in [`SKILL.md`](SKILL.md).

### 2. Install Python deps

```bash
pip install pymupdf psycopg2 requests
```

### 3. Import a document

```bash
python3 scripts/import_document.py --file document.pdf --project "my-project"
# → ✅ Imported atoms: 235, links: 6
```

Works without an LLM key (atoms get imported untagged). With a key, tagging/entities/summaries are automatic:

```bash
export LLM_API_KEY="..."   # any OpenAI-compatible key
export LLM_MODEL="deepseek/deepseek-v4-flash"   # default
```

### 4. Search

```bash
python3 scripts/memory_query.py "sensitivity of the indicator" --limit 5
```

## How It Works

```
PDF ──► [1] parse (pymupdf)
     ──► [2] tables & figures extracted WHOLE (table_no / fig_no)
     ──► [3] smart split at sentence boundaries (300–500 chars)
     ──► [4] quality gate (drop junk)
     ──► [5] LLM enrichment (tags, entities, refs)
     ──► [6] single transaction: sources → versions (sha256) → atoms (+ atom_links)
```

Search pipeline: metadata filters (project/tags/type) → RU+EN morphological FTS (`ru_en` config) → follow `atom_links` to pull referenced tables/figures into context.

## Database Schema

```
projects ─┬─ sources ── versions ── atoms (content, metadata jsonb, status)
          │                                │
          │                                ├── atom_links (from_atom → to_atom, rel_type)
          │                                └── embeddings (optional, vector)
          └── journal (operation log)
```

Full schema: [`references/schema.sql`](references/schema.sql).

## Real Numbers (measured)

| Metric | Value |
|---|---|
| 40-page standard | ~235 atoms (149 text + 24 tables + 62 figures) |
| Import time | ~1 minute |
| LLM enrichment cost | **~$0.003 / document** |
| DB size (7 sources) | ~15 MB — fits a tiny VPS |

## Integration with Hermes

Install as any other skill:

```bash
hermes skills install <SKILL.md URL or archive>
```

The agent then recognizes `память:`, `#память`, `memory:` message triggers, runs the search, and answers with the source (document + clause + page). Slash forms (`/память`) are intercepted by the gateway and do **not** work.

## Requirements

- Linux (Ubuntu 24.04 tested), Python 3.10+
- PostgreSQL 16 + pgvector
- LLM API key — optional (metadata enrichment only)

## License

MIT
