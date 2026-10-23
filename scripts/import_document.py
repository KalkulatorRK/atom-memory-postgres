#!/usr/bin/env python3
"""Импорт документа в память агента (Этап 2, v2 — механизм качества).

Конвейер: PDF → нормализация → умная резка по предложениям → таблицы/схемы целиком
→ quality gate → DeepSeek-обогащение (контекст-приписка) → резолвинг refs → PostgreSQL

Использование:
  python3 import_document.py --file document.pdf --project "my-project"
"""
import argparse
import hashlib

from _common import normalize_table_no, normalize_fig_no, __version__
from structure import DocImportOptions, prepare_for_import, structure_split
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
    """Шаг 1: PDF → список (номер_страницы, текст). Документ закрывается.

    Текст внутри найденных таблиц вырезается по строкам: иначе ячейки попадают
    и в атом таблицы, и в текстовые атомы, а текстовый атом получает чужую
    страницу. Удаляются строки, а не блоки — блок может склеить последнюю
    строку таблицы с абзацем под ней, и вырезание блока затирало бы абзац.
    """
    import fitz
    doc = fitz.open(pdf_path)
    try:
        pages = []
        for page in doc:
            # Текст собирается из строк по позиции, а не из get_text() с вырезанием
            # по содержимому: str.replace убирал первое вхождение строки где угодно
            # на странице, и ячейка «2» стирала первую двойку из обычного текста.
            tables = _safe_tables(page)
            kept = [ln["text"] for ln in _lines(page)
                    if not any(_overlaps(ln["bbox"], t.bbox) for t in tables)]
            pages.append((page.number + 1, "\n".join(kept)))
        return pages
    finally:
        doc.close()


def _lines(page):
    out = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            txt = "".join(sp["text"] for sp in line.get("spans", []))
            out.append({"bbox": line["bbox"], "text": txt})
    return out


def _safe_tables(page):
    try:
        return page.find_tables().tables
    except Exception as e:
        print(f"      таблицы на стр. {page.number + 1} не извлеклись: {e}", file=sys.stderr)
        return []


def _overlaps(block, bbox):
    """Пересечение, а не полное вхождение: строка на границе таблицы
    иначе оставалась в текстовом атоме."""
    x0, y0, x1, y1 = block
    return x0 < bbox[2] and x1 > bbox[0] and y0 < bbox[3] and y1 > bbox[1]


def pdf_to_text(pdf_path: str) -> str:
    """Совместимость: текст всех страниц одной строкой с маркерами страниц."""
    return "\n\n".join(
        f"<!-- страница {n} -->\n{t}" for n, t in pdf_to_pages(pdf_path) if t.strip())


def _normalize_is_numbered_heading(s: str, prev_line: str = "") -> bool:
    from structure_headings import StructureLineState, accept_code_point_line

    if len(s) >= 120 or not s or not s[0].isdigit():
        return False
    if re.match(r"^\d+\s+Федерального\s+зак", s, re.IGNORECASE):
        return False
    if re.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}\b", s):
        return False
    from structure_headings import is_structure_heading_line

    ls = StructureLineState(
        prev_line=prev_line,
        at_doc_start=not prev_line.strip(),
        prev_was_structure_heading=is_structure_heading_line(prev_line),
    )
    if accept_code_point_line(s, ls)[0]:
        return True
    m = re.match(r"^(\d+(?:\.\d+)*)\s+(\S)", s)
    if not m:
        return False
    first_word = m.group(2)
    return bool(re.match(r"^[A-ZА-ЯЁ«\"(0-9]", first_word))


def normalize_text(md: str) -> str:
    """Склейка переносов строк внутри абзацев (PDF-колонки)."""
    from structure_headings import RE_ARTICLE_BARE

    lines = md.split('\n')
    out = []
    buffer = []
    prev_raw = ""
    for line in lines:
        s = line.strip()
        if not s:
            if buffer:
                out.append(' '.join(buffer))
                buffer = []
            prev_raw = ""
            continue
        if RE_ARTICLE_BARE.match(s):
            if buffer:
                out.append(' '.join(buffer))
                buffer = []
            out.append(s)
            prev_raw = s
            continue
        prev_for_point = " ".join(buffer) if buffer else prev_raw
        prev_heading_tail = buffer[-1] if buffer else prev_raw
        is_new_block = (
            s.startswith('<!--') or s.startswith('#') or s.startswith('- ') or
            s.startswith('* ') or s.startswith('|') or
            re.match(r'^(?:Статья|СТАТЬЯ)\s+\d', s) or
            re.match(r'^(?:Глава|ГЛАВА|Раздел|РАЗДЕЛ|Часть)\s', s, re.IGNORECASE) or
            _normalize_is_numbered_heading(s, prev_heading_tail) or
            s.startswith(('Приложение', 'ГОСТ', 'Таблица', 'Примечание', 'ПРИЛОЖЕНИЕ'))
        )
        if is_new_block and buffer:
            out.append(' '.join(buffer))
            prev_raw = buffer[-1] if buffer else prev_raw
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

    def emit(buf):
        nonlocal ordinal, page
        # Страница атома — та, на которой он начался. Если буфер открывается
        # маркером, начинаем с него; иначе продолжаем текущую страницу.
        # Текущую страницу после атома двигаем по последнему маркеру,
        # иначе атом на стыке откатывает нумерацию всех следующих.
        marks = re.findall(r'<!-- страница (\d+) -->', buf)
        start = int(marks[0]) if buf.lstrip().startswith("<!--") and marks else page
        atoms.append({"ordinal": ordinal, "content": buf, "atom_type": "text",
                      "page": start})
        if marks:
            page = int(marks[-1])
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
            print(f"      не извлеклось на стр. {pno + 1}: {e}", file=sys.stderr)

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

                rects = page.get_image_rects(xref)
                fig_bbox = rects[0] if rects else pix.irect
                fig_no, _cap = _nearest_caption(page, fig_bbox, "figure")

                images.append({
                    "ordinal": 0,
                    "atom_type": "image",
                    "content": f"[изображение: {fname}]",
                    "fig_no": fig_no,
                    "caption": _cap or None,
                    "file_path": fpath,
                    "page": pno + 1,
                })
        except Exception as e:
            print(f"      не извлеклось на стр. {pno + 1}: {e}", file=sys.stderr)

    doc.close()
    return tables, images


def _nearest_caption(page, bbox, kind):
    """Подпись, ближайшая к объекту и по вертикали, и по горизонтали.

    Две подписи в одной строке pymupdf отдаёт одним блоком, и search брал
    первую для обоих рисунков. Поэтому перебираем все совпадения (finditer)
    и берём то, чей горизонтальный интервал ближе к объекту.
    """
    if kind == "table":
        rx = re.compile(r'Таблица\s+([0-9]+(?:\.[0-9]+)?|[А-Яа-яA-Za-z](?:\.[0-9]+)?)(?!\w)'
                        r'(?:\s*[—–-]\s*([^\n]+))?')
        above = True
    else:
        rx = re.compile(r'(?:рис\.|Рисунок|рисунок|Схема|схема)\s*'
                        r'([0-9]+(?:\.[0-9]+)?|[А-Яа-яA-Za-z](?:\.[0-9]+)?)(?!\w)')
        above = False
    best, best_dist = None, None
    # get_text("dict") даёт bbox каждой строки, а не всего блока: две подписи
    # в одной строке иначе получают одинаковый зазор и обе становятся первыми.
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            x0, y0, x1, y1 = line["bbox"]
            text = "".join(sp["text"] for sp in line.get("spans", []))
            vgap = (bbox[1] - y1) if above else (y0 - bbox[3])
            if vgap < -5:
                continue
            for m in rx.finditer(text):
                hgap = 0 if x1 >= bbox[0] and x0 <= bbox[2] else min(abs(x0 - bbox[2]), abs(bbox[0] - x1))
                dist = vgap + hgap
                if best_dist is None or dist < best_dist:
                    best, best_dist = m, dist
    if not best:
        return None, ""
    number = best.group(1)
    if kind == "figure":
        number = f"рис. {number}"
    title = ""
    if kind == "table" and best.lastindex and best.lastindex >= 2 and best.group(2):
        title = best.group(2).strip()
    return number, title


def quality_gate(atoms):
    """Шаг 2: фильтр качества — отброс мусора, разбивка смесей."""
    clean = []
    dropped = 0
    for a in atoms:
        content = a["content"].strip()
        # Мусор: без букв, слишком короткий
        letters = re.findall(r'[А-Яа-яA-Za-z]', content)
        sm = a.get("structure_meta") or {}
        structured = bool(
            sm.get("article") or sm.get("section_path") or sm.get("point") or sm.get("annex")
        )
        min_len = 8 if structured else 30
        min_letters = 4 if structured else 10
        if len(content) < min_len or len(letters) < min_letters:
            dropped += 1
            continue
        marks = re.findall(r'<!-- страница (\d+) -->', content)
        if marks and not a.get("page"):
            a["page"] = int(marks[0])
        content = re.sub(r'<!-- страница \d+ -->\s*', '', content)
        a["content"] = content
        clean.append(a)
    return clean, dropped


STRUCTURE_META_KEYS = (
    "doc_kind",
    "standard",
    "law",
    "chapter",
    "article",
    "article_title",
    "point",
    "subpoint",
    "section_path",
    "annex",
    "redaction",
    "effective_date",
    "redaction_source",
)


def _hint_to_metadata(atom: dict) -> dict:
    hint = atom.get("metadata_hint") or {}
    sm = atom.get("structure_meta") or {}
    out = {}
    for k in STRUCTURE_META_KEYS:
        if k in hint and hint[k] is not None:
            out[k] = hint[k]
        elif k in sm and sm[k] is not None:
            out[k] = sm[k]
    if atom.get("page") and "page" not in out:
        out["page"] = atom.get("page")
    return out


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
                "atom_type": atom["atom_type"], "source_doc": doc_title,
                **_hint_to_metadata(atom)}})
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
                    "User-Agent": f"atom-memory-postgres/{__version__}",
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
                **({"page": atom.get("page")} if atom.get("page") else {}),
                "source_doc": doc_title,
                **_hint_to_metadata(atom)}})
    else:
        for atom in atoms_batch:
            enriched.append({**atom, "metadata": {
                "tags": [], "entities": [], "summary": atom["content"][:80],
                "atom_type": atom["atom_type"], "refs": [], "source_doc": doc_title,
                **_hint_to_metadata(atom)}})
    return enriched


def _existing_source(pdf_path):
    """Источник с этим путём независимо от проекта, или None.

    location уникален глобально, поэтому один файл не может лежать в двух
    проектах. Проверяется до нарезки и LLM.
    """
    pdf_path = os.path.abspath(pdf_path)
    with open(pdf_path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        "SELECT p.name, s.content_sha FROM sources s "
        "JOIN projects p ON s.project_id = p.id WHERE s.location = %s",
        (pdf_path,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {"project": row[0], "sha": row[1], "same": row[1] == sha}


def import_doc(
    pdf_path,
    project_name,
    *,
    doc_kind: str = "auto",
    redaction: str | None = None,
    effective_date: str | None = None,
):
    t0 = time.time()
    existing = _existing_source(pdf_path)
    if existing and existing["project"] != project_name:
        raise SystemExit(
            f"Файл уже импортирован в проект '{existing['project']}'. "
            f"Один файл не может лежать в двух проектах (location уникален).")
    if existing and existing["same"] and doc_kind == "auto":
        print("      Без изменений (sha совпал), импорт пропущен")
        return 0, 0
    print("[1/4] Конвертация PDF → текст...")
    md = pdf_to_text(pdf_path)
    md = normalize_text(md)
    doc_title = os.path.basename(pdf_path)
    imp_opts = DocImportOptions(
        doc_kind=doc_kind,
        redaction=redaction,
        effective_date=effective_date,
        source_title=doc_title,
    )
    md, struct_ctx, page_map = prepare_for_import(md, imp_opts)
    print(f"      Текст: {len(md)} символов, {time.time()-t0:.0f} сек")
    if struct_ctx:
        print(f"      Структурный профиль: {struct_ctx.doc_kind}")

    print("[1а] Таблицы и изображения...")
    tables, images = extract_tables_images(pdf_path)
    print(f"      Таблиц: {len(tables)}, изображений: {len(images)}")

    print("[2/4] Умная резка по предложениям + quality gate...")
    if struct_ctx:
        text_atoms = structure_split(
            md, struct_ctx, chunk_max=CHUNK_MAX, chunk_min=CHUNK_MIN
        )
        if not text_atoms:
            print(
                "      ⚠ структурная нарезка не дала атомов — fallback на smart_split",
                file=sys.stderr,
            )
            struct_ctx = None
            text_atoms = smart_split(md)
    else:
        text_atoms = smart_split(md)
    text_atoms, dropped = quality_gate(text_atoms)
    print(f"      Текст-атомов: {len(text_atoms)} (отброшено мусора: {dropped})")
    if not text_atoms and not tables and not images:
        raise SystemExit(
            "Импорт не создал ни одного атома: проверьте --doc-kind или содержимое PDF."
        )

    # Собираем все атомы: таблицы и изображения ПЕРВЫМИ (не режутся)
    all_atoms = []
    for t in tables:
        t["ordinal"] = len(all_atoms)
        hint = {"table_no": t.get("table_no"), "title": t.get("title"), "page": t.get("page")}
        pg = t.get("page")
        if pg and page_map.get(pg):
            hint.update({k: v for k, v in page_map[pg].items() if k != "page"})
        t["metadata_hint"] = hint
        all_atoms.append(t)
    for im in images:
        im["ordinal"] = len(all_atoms)
        im["metadata_hint"] = {"fig_no": im.get("fig_no"), "file_path": im.get("file_path"), "page": im.get("page")}
        all_atoms.append(im)
    for a in text_atoms:
        a["ordinal"] = len(all_atoms)
        hint = {"page": a.get("page")}
        hint.update(a.get("structure_meta") or {})
        a["metadata_hint"] = hint
        all_atoms.append(a)

    print(f"      Всего атомов: {len(all_atoms)}")

    print("[3/4] Обогащение DeepSeek (параллельно, только текст-атомы)...")
    enriched = []

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
                    "atom_type": atom["atom_type"], **({"page": atom.get("page")} if atom.get("page") else {}),
                    "source_doc": doc_title}})
    print(f"      Обогащено: {len(enriched)} атомов")

    print("[4/4] Запись в PostgreSQL + atom_links...")
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
        source_id_tmp = row[0]
        cur.execute(
            "SELECT a.metadata->>'doc_kind' FROM atoms a "
            "JOIN versions v ON v.id = a.version_id "
            "WHERE v.source_id = %s AND a.status = 'active' "
            "AND a.metadata ? 'doc_kind' ORDER BY v.version_no DESC, a.id LIMIT 1",
            (source_id_tmp,),
        )
        last_kind = cur.fetchone()
        last_kind = last_kind[0] if last_kind else None
        want_kind = None if doc_kind == "none" else (struct_ctx.doc_kind if struct_ctx else None)
        if doc_kind == "auto" or want_kind == last_kind:
            conn.rollback()
            cur.close()
            conn.close()
            print("      Без изменений (sha совпал), импорт пропущен")
            return 0, 0
        print(
            f"      sha совпал, но --doc-kind изменился ({last_kind!r} → {want_kind!r}) — новая версия",
            file=sys.stderr,
        )
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
        if hint.get("caption"):
            meta["caption"] = hint["caption"]
        for k in STRUCTURE_META_KEYS:
            if hint.get(k) is not None and k not in meta:
                meta[k] = hint[k]

        cur.execute(
            "INSERT INTO atoms (version_id, document_id, atom_type, ordinal, content, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb) RETURNING id",
            (version_id, source_id, atom["atom_type"], atom["ordinal"], atom["content"],
             json.dumps(meta, ensure_ascii=False)))
        atom_ids[atom["ordinal"]] = cur.fetchone()[0]

    # Резолвинг refs → atom_links: одна карта table_no/fig_no → id на версию.
    # Сопоставление по типу ссылки — таблица не привязывается к рисунку.
    cur.execute(
        "SELECT id, atom_type, metadata->>'table_no' AS tn, metadata->>'fig_no' AS fn "
        "FROM atoms WHERE version_id=%s AND status='active' ORDER BY id",
        (version_id,))
    table_idx, fig_idx = {}, {}
    for aid, atype, tn, fn in cur.fetchall():
        if tn:
            table_idx.setdefault(normalize_table_no(tn), []).append(aid)
        if fn:
            fig_idx.setdefault(normalize_fig_no(fn), []).append(aid)

    inserts = []
    for atom in enriched:
        refs = atom.get("metadata", {}).get("refs", [])
        from_id = atom_ids.get(atom["ordinal"])
        if not from_id or not refs:
            continue
        for ref in refs:
            target = str(ref.get("target", "")).strip()
            rtype = str(ref.get("type", "")).lower()
            if not target:
                continue
            to_id = None
            if rtype in ("table", "appendix"):
                cands = table_idx.get(normalize_table_no(target), [])
                if cands:
                    to_id = cands[0]
            elif rtype in ("figure", "image"):
                cands = fig_idx.get(normalize_fig_no(target), [])
                if cands:
                    to_id = cands[0]
            else:
                print(f"      неизвестный тип ссылки '{rtype}', пропущено", file=sys.stderr)
                continue
            if to_id and to_id != from_id:
                inserts.append((from_id, to_id, f"references_{rtype}"))

    links = 0
    if inserts:
        from psycopg2.extras import execute_values
        execute_values(cur,
            "INSERT INTO atom_links (from_atom, to_atom, rel_type) VALUES %s "
            "ON CONFLICT DO NOTHING", inserts)
        links = cur.rowcount

    cur.execute(
        "INSERT INTO journal (op_type, details) VALUES ('import', %s::jsonb)",
        (json.dumps({"source_id": source_id, "version_id": version_id,
                     "version_no": version_no, "atoms": len(enriched),
                     "doc_kind": struct_ctx.doc_kind if struct_ctx else None,
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

    if not getattr(import_doc, "_no_embed", False):
        try:
            from embed_atoms import embed_atoms_for_version

            n_emb, ew = embed_atoms_for_version(version_id)
            for w in ew:
                print(w, file=sys.stderr)
            if n_emb:
                print(f"      Эмбеддинги: {n_emb} атомов", file=sys.stderr)
        except Exception as e:
            print(
                f"      атомы сохранены без векторов: {e}; выполните scripts/embed_atoms.py",
                file=sys.stderr,
            )

    return len(enriched), links


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--project", default="default")
    parser.add_argument("--no-embed", action="store_true", help="не считать эмбеддинги после импорта")
    parser.add_argument(
        "--doc-kind",
        default="auto",
        choices=["auto", "code", "gost", "sdank", "none"],
        help="структурная нарезка: кодекс, ГОСТ/СДАНК или обычный PDF (none/auto)",
    )
    parser.add_argument("--redaction", default="", help="редакция документа (перекрывает автоизвлечение)")
    parser.add_argument("--effective-date", default="", help="дата вступления в силу (ISO или DD.MM.YYYY)")
    args = parser.parse_args()
    if args.no_embed:
        import_doc._no_embed = True
    n_atoms, n_links = import_doc(
        args.file,
        args.project,
        doc_kind=args.doc_kind,
        redaction=args.redaction or None,
        effective_date=args.effective_date or None,
    )
    print(f"\n✅ Импортировано атомов: {n_atoms}, связей: {n_links}")
