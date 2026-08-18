import os
import subprocess
from pathlib import Path

from sqlalchemy import create_engine, inspect

API_ROOT = Path(__file__).resolve().parents[1]


def _alembic(*args: str) -> None:
    subprocess.run(["uv", "run", "alembic", *args], cwd=API_ROOT, check=True)


def _table_names() -> set[str]:
    engine = create_engine(os.environ["CHATBI_DATABASE_URL"])
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


TABLES = {"users", "sessions", "datasources", "datasource_grants"}


def test_migrations_roundtrip(_migrated: None) -> None:
    """从 head 出发 down 到底再 up 回 head，结束时状态与开始时一致。"""
    assert TABLES <= _table_names()

    _alembic("downgrade", "base")
    assert not TABLES & _table_names()

    _alembic("upgrade", "head")
    assert TABLES <= _table_names()
