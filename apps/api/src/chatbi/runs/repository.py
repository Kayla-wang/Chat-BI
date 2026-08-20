"""run 事件流的持久化。

**这个模块只有 append 与 list，没有 update、没有 delete。** 上游 spec §2.5 与 §4.6 都
要求 run_events 是 append-only（F-304 全链路可审计），落实方式就是仓储的形状——往这里加
一个 update_event 会让那个承诺失效，而不会有任何测试因此变红，所以
tests/test_run_events.py 里有一条测试专门扫本模块的导出名。

不 import fastapi：持久化是领域逻辑（spec §1.3 规则 2）。
"""

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from chatbi.db.models import RunEvent


def append_event(
    session: Session,
    *,
    run_id: uuid.UUID,
    seq: int,
    step: str,
    status: str,
    duration_ms: int | None = None,
    detail: dict[str, Any] | None = None,
) -> RunEvent:
    """追加一条事件。

    seq 由调用方给（执行流按事件顺序从 1 递增）。`unique (run_id, seq)` 会在重放一个已
    用过的 seq 时抛 IntegrityError——**那说明调用方的序号管理有 bug，不要 catch 掉它来
    「修复」**。

    detail 里**不放结果行内容**（上游 §4.6：不记录结果行内容到日志，只记行数）。结果摘要
    存 run_result_previews，受同样的权限控制；事件流是运维视角的，不该成为数据外泄的旁路。
    """
    event = RunEvent(
        run_id=run_id,
        seq=seq,
        step=step,
        status=status,
        duration_ms=duration_ms,
        detail=detail,
    )
    session.add(event)
    session.flush()
    return event


def list_events(session: Session, run_id: uuid.UUID) -> list[RunEvent]:
    """按 seq 升序。**不按 at 排序**——同毫秒内的事件顺序不确定，而回放要的是确定的
    顺序。也不按 id 排：id 是插入顺序，而 seq 是逻辑顺序，两者在乱序 append 时会不一致。
    """
    statement = sa.select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
    return list(session.scalars(statement))
