"""ФЗ: inline-часть 1 и колонтитул КонсультантПлюс vs «2.» после разрыва страницы."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_document import normalize_text, quality_gate
from structure import DocImportOptions, prepare_for_import, structure_split


def _atoms_from_md(md: str, *, title: str = "case.pdf") -> list[dict]:
    opts = DocImportOptions(doc_kind="code", source_title=title)
    md = normalize_text(md)
    md2, ctx, _ = prepare_for_import(md, opts)
    assert ctx is not None
    atoms, _ = quality_gate(
        structure_split(md2, ctx, chunk_max=900, chunk_min=30)
    )
    return atoms


def _meta_keys(atoms: list[dict]) -> list[tuple[str | None, str | None]]:
    out = []
    for a in atoms:
        m = a.get("structure_meta") or {}
        if m.get("article"):
            out.append((str(m.get("article")), str(m.get("point") or "")))
    return out


class FzColontitelTests(unittest.TestCase):
    def test_fz118_inline_article_body_is_point_one(self):
        md = (
            "118-ФЗ\n\n"
            "Статья 1. Ввести в действие часть вторую Налогового кодекса "
            '(глава 21 "НДС"; глава 22 "Акцизы") с 1 января 2001 года.\n\n'
            "Статья 3. Текст статьи 3 достаточной длины для quality gate filter."
        )
        keys = _meta_keys(_atoms_from_md(md))
        self.assertIn(("1", "1"), keys)
        self.assertIn(("3", "1"), keys)

    def test_fz44_colontitel_not_glued_to_point_two(self):
        fz = (
            'Федеральный закон от 05.04.2013 N 44-ФЗ (ред. от 08.08.2024) '
            '"О контрактной системе в сфере закупок товаров, работ, услуг"'
        )
        md = (
            f"{fz}\n\n"
            "Глава 1. Общие положения\n\n"
            "Статья 1. Основные положения\n\n"
            "1. Текст части первой статьи один достаточной длины для quality gate filter test.\n\n"
            f"<!-- страница 2 --> {fz} "
            "2. Текст части второй статьи один достаточной длины для quality gate filter test case."
        )
        keys = _meta_keys(_atoms_from_md(md, title="fz44_hdr.pdf"))
        self.assertIn(("1", "1"), keys)
        self.assertIn(("1", "2"), keys)


if __name__ == "__main__":
    unittest.main()
