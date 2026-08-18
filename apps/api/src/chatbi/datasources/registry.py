"""kind → 驱动 的映射。外界取用驱动的唯一入口。

惰性 import：get_driver("mysql") 时才去 import mysql 模块。否则没装
clickhouse-connect 的环境里，连 import chatbi.main 都会炸——而 P2c/P3/P4 的
开发者不该为了跑前端或管线测试去装三个数据库驱动包。
"""

from functools import lru_cache
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chatbi.datasources.drivers.base import Driver

# kind → (模块路径, 类名)。新增驱动只改这张表；值是字符串，所以这里不触发 import。
_DRIVERS: dict[str, tuple[str, str]] = {
    "postgres": ("chatbi.datasources.drivers.postgres", "PostgresDriver"),
    "mysql": ("chatbi.datasources.drivers.mysql", "MySQLDriver"),
    "clickhouse": ("chatbi.datasources.drivers.clickhouse", "ClickHouseDriver"),
}


class UnknownDriver(ValueError):
    """没有这个 kind 对应的驱动。"""


def registered_kinds() -> tuple[str, ...]:
    """已登记的 kind。**不触发任何 import**——测试钉住了这条。"""
    return tuple(_DRIVERS)


@lru_cache
def get_driver(kind: str) -> "Driver":
    """取驱动实例。驱动无状态，所以共享一个实例（lru_cache）。"""
    try:
        module_path, class_name = _DRIVERS[kind]
    except KeyError as exc:
        raise UnknownDriver(f"没有 kind={kind!r} 的驱动，已登记的是 {sorted(_DRIVERS)}") from exc
    return getattr(import_module(module_path), class_name)()
