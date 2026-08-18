"""模型 → ConnectionInfo 的组装。

这是明文密码从仓储走向驱动的**唯一**一段路。放单独一个模块而不是塞进 repository：
仓储跟着表结构变，这里跟着驱动协议变，两者的变更理由不同。
"""

from chatbi.datasources.drivers.base import ConnectionInfo
from chatbi.datasources.repository import read_password
from chatbi.db.models import Datasource


def connection_info(datasource: Datasource) -> ConnectionInfo:
    """组装驱动的输入。返回值的 repr 已由 ConnectionInfo 掩码。

    调用方只有 /test 与 P3 的执行器。**不要**把返回值整体写进日志——掩码只挡住了
    password，host/port 仍在里面（那是允许进服务端日志的，但不允许进 HTTP 响应）。
    """
    return ConnectionInfo(
        kind=datasource.kind,
        host=datasource.host,
        port=datasource.port,
        database=datasource.database,
        username=datasource.username,
        password=read_password(datasource),
        # 拷一份：options 是 JSONB 映射出来的可变 dict，直接塞进 frozen dataclass
        # 会让「不可变的连接信息」名不副实。
        options=dict(datasource.options or {}),
    )
