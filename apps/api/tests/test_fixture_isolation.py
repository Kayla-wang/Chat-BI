import os
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from chatbi.db.models import User


@pytest.mark.parametrize(
    ("join_mode", "row_should_survive"),
    [
        ("create_savepoint", False),
        ("control_fully", True),
    ],
)
def test_join_transaction_mode_controls_leak_on_commit(
    _migrated: None, join_mode: str, row_should_survive: bool
) -> None:
    """直接复刻 conftest.db_session 的连接/事务结构（engine -> connection ->
    connection.begin() -> 绑定其上的 Session），但把 join_transaction_mode 当参数化变量：

    - "create_savepoint" 必须隔离：session.commit() 只释放 SAVEPOINT，外层
      transaction.rollback() 之后这行必须消失。
    - "control_fully" 必须真泄漏：这个模式把事务控制权完全交给 Session，
      commit() 会真正结束外层事务，外层 rollback() 管不到已提交的行。

    两个方向都断言，任何一边失败都说明 conftest.db_session 当前用的
    create_savepoint 模式失去了隔离保证——这是这个测试存在的意义。
    """
    email = f"join-mode-probe-{join_mode}@example.com"
    engine = create_engine(os.environ["CHATBI_DATABASE_URL"])
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode=join_mode
    )()
    try:
        session.add(
            User(
                id=uuid.uuid4(),
                email=email,
                display_name="join-mode 探针",
                password_hash="not-a-real-hash",
                role="analyst",
                is_active=True,
            )
        )
        session.commit()
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()

    # 用一个独立的连接检查行是否真的落库——不能复用上面那个连接/事务。
    check_engine = create_engine(os.environ["CHATBI_DATABASE_URL"])
    try:
        with check_engine.connect() as check_connection:
            row = check_connection.execute(select(User).where(User.email == email)).first()
        survived = row is not None

        if survived:
            # control_fully 分支下 commit() 是真实提交，行已经落进 chatbi_test。
            # 外层 rollback 对它无效，这里显式删掉，避免撞 email 唯一索引或
            # 污染下一次测试运行——这是故意的清理，不是遗留代码。
            with check_engine.begin() as cleanup_connection:
                cleanup_connection.execute(User.__table__.delete().where(User.email == email))

        assert survived == row_should_survive
    finally:
        check_engine.dispose()
