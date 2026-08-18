"""注册表。重点是惰性 import——协议层必须能在没装驱动包的环境里工作。"""

import pytest

from chatbi.datasources.registry import UnknownDriver, get_driver
from chatbi.db.models import DATASOURCE_KINDS


def test_every_supported_kind_is_registered() -> None:
    """DATASOURCE_KINDS 里有的 kind，注册表必须都认。

    否则「数据源建得出来但连不上」这个组合会一直存在——CHECK 约束放行了 kind，
    而运行时才发现没有对应驱动。
    """
    from chatbi.datasources.registry import registered_kinds

    assert set(registered_kinds()) == set(DATASOURCE_KINDS)


def test_unknown_kind_raises_a_typed_error() -> None:
    with pytest.raises(UnknownDriver) as exc_info:
        get_driver("oracle")

    # 消息里要带上收到的 kind，否则排障时不知道是谁传错了
    assert "oracle" in str(exc_info.value)


def test_registered_kinds_does_not_import_the_driver_modules() -> None:
    """列出 kind 不该触发 import。

    否则没装 clickhouse-connect 的环境里，任何调用 registered_kinds() 的代码路径
    都会炸——而 P2c/P3/P4 的开发者不该为了跑别的测试去装三个数据库驱动。
    """
    import sys

    from chatbi.datasources.registry import registered_kinds

    for module in list(sys.modules):
        if module.startswith("chatbi.datasources.drivers."):
            del sys.modules[module]

    registered_kinds()

    assert not [m for m in sys.modules if m.startswith("chatbi.datasources.drivers.")]
