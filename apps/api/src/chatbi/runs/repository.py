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

from chatbi.db.models import Run, RunEvent, RunResultPreview


def next_seq(session: Session, run_id: uuid.UUID) -> int:
    """下一个可用的事件序号。

    **从 max(seq)+1 续，不是从 1 硬起。** 问答流（P3c）会先写 understand / generate 两条
    事件，执行流必须接在它们后面——硬编码 1 的实现在 P3b 的测试里全绿（那时 run 都是
    干净的），接上 P3c 之后 `unique (run_id, seq)` 会拒绝重复的 1，而报错会出现在执行流
    里、看起来像执行流的 bug。
    """
    current = session.scalar(sa.select(sa.func.max(RunEvent.seq)).where(RunEvent.run_id == run_id))
    return (current or 0) + 1


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


def get_run(session: Session, run_id: uuid.UUID) -> Run | None:
    return session.get(Run, run_id)


def mark_running(
    session: Session, run_id: uuid.UUID, *, final_sql: str, effective_sql: str
) -> bool:
    """drafted -> running。返回 False 表示「它已经不是 drafted 了」（调用方给 409）。

    **带条件的 UPDATE，不是先查状态再改**（P3b 设计 §5.1）：check-then-update 在两个并发
    请求下会双双通过检查，然后双双执行——而一个 run 只装得下一次执行的结果（final_sql /
    row_count / executed_at 都是单列），第二次会静默改写第一次的审计记录。P2a 的仓储用
    insert + IntegrityError 而不是 check-then-insert 是同一条理由。

    顺带：`running` 也不满足条件，所以双击运行按钮的防护是免费得到的。
    """
    result = session.execute(
        sa.update(Run)
        .where(Run.id == run_id, Run.status == "drafted")
        .values(
            status="running",
            final_sql=final_sql,
            effective_sql=effective_sql,
            executed_at=sa.func.now(),
        )
    )
    session.flush()
    return bool(result.rowcount)


def mark_finished(
    session: Session,
    run_id: uuid.UUID,
    *,
    status: str,
    row_count: int | None = None,
    duration_ms: int | None = None,
    error_code: str | None = None,
) -> None:
    """写终态。status ∈ succeeded | failed | cancelled | blocked。

    **不加 `where status = 'running'` 的条件**：blocked 是从 drafted 直接来的（guard 判定
    不通过，从未 running 过），而 cancelled 可能由 cancel_run 先写过一次。加了条件会让这些
    路径静默不落库——而失败路径的审计正是 F-304 最需要的（设计 §2.2）。
    """
    session.execute(
        sa.update(Run)
        .where(Run.id == run_id)
        .values(status=status, row_count=row_count, duration_ms=duration_ms, error_code=error_code)
    )
    session.flush()


def save_preview(
    session: Session,
    run_id: uuid.UUID,
    *,
    columns: list[dict[str, Any]],
    rows: list[list[Any]],
    truncated: bool,
) -> RunResultPreview:
    """结果摘要，一个 run 一行（run_id 是主键）。

    用 get-then-set 而不是纯 insert：一个 run 只执行一次（设计 §5）所以覆盖路径理论上走
    不到，但仓储不该因为调用方的约定而在第二次调用时抛 IntegrityError——那种失败会以 500
    出现在执行流的末尾，把一次**已经成功**的查询变成失败。
    """
    preview = session.get(RunResultPreview, run_id)
    if preview is None:
        preview = RunResultPreview(run_id=run_id, columns=columns, rows=rows, truncated=truncated)
        session.add(preview)
    else:
        preview.columns = columns
        preview.rows = rows
        preview.truncated = truncated
    session.flush()
    return preview
