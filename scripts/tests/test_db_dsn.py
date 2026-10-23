from db_dsn import admin_dsn_for_database


def test_admin_dsn_preserves_query():
    admin = "postgresql://u:p@host:5432/postgres?sslmode=require"
    assert admin_dsn_for_database(admin, "memory_test") == (
        "postgresql://u:p@host:5432/memory_test?sslmode=require"
    )
