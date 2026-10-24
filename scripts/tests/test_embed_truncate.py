"""Регрессия: оценка/усечение токенов для HTML-таблиц (баг из PR: HTTP 400
на длинных таблицах при backfill)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from embeddings import estimate_tokens, truncate_to_tokens  # noqa: E402


def test_estimate_conservative_for_html():
    # HTML-таблицы дают ~1.5 симв/токен; старая len/3 пропускала их мимо усечения.
    text = "<table><tr><td>" + "показатель контроля " * 500 + "</td></tr></table>"
    assert estimate_tokens(text) >= len(text) // 3


def test_truncate_long_html_table():
    # ~16671 симв. — как реальная длинная таблица, дававшая 8193 токена при 8192.
    text = "<table><tr><td>" + "значение допуска " * 1300 + "</td></tr></table>"
    cut, trunc = truncate_to_tokens(text, 8192)
    assert trunc is True
    # усекаем с запасом ~30%, поэтому длина симв. не должна превышать лимит
    assert len(cut) <= int(8192 * 1.4) + 4


def test_short_text_not_truncated():
    text = "короткий текст атома"
    cut, trunc = truncate_to_tokens(text, 8192)
    assert trunc is False
    assert cut == text