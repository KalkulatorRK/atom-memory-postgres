#!/usr/bin/env python3
"""Импорт документа в память агента (Этап 2, v2 — механизм качества).

Конвейер: PDF → нормализация → умная резка по предложениям → таблицы/схемы целиком
→ quality gate → DeepSeek-обогащение (контекст-приписка) → резолвинг refs → PostgreSQL

Использование:
  python3 import_document.py --file document.pdf --project "my-project"
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

# ===== Конфигурация =====
PG_DSN = os.environ.get("PG_DSN") or ""
CHUNK_MIN = 300          # мин. символов на атом
CHUNK_TARGET = 400       # целевой размер
CHUNK_MAX = 500          # макс. (до границы предложения)
CHUNK_OVERLAP = 40       # 10% overlap
BATCH_SIZE = 10          # атомов на LLM-вызов (текст; короткие батчи надёжны)
MAX_WORKERS = 5          # параллельные вызовы DeepSeek (ThreadPool)
ASSETS_DIR = os.path.expanduser(os.environ.get("MEMORY_ASSETS_DIR", "~/memory_import/assets"))


def get_pg():
    import psycopg2
    if not PG_DSN:
        raise SystemExit("PG_DSN не задан: export PG_DSN=postgresql://user:pass@host:5432/db")
    return psycopg2.connect(PG_DSN)


def pdf_to_pages(pdf_path: str):
    """Шаг 1: PDF → список (номер_страницы, текст). Документ закрывается."""
    import fitz
    doc = fitz.open(pdf_path)
    try:
        return [(page.number + 1, page.get_text()) for page in doc]
    finally:
        doc.close()


def pdf_to_text(pdf_path: str) -> str:
    """Совместимость: текст всех страниц одной строкой с маркерами страниц."""
    return "\n\n".join(
        f"<!-- страница {n} -->\n{t}" for n, t in pdf_to_pages(pdf_path) if t.strip())


def normalize_text(md: str) -> str:
    """Склейка переносов строк внутри абзацев (PDF-колонки)."""
    lines = md.split('\n')
    out = []
    buffer = []
    for line in lines:
        s = line.strip()
        if not s:
            if buffer:
                out.append(' '.join(buffer))
                buffer = []
            continue
        is_new_block = (
            s.startswith('<!--') or s.startswith('#') or s.startswith('- ') or
            s.startswith('* ') or s.startswith('|') or
            len(s) < 120 and (s[0].isdigit() or
                s.startswith(('Приложение', 'ГОСТ', 'Таблица', 'Примечание', 'ПРИЛОЖЕНИЕ')))
        )
        if is_new_block and buffer:
            out.append(' '.join(buffer))
            buffer = []
        buffer.append(s)
    if buffer:
        out.append(' '.join(buffer))
    return '\n\n'.join(out)


def smart_split(text: str):
    """Умная резка: по границам предложений, а не по символам.

    Возвращает список атомов-словарей с ordinal/content/atom_type.
    """
    # Точки-разделители предложений (не внутри чисел/сокращений)
    sentences = re.split(r'(?<=[.!?])\s+|\n\n', text)
    atoms = []
    current = ""
    page = None
    ordinal = 0

    def page_of(fragment):
        marks = re.findall(r'<!-- страница (\d+) -->', fragment)
        return int(marks[-1]) if marks else None

    def emit(buf):
        nonlocal ordinal, page
        atoms.append({"ordinal": ordinal, "content": buf, "atom_type": "text",
                      "page": page_of(buf) or page})
        page = page_of(buf) or page
        ordinal += 1

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(current) + len(sent) <= CHUNK_MAX or not current:
            current = current + (" " if current else "") + sent
        else:
            emit(current)
            current = sent
    if current:
        emit(current)

    # Финальная проверка: атомы меньше CHUNK_MIN — мёрджим с соседом
    merged = []
    for a in atoms:
        if merged and len(a["content"]) < CHUNK_MIN and len(merged[-1]["content"]) + len(a["content"]) < CHUNK_MAX * 1.5:
            merged[-1]["content"] += " " + a["content"]
            merged[-1]["page"] = merged[-1].get("page") or a.get("page")
        else:
            merged.append(a)
    return merged


def extract_tables_images(pdf_path: str):
    """Шаг 1а: таблицы и изображения — целиком, с идентификаторами.

    Возвращает (tables_atoms, images_atoms).
    """
    import fitz
    import hashlib as _hashlib
    doc = fitz.open(pdf_path)
    os.makedirs(ASSETS_DIR, exist_ok=True)
    # Префикс документа: без него картинки разных PDF затирали друг друга
    # в общем каталоге (имя было img_p{страница}_{xref}.png).
    doc_key = _hashlib.sha256(os.path.abspath(pdf_path).encode()).hexdigest()[:10]
    tables = []
    images = []
    seen_figs = set()

    for pno in range(len(doc)):
        page = doc[pno]
        page_text = page.get_text()

        # ===== ТАБЛИЦЫ =====
        try:
            tabs = page.find_tables()
            for t in tabs.tables:
                rows = t.extract()
                if not rows:
                    continue
                # Markdown-таблица
                md_rows = []
                for row in rows:
                    md_rows.append("| " + " | ".join(str(c).replace("|", "/").strip() if c else "" for c in row) + " |")
                content = "\n".join(md_rows)

                # Номер берём из подписи прямо над таблицей, а не из первого
                # совпадения на странице: иначе все таблицы страницы получали
                # номер первой.
                table_no, title = _nearest_caption(page, t.bbox, "table")

                tables.append({
                    "ordinal": 0,
                    "atom_type": "table",
                    "content": content,
                    "table_no": table_no,
                    "title": title,
                    "page": pno + 1,
                })
        except Exception as e:
            pass

        # ===== ИЗОБРАЖЕНИЯ =====
        try:
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen_figs:
                    continue
                seen_figs.add(xref)
                # Извлекаем
                pix = fitz.Pixmap(doc, xref)
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                fname = f"{doc_key}_p{pno+1}_{xref}.png"
                fpath = os.path.join(ASSETS_DIR, fname)
                pix.save(fpath)

                fig_no, _cap = _nearest_caption(page, pix.irect, "figure")

                images.append({
                    "ordinal": 0,
                    "atom_type": "image",
                    "content": f"[изображение: {fname}]",
                    "fig_no": fig_no,
                    "file_path": fpath,
                    "page": pno + 1,
                })
        except Exception as e:
            pass

    doc.close()
    return tables, images


def _nearest_caption(page, bbox, kind):
    """Подпись ближайшая к объекту: над ним для таблиц, под ним для рисунков.

    kind='table' ищет «Таблица N», kind='figure' — «рис. N» / «Рисунок N».
    Возвращает (номер, заголовок). Номер в том виде, как в документе.
    """
    if kind == "table":
        rx = re.compile(r'Таблица\s+([0-9]+(?:\.[0-9]+)?|[А-Яа-яA-Za-z](?:\.[0-9]+)?)'
                        r'(?:\s*[—–-]\s*([^\n]+))?')
        above = True
    else:
        rx = re.compile(r'(?:рис\.|Рисунок|рисунок|Схема|схема)\s*'
                        r'([0-9]+(?:\.[0-9]+)?|[А-Яа-яA-Za-z](?:\.[0-9]+)?)')
        above = False
    best, best_gap = None, None
    for b in page.get_text("blocks"):
        x0, y0, x1, y1, text = b[:5]
        m = rx.search(text or "")
        if not m:
            continue
        gap = (bbox[1] - y1) if above else (y0 - bbox[3])
        if gap < -5:
            continue
        if best_gap is None or gap < best_gap:
            best, best_gap = m, gap
    if not best:
        return None, ""
    number = best.group(1)
    if kind == "figure":
        number = f"рис. {number}"
    title = best.group(2).strip() if kind == "table" and best.lastindex and best.lastindex >= 2 and best.group(2) else ""
    return number, title


def quality_gate(atoms):
    """Шаг 2: фильтр качества — отброс мусора, разбивка смесей."""
    clean = []
    dropped = 0
    for a in atoms:
        content = a["content"].strip()
        # Мусор: без букв, слишком короткий
        letters = re.findall(r'[А-Яа-яA-Za-z]', content)
        if len(content) < 30 or len(letters) < 10:
            dropped += 1
            continue
        marks = re.findall(r'<!-- страница (\d+) -->', content)
        if marks and not a.get("page"):
            a["page"] = int(marks[0])
        content = re.sub(r'<!-- страница \d+ -->\s*', '', content)
        a["content"] = content
        clean.append(a)
    return clean, dropped


def enrich_batch(atoms_batch, doc_title="ГОСТ", prev_tail=""):
    """Шаг 3: DeepSeek-обогащение с контекст-припиской (батч по 5)."""
    import requests

    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("NOUS_API_KEY", "")
    if not api_key:
        env_path = os.path.expanduser("~/.hermes/.env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith(("NOUS_API_KEY=", "LLM_API_KEY=")):
                        api_key = line.strip().split("=", 1)[1]
                        break

    enriched = []
    if not api_key:
        for atom in atoms_batch:
            enriched.append({**atom, "metadata": {
                "tags": [], "entities": [], "summary": atom["content"][:80],
                "atom_type": atom["atom_type"], "source_doc": doc_title}})
        return enriched

    items = []
    for i, atom in enumerate(atoms_batch):
        items.append(f"[{i}] {atom['content'][:300]}")

    ctx_line = f"КОНТЕКСТ (конец предыдущего атома): {prev_tail[:150]}\n\n" if prev_tail else ""
    prompt = (
        "Ты — система извлечения метаданных для базы знаний (документ: "
        f"{doc_title}). {ctx_line}"
        f"Для каждого фрагмента [{i}] верни JSON-массив из объектов:\n"
        '{"tags": ["2-5 коротких тегов на русском, ОБЯЗАТЕЛЬНО непустые; если фрагмент обрывок '
        'или формула — поставь минимум 1 тег по типу: "формула"/"таблица"/"фрагмент"], '
        '"entities": ["сущности: стандарты, термины, номера пунктов"], '
        '"summary": "аннотация до 40 слов", "atom_type": "text|table|formula", '
        '"refs": [{"type": "table|image|appendix", "target": "номер из текста, напр. 5 или рис. 3"}]}. '
        'refs — только если в фрагменте ЕСТЬ ссылка на таблицу/рисунок/приложение. '
        'Отвечай ТОЛЬКО валидным JSON, без пояснений.\n\n'
        + "\n\n".join(items)
    )

    parsed = None
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{os.environ.get('LLM_BASE_URL', 'https://inference-api.nousresearch.com/v1')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                },
                json={
                    "model": os.environ.get("LLM_MODEL", "deepseek/deepseek-v4-flash"),
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2500,
                    "temperature": 0.1,
                },
                timeout=90,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            if not content or not content.strip():
                if attempt < 2:
                    continue
                raise ValueError("Пустой ответ модели")
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = json.loads(content)
            break
        except Exception as e:
            if attempt == 2:
                print(f"      ⚠ LLM-сбой: {e}")
                parsed = None
            continue

    if parsed is not None and isinstance(parsed, list):
        for i, atom in enumerate(atoms_batch):
            meta = parsed[i] if i < len(parsed) else {}
            if not isinstance(meta, dict):
                meta = {}
            tags = meta.get("tags", []) or []
            if not tags:
                tags = ["фрагмент"]
            enriched.append({**atom, "metadata": {
                "tags": tags,
                "entities": meta.get("entities", []),
                "summary": meta.get("summary", atom["content"][:80]),
                "atom_type": meta.get("atom_type", atom["atom_type"]),
                "refs": meta.get("refs", []),
                "source_doc": doc_title}})
    else:
        for atom in atoms_batch:
            enriched.append({**atom, "metadata": {
                "tags": [], "entities": [], "summary": atom["content"][:80],
                "atom_type": atom["atom_type"], "refs": [], "source_doc": doc_title}})
    return enriched


def import_doc(pdf_path, project_name):
    t0 = time.time()
    print(f"[1/4] Конвертация PDF → текст...")
    md = pdf_to_text(pdf_path)
    md = normalize_text(md)
    print(f"      Текст: {len(md)} символов, {time.time()-t0:.0f} сек")

    print(f"[1а] Таблицы и изображения...")
    tables, images = extract_tables_images(pdf_path)
    print(f"      Таблиц: {len(tables)}, изображений: {len(images)}")

    print(f"[2/4] Умная резка по предложениям + quality gate...")
    text_atoms = smart_split(md)
    text_atoms, dropped = quality_gate(text_atoms)
    print(f"      Текст-атомов: {len(text_atoms)} (отброшено мусора: {dropped})")

    # Собираем все атомы: таблицы и изображения ПЕРВЫМИ (не режутся)
    all_atoms = []
    for t in tables:
        t["ordinal"] = len(all_atoms)
        t["metadata_hint"] = {"table_no": t.get("table_no"), "title": t.get("title"), "page": t.get("page")}
        all_atoms.append(t)
    for im in images:
        im["ordinal"] = len(all_atoms)
        im["metadata_hint"] = {"fig_no": im.get("fig_no"), "file_path": im.get("file_path"), "page": im.get("page")}
        all_atoms.append(im)
    for a in text_atoms:
        a["ordinal"] = len(all_atoms)
        a["metadata_hint"] = {"page": a.get("page")}
        all_atoms.append(a)

    print(f"      Всего атомов: {len(all_atoms)}")

    print(f"[3/4] Обогащение DeepSeek (параллельно, только текст-атомы)...")
    enriched = []
    doc_title = os.path.basename(pdf_path)

    # Таблицы и изображения: метаданные уже дал код (table_no/fig_no/file_path)
    # НЕ отправляем их в LLM (принцип разумности — экономия 36% вызовов, $0)
    # Для них добавляем теги по типу
    for t in tables:
        hint = t.get("metadata_hint", {})
        enriched.append({**t, "metadata": {
            "tags": [hint.get("title", "таблица")] if hint.get("table_no") else ["таблица"],
            "entities": [],
            "summary": hint.get("title", "Таблица из документа"),
            "atom_type": "table",
            "table_no": hint.get("table_no"),
            "title": hint.get("title"),
            "page": hint.get("page"),
            "source_doc": doc_title}})
    for im in images:
        hint = im.get("metadata_hint", {})
        enriched.append({**im, "metadata": {
            "tags": [hint.get("fig_no", "схема")] if hint.get("fig_no") else ["схема"],
            "entities": [],
            "summary": f"Изображение {'с номером ' + hint.get('fig_no', '') if hint.get('fig_no') else ''}".strip(),
            "atom_type": "image",
            "fig_no": hint.get("fig_no"),
            "file_path": hint.get("file_path"),
            "page": hint.get("page"),
            "source_doc": doc_title}})

    # Текст-атомы → DeepSeek параллельно
    text_atoms_for_llm = [a for a in text_atoms]
    batches = [text_atoms_for_llm[i:i+BATCH_SIZE] for i in range(0, len(text_atoms_for_llm), BATCH_SIZE)]
    print(f"      Батчей текста: {len(batches)} (параллельность {MAX_WORKERS})")

    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}
    prev_tail = ""
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {}
        for bi, batch in enumerate(batches):
            futures[ex.submit(enrich_batch, batch, doc_title, "")] = bi
        for fut in as_completed(futures):
            bi = futures[fut]
            try:
                results[bi] = fut.result()
            except Exception as e:
                print(f"      ⚠ сбой батча {bi}: {e}")
                results[bi] = None
    for bi in sorted(results):
        if results[bi]:
            enriched.extend(results[bi])
        else:
            # fallback
            for atom in batches[bi]:
                enriched.append({**atom, "metadata": {
                    "tags": [], "entities": [], "summary": atom["content"][:80],
                    "atom_type": atom["atom_type"], "page": atom.get("page"),
                    "source_doc": doc_title}})
    print(f"      Обогащено: {len(enriched)} атомов")

    print(f"[4/4] Запись в PostgreSQL + atom_links...")
    conn = get_pg()
    cur = conn.cursor()

    cur.execute("SELECT id FROM projects WHERE name = %s", (project_name,))
    row = cur.fetchone()
    if row:
        project_id = row[0]
    else:
        cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING id", (project_name,))
        project_id = cur.fetchone()[0]

    pdf_path = os.path.abspath(pdf_path)
    with open(pdf_path, 'rb') as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    size = os.path.getsize(pdf_path)
    cur.execute("SELECT id, content_sha FROM sources WHERE location = %s", (pdf_path,))
    row = cur.fetchone()
    if row and row[1] == sha:
        # Файл не изменился — новую версию не плодим, атомы не трогаем.
        conn.rollback()
        cur.close()
        conn.close()
        print(f"      Без изменений (sha совпал), импорт пропущен")
        return 0, 0
    if row:
        source_id = row[0]
        cur.execute("UPDATE sources SET content_sha = %s, content_size = %s WHERE id = %s",
                    (sha, size, source_id))
        cur.execute("SELECT COALESCE(MAX(version_no), 0) FROM versions WHERE source_id = %s", (source_id,))
        version_no = cur.fetchone()[0] + 1
        cur.execute("UPDATE atoms SET status = 'superseded' WHERE version_id IN "
                    "(SELECT id FROM versions WHERE source_id = %s)", (source_id,))
    else:
        cur.execute(
            "INSERT INTO sources (project_id, title, source_type, location, content_sha, content_size) "
            "VALUES (%s, %s, 'pdf', %s, %s, %s) RETURNING id",
            (project_id, os.path.basename(pdf_path), pdf_path, sha, size))
        source_id = cur.fetchone()[0]
        version_no = 1

    cur.execute("INSERT INTO versions (source_id, version_no, sha256) VALUES (%s, %s, %s) RETURNING id",
                (source_id, version_no, sha))
    version_id = cur.fetchone()[0]

    # Вставка атомов + сбор id для ссылок
    atom_ids = {}
    for atom in enriched:
        meta = dict(atom.get("metadata", {}))
        # Обогащаем метаданные таблиц/изображений
        hint = atom.get("metadata_hint", {})
        if hint.get("table_no"):
            meta["table_no"] = hint["table_no"]
        if hint.get("fig_no"):
            meta["fig_no"] = hint["fig_no"]
        if hint.get("file_path"):
            meta["file_path"] = hint["file_path"]
        if hint.get("title"):
            meta["title"] = hint["title"]
        if hint.get("page"):
            meta["page"] = hint["page"]

        cur.execute(
            "INSERT INTO atoms (version_id, document_id, atom_type, ordinal, content, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb) RETURNING id",
            (version_id, source_id, atom["atom_type"], atom["ordinal"], atom["content"],
             json.dumps(meta, ensure_ascii=False)))
        atom_ids[atom["ordinal"]] = cur.fetchone()[0]

    # Резолвинг refs → atom_links
    links = 0
    for atom in enriched:
        refs = atom.get("metadata", {}).get("refs", [])
        from_id = atom_ids.get(atom["ordinal"])
        if not from_id or not refs:
            continue
        for ref in refs:
            target = str(ref.get("target", "")).lower().strip()
            rtype = ref.get("type", "table")
            if not target:
                continue
            # Ищем атом-цель по table_no / fig_no в метаданных
            cur.execute(
                "SELECT id FROM atoms WHERE version_id=%s AND status='active' AND ("
                "lower(metadata->>'table_no') = lower(%s) OR "
                "lower(metadata->>'fig_no') = lower(%s) OR "
                "lower(metadata->>'fig_no') = lower('рис. ' || %s)) LIMIT 1",
                (version_id, target, target, target))
            row = cur.fetchone()
            if row:
                try:
                    cur.execute(
                        "INSERT INTO atom_links (from_atom, to_atom, rel_type) VALUES (%s, %s, %s) "
                        "ON CONFLICT DO NOTHING",
                        (from_id, row[0], f"references_{rtype}"))
                    links += cur.rowcount
                except Exception:
                    pass

    cur.execute(
        "INSERT INTO journal (op_type, details) VALUES ('import', %s::jsonb)",
        (json.dumps({"source_id": source_id, "version_id": version_id,
                     "version_no": version_no, "atoms": len(enriched),
                     "file": os.path.basename(pdf_path)}, ensure_ascii=False),))
    conn.commit()
    cur.close()
    conn.close()
    print(f"      Готово: {len(enriched)} атомов, {links} ссылок, {time.time()-t0:.0f} сек")

    # Нормализация перекрёстных ссылок (3 стратегии: точное/префиксное/текст)
    try:
        from normalize_links import resolve_links
        n_links = resolve_links(version_id)
        links += n_links
        print(f"      Нормализация: +{n_links} ссылок (итого {links})")
    except ImportError:
        pass  # normalize_links.py не рядом — не критично
    return len(enriched), links


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--project", default="default")
    args = parser.parse_args()
    n, l = import_doc(args.file, args.project)
    print(f"\n✅ Импортировано атомов: {n}, связей: {l}")
