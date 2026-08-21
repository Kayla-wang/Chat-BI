"""runs 与 run_result_previews 的仓储（P3b 设计 §5.1、§9）。

run_events 仍然只有 append_event / list_events / next_seq（P3a + p3b1 Task 1），本文件测的
是另两张表——**它们不是 append-only 的**，run 的状态本来就要从 drafted 变到终态。
"""

import uuid

import pytest

from chatbi.db.models import Conversation, Run, RunResultPreview
from chatbi.runs.repository import (
    append_event,
    get_run,
    mark_finished,
    mark_running,
    next_seq,
    save_preview,
)


@pytest.fixture
def make_run(db_session, make_user, make_datasource):
    def _make(status: str = "drafted") -> Run:
        user, datasource = make_user(), make_datasource()
        conversation = Conversation(
            id=uuid.uuid4(), user_id=user.id, datasource_id=datasource.id, title="t"
        )
        db_session.add(conversation)
        db_session.flush()
        run = Run(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            user_id=user.id,
            datasource_id=datasource.id,
            question="q",
            status=status,
        )
        db_session.add(run)
        db_session.flush()
        return run

    return _make


def test_get_run_returns_none_for_an_unknown_id(db_session) -> None:
    assert get_run(db_session, uuid.uuid4()) is None


def test_mark_running_moves_a_drafted_run(db_session, make_run) -> None:
    run = make_run("drafted")

    assert (
        mark_running(db_session, run.id, final_sql="select 1", effective_sql="SELECT 1 LIMIT 1000")
        is True
    )

    db_session.expire_all()
    refreshed = get_run(db_session, run.id)
    assert refreshed.status == "running"
    assert refreshed.final_sql == "select 1"
    assert refreshed.effective_sql == "SELECT 1 LIMIT 1000"
    assert refreshed.executed_at is not None


@pytest.mark.parametrize("status", ["running", "succeeded", "failed", "cancelled", "blocked"])
def test_mark_running_refuses_any_non_drafted_run(db_session, make_run, status: str) -> None:
    """**一个 run 恰好执行一次**（设计 §5）。返回 False 让调用方给 409。

    `running` 也在列表里——那条正是双击运行按钮的防护，而它是免费得到的：第二次请求打在
    running 上，条件 UPDATE 匹配不到行。
    """
    run = make_run(status)

    assert mark_running(db_session, run.id, final_sql="s", effective_sql="s") is False

    db_session.expire_all()
    assert get_run(db_session, run.id).status == status  # 状态没被动


def test_mark_running_uses_a_conditional_update_not_check_then_update(db_session, make_run) -> None:
    """并发保护靠 DB 而不是靠先查后改（设计 §5.1）。

    直接模拟并发很难，所以这里验的是**它的可观察后果**：第二次 mark_running 必须失败，
    且不覆盖第一次写的 final_sql。check-then-update 的实现在两个并发请求下会双双通过
    检查——那种失败在测试里看不到，但这条至少钉住了「它是按 status 条件写的」。
    """
    run = make_run("drafted")

    assert mark_running(db_session, run.id, final_sql="a", effective_sql="a") is True
    assert mark_running(db_session, run.id, final_sql="b", effective_sql="b") is False

    db_session.expire_all()
    assert get_run(db_session, run.id).final_sql == "a"  # 第二次没覆盖第一次


def test_mark_running_returns_false_for_an_unknown_run(db_session) -> None:
    assert mark_running(db_session, uuid.uuid4(), final_sql="s", effective_sql="s") is False


def test_mark_finished_records_the_outcome(db_session, make_run) -> None:
    run = make_run("running")

    mark_finished(db_session, run.id, status="succeeded", row_count=42, duration_ms=1234)

    db_session.expire_all()
    refreshed = get_run(db_session, run.id)
    assert refreshed.status == "succeeded"
    assert refreshed.row_count == 42
    assert refreshed.duration_ms == 1234
    assert refreshed.error_code is None


def test_mark_finished_records_an_error_code(db_session, make_run) -> None:
    """失败路径也要落库——F-304 要审计的正是这些（设计 §2.2）。"""
    run = make_run("running")

    mark_finished(db_session, run.id, status="failed", error_code="QUERY_TIMEOUT")

    db_session.expire_all()
    refreshed = get_run(db_session, run.id)
    assert refreshed.status == "failed"
    assert refreshed.error_code == "QUERY_TIMEOUT"
    assert refreshed.row_count is None


def test_mark_finished_works_on_a_blocked_run_that_never_ran(db_session, make_run) -> None:
    """blocked 是从 drafted **直接**来的（guard 判定不通过，从未 running 过）。

    若 mark_finished 加了 `where status = 'running'` 的条件，这条路径会静默不落库——而
    被拒的执行同样要有审计（F-304）。
    """
    run = make_run("drafted")

    mark_finished(db_session, run.id, status="blocked", error_code="WRITE_BLOCKED")

    db_session.expire_all()
    assert get_run(db_session, run.id).status == "blocked"


def test_next_seq_starts_at_one_for_a_fresh_run(db_session, make_run) -> None:
    assert next_seq(db_session, make_run().id) == 1


def test_next_seq_continues_after_existing_events(db_session, make_run) -> None:
    """**接上 P3c 时的关键一条**（设计 §13）。

    问答流会先写 understand / generate 两条事件（seq 1、2），执行流必须从 3 续。硬编码
    seq=1 的实现在本份的测试里全绿（本份的 run 都是干净的），接上 P3c 之后
    `unique (run_id, seq)` 会拒绝重复的 1，而那时报错出现在执行流里、看起来像执行流的 bug。
    """
    run = make_run()
    append_event(db_session, run_id=run.id, seq=1, step="understand", status="ok")
    append_event(db_session, run_id=run.id, seq=2, step="generate", status="ok")

    assert next_seq(db_session, run.id) == 3


def test_next_seq_is_per_run(db_session, make_run) -> None:
    """seq 是每个 run 独立的（唯一键是 (run_id, seq) 复合的）。"""
    first, second = make_run(), make_run()
    append_event(db_session, run_id=first.id, seq=1, step="x", status="ok")

    assert next_seq(db_session, second.id) == 1


def test_save_preview_stores_the_summary(db_session, make_run) -> None:
    run = make_run("running")

    save_preview(
        db_session,
        run.id,
        columns=[{"name": "id", "type": "integer", "is_numeric": True}],
        rows=[[1], [2]],
        truncated=True,
    )

    db_session.expire_all()
    preview = db_session.get(RunResultPreview, run.id)
    assert preview.rows == [[1], [2]]
    assert preview.truncated is True


def test_save_preview_overwrites_an_existing_one(db_session, make_run) -> None:
    """一个 run 一行（run_id 是主键）。

    实际上一个 run 只执行一次（设计 §5），所以覆盖路径**理论上走不到**——但仓储不该因为
    调用方的约定而在第二次调用时抛 IntegrityError，那种失败会以 500 出现在执行流的末尾、
    把一次**已经成功**的查询变成失败。
    """
    run = make_run("running")
    save_preview(db_session, run.id, columns=[], rows=[[1]], truncated=False)

    save_preview(db_session, run.id, columns=[], rows=[[2]], truncated=False)

    db_session.expire_all()
    assert db_session.get(RunResultPreview, run.id).rows == [[2]]
