from collections.abc import Iterator
from contextlib import contextmanager

import typer
from sqlalchemy.orm import Session

from chatbi.auth.provisioning import create_user
from chatbi.db.base import get_session_factory
from chatbi.errors import ApiError

app = typer.Typer(help="Chat-BI 管理命令")


@app.callback()
def _main() -> None:
    """Chat-BI 管理命令。

    显式回调是必须的：Typer 在只注册了一个命令且没有回调时会把该命令直接
    当成整个 app（省略子命令名），这样 `create-user` 就不再是必填的子命令
    名，与本文件的测试及 README 里的调用方式（显式写 `create-user`）不一致。
    加一个空回调可以强制 Typer 始终走「分组 + 子命令」的路径。
    """


@contextmanager
def _session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@app.command("create-user")
def create_user_command(
    email: str,
    display_name: str,
    role: str = typer.Option("admin", help="admin / analyst / viewer"),
    password: str = typer.Option(
        ..., prompt="密码", confirmation_prompt="再输一次", hide_input=True
    ),
) -> None:
    """创建账号。私有化部署里账号由管理员发，不开放注册页面。

    失败消息走 stdout 而非 stderr：Click 8.2 起 CliRunner 不再默认把 stderr
    并入 output，走 stdout 能让断言在各版本下都稳定。退出码才是失败的载体。
    """
    try:
        with _session_scope() as session:
            user = create_user(
                session, email=email, display_name=display_name, password=password, role=role
            )
            typer.echo(f"已创建 {user.email}（{user.role}）")
    except ApiError as exc:
        typer.echo(f"失败：{exc.message}")
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        typer.echo(f"失败：{exc}")
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
