"""值对象与协议的语义测试。不连任何库，不 import 任何驱动实现。"""

import pytest

from chatbi.datasources.drivers.base import (
    ConnectionFailed,
    ConnectionInfo,
    DriverError,
    QueryCancelled,
    QueryFailed,
    QueryTimeout,
    truncate,
)


def _info(**overrides) -> ConnectionInfo:
    base = {
        "kind": "postgres",
        "host": "db.internal",
        "port": 5432,
        "database": "analytics",
        "username": "ro_user",
        "password": "super-secret-pw",
    }
    return ConnectionInfo(**(base | overrides))


def test_connection_info_repr_hides_the_password() -> None:
    """这个对象会进异常回溯的局部变量表，而 pytest --showlocals 会原样打出来。"""
    info = _info()

    assert "super-secret-pw" not in repr(info)
    assert "super-secret-pw" not in str(info)
    # 非敏感字段应当仍然可见，否则排障时 repr 毫无用处
    assert "db.internal" in repr(info)


def test_connection_info_repr_hides_the_password_even_when_it_is_none() -> None:
    """None 也要走同一条掩码路径，不能出现 password=None 与 password=*** 两种形状——
    形状不同就等于告诉读者「这个数据源没设密码」。
    """
    assert repr(_info(password=None)) == repr(_info())


def test_connection_info_is_frozen() -> None:
    """驱动拿到的连接信息不可改：改了之后「这条查询连的是哪个库」就说不清了。"""
    info = _info()

    with pytest.raises(Exception):  # noqa: B017 —— dataclasses 抛 FrozenInstanceError
        info.host = "evil.internal"


def test_truncate_reports_truncation_only_when_there_is_an_extra_row() -> None:
    """多取一行来判断——靠 len(rows) == max_rows 猜会在恰好等于上限时误报。"""
    rows = tuple((i,) for i in range(11))

    kept, truncated = truncate(rows, 10)

    assert len(kept) == 10
    assert truncated is True


def test_truncate_does_not_report_truncation_at_exactly_the_limit() -> None:
    rows = tuple((i,) for i in range(10))

    kept, truncated = truncate(rows, 10)

    assert len(kept) == 10
    assert truncated is False


def test_truncate_handles_fewer_rows_than_the_limit() -> None:
    kept, truncated = truncate(((1,), (2,)), 10)

    assert kept == ((1,), (2,))
    assert truncated is False


def test_every_driver_exception_is_a_driver_error() -> None:
    """执行器要能用一个 except 兜住驱动的全部失败，不然新增异常类型时会漏。"""
    for exc_type in (ConnectionFailed, QueryTimeout, QueryCancelled, QueryFailed):
        assert issubclass(exc_type, DriverError)


def test_connection_failed_message_carries_no_address() -> None:
    """spec §4.4：CONNECTION_ERROR 的用户可见文案不回显地址端口。

    驱动构造这个异常时只能传通用消息；地址端口进服务端日志，由调用方记。
    """
    exc = ConnectionFailed()

    text = str(exc)
    assert "db.internal" not in text
    assert "5432" not in text
    assert text  # 但不能是空字符串，否则日志里只剩一个类名
