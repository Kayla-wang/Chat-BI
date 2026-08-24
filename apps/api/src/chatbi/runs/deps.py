"""run 的 FastAPI 依赖。

与 datasources/deps.py 同形：只做「取 + 判定 + 抛 ApiError」。不 import 驱动、不 import
crypto——HTTP 层没有任何需要明文密码的理由。
"""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from chatbi.auth.deps import current_user
from chatbi.datasources.repository import get_visible
from chatbi.db.base import get_db
from chatbi.db.models import Run, User
from chatbi.errors import PERMISSION_DENIED, RUN_NOT_FOUND, ApiError
from chatbi.runs.repository import get_run


def require_run(
    run_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> Run:
    """按路径参数取 run，三条不满足任一就抛（P3b 设计 §6）。

    参数名必须叫 run_id——FastAPI 按名字从路径 {run_id} 里取。

    **不存在与不属于本人都是 404**，不是 403。理由与 datasources 的做法**有意不同**：
    数据源是**共享资源**，一个 analyst 知道「有这么个数据源但我没被授权」是合理的、
    也是他去找管理员要授权的前提；run 是**私有资源**，没有这个诉求，而用 403 区分
    「不存在」与「存在但不是你的」会确认那个 id 存在。

    另两条是 403（「你不该做这件事」而不是「它不存在」）：
    - 角色是 viewer：上游 spec §4.2 明写「viewer 只看历史，不能执行」。**这一条不被
      下一条覆盖**——一个 viewer 完全可以有 can_query 授权（grants 表不区分角色），
      漏了它 viewer 就能执行查询。
    - 对 run.datasource_id 没有 can_query：授权可能在 run 创建**之后**被撤销，
      不重新检查等于给了一条绕过 datasource_grants 的路。

    **admin 也不例外**（设计 §6.2）：他要停掉一条跑飞的查询，正确的路径是去数据库侧
    kill，而不是在应用里给自己开一个能操作别人 run 的后门。别因为「admin 应该能管
    一切」的直觉把这里改掉。
    """
    run = get_run(db, run_id)
    if run is None or run.user_id != user.id:
        raise ApiError(*RUN_NOT_FOUND)
    if user.role == "viewer":
        raise ApiError(*PERMISSION_DENIED)
    if get_visible(db, user, run.datasource_id) is None:
        raise ApiError(*PERMISSION_DENIED)
    return run
