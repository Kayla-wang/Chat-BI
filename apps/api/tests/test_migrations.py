import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, inspect

API_ROOT = Path(__file__).resolve().parents[1]


def _alembic(*args: str) -> None:
    subprocess.run(["uv", "run", "alembic", *args], cwd=API_ROOT, check=True)


def _table_names(schema: str | None = None) -> set[str]:
    engine = create_engine(os.environ["CHATBI_DATABASE_URL"])
    try:
        return set(inspect(engine).get_table_names(schema=schema))
    finally:
        engine.dispose()


TABLES = {"users", "sessions", "datasources", "datasource_grants"}
# demo 表不在默认 schema 里，get_table_names() 看不到，要单独断言
DEMO_TABLES = {"customers", "orders", "products"}


def test_migrations_roundtrip(_migrated: None) -> None:
    """从 head 出发 down 到底再 up 回 head，结束时状态与开始时一致。"""
    assert TABLES <= _table_names()
    assert DEMO_TABLES <= _table_names("demo_sales")

    _alembic("downgrade", "base")
    assert not TABLES & _table_names()
    assert not DEMO_TABLES & _table_names("demo_sales")

    _alembic("upgrade", "head")
    assert TABLES <= _table_names()
    assert DEMO_TABLES <= _table_names("demo_sales")
