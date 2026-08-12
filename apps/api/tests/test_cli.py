from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from chatbi import cli
from chatbi.db.models import User


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> CliRunner:
    """把 CLI 的会话来源换成测试事务，避免命令真的往库里提交。"""

    @contextmanager
    def _scope():
        yield db_session

    monkeypatch.setattr(cli, "_session_scope", _scope)
    return CliRunner()


def test_create_user_command_creates_an_admin(runner: CliRunner, db_session: Session) -> None:
    result = runner.invoke(
        cli.app,
        ["create-user", "boss@example.com", "老板", "--role", "admin"],
        input="pw-12345678\npw-12345678\n",
    )

    assert result.exit_code == 0
    user = db_session.scalar(select(User).where(User.email == "boss@example.com"))
    assert user is not None
    assert user.role == "admin"


def test_create_user_command_reports_a_duplicate_email(
    runner: CliRunner, db_session: Session, make_user
) -> None:
    make_user(email="boss@example.com")

    result = runner.invoke(
        cli.app,
        ["create-user", "boss@example.com", "老板", "--role", "admin"],
        input="pw-12345678\npw-12345678\n",
    )

    assert result.exit_code == 1
    assert "已存在" in result.output


def test_create_user_command_does_not_echo_the_password(
    runner: CliRunner, db_session: Session
) -> None:
    result = runner.invoke(
        cli.app,
        ["create-user", "boss@example.com", "老板", "--role", "admin"],
        input="pw-12345678\npw-12345678\n",
    )

    assert "pw-12345678" not in result.output
