"""Охрана тестов, которые пишут в базу.

Тест на разрушение данных нельзя запустить на рабочей базе. Охрана требует:
- переменную окружения ATOM_MEMORY_ALLOW_DESTRUCTIVE_TESTS=1 (явный opt-in);
- TEST_PG_DSN на отдельную базу, имя которой строго `test_*` или `*_test`;
- что эта база реально отличается от рабочей (PG_DSN) по имени, адресу и порту,
  полученным с самого сервера, а не из строки подключения.

Пароли и полный DSN в сообщениях не печатаются.
"""
import os
import re
import unittest

OPTIN_VAR = "ATOM_MEMORY_ALLOW_DESTRUCTIVE_TESTS"
NAME_RX = re.compile(r"^(?:test_[a-z0-9_]+|[a-z0-9_]+_test)$")


def _facts(dsn: str):
    """(current_database, inet_server_addr, inet_server_port) с самого сервера."""
    import psycopg2
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        cur.execute("SELECT current_database(), inet_server_addr(), inet_server_port()")
        return cur.fetchone()
    finally:
        conn.close()


def assess(test_dsn: str, prod_dsn: str):
    """Возвращает (mode, reason), mode ∈ {'ok', 'skip', 'fail'}."""
    if not test_dsn:
        return ("skip", "TEST_PG_DSN не задан — тест работает только на отдельной базе")
    if os.environ.get(OPTIN_VAR) != "1":
        return ("skip", f"нужен {OPTIN_VAR}=1: тест пишет в базу и не запускается молча")
    try:
        t_db, t_addr, t_port = _facts(test_dsn)
    except Exception as e:
        return ("fail", f"не удалось подключиться к тестовой базе: {type(e).__name__}")
    if not NAME_RX.match(t_db):
        return ("fail", f"имя тестовой базы '{t_db}' не подходит под test_* / *_test")
    if prod_dsn:
        try:
            p_db, p_addr, p_port = _facts(prod_dsn)
        except Exception:
            return ("fail", "PG_DSN задан, но подключиться к рабочей базе не удалось — сравнить невозможно")
        if t_db == p_db:
            if t_addr is None or p_addr is None:
                return ("fail", f"подключение через unix-сокет, отличить '{t_db}' от рабочей нельзя")
            if t_addr == p_addr and t_port == p_port:
                return ("fail", f"тестовая база '{t_db}' — это и есть рабочая; отказ")
    return ("ok", None)


def require(test_dsn: str, prod_dsn: str):
    """SkipTest, если пропустить; AssertionError, если настроено неверно."""
    mode, reason = assess(test_dsn, prod_dsn)
    if mode == "skip":
        raise unittest.SkipTest(reason)
    if mode == "fail":
        raise AssertionError(reason)