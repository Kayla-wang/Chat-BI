"""四张表的约束与外键行为（上游 spec §2.5）。

用 count 而不是 session.get() 验删除行为：四个模型都**没有定义 relationship**（db 是
叶子模块），所以 SQLAlchemy 不知道 DB 级的 ON DELETE CASCADE——identity map 里的旧对象
会被直接返回，断言永远看不到 CASCADE 生效。这个坑 P2c1 踩过一次。
"""

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from chatbi.db.models import Conversation, Run, RunEvent, RunResultPreview


def _count(session, model) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(model))


@pytest.fixture
def make_conversation(db_session, make_user, make_datasource):
    def _make(**kwargs):
        conversation = Conversation(
            id=uuid.uuid4(),
            user_id=kwargs.get("user_id") or make_user().id,
            datasource_id=kwargs.get("datasource_id") or make_datasource().id,
            title=kwargs.get("title", "月度营收"),
        )
        db_session.add(conversation)
        db_session.flush()
        return conversation

    return _make


@pytest.fixture
def make_run(db_session, make_conversation):
    def _make(**kwargs):
        conversation = kwargs.get("conversation") or make_conversation()
        run = Run(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            user_id=conversation.user_id,
            datasource_id=conversation.datasource_id,
            question=kwargs.get("question", "上个月营收多少"),
            status=kwargs.get("status", "drafted"),
            parent_run_id=kwargs.get("parent_run_id"),
        )
        db_session.add(run)
        db_session.flush()
        return run

    return _make


def test_deleting_a_conversation_takes_its_runs(db_session, make_run) -> None:
    """runs.conversation_id 是 CASCADE：run 脱离会话没有意义。"""
    run = make_run()
    conversation = db_session.get(Conversation, run.conversation_id)
    assert _count(db_session, Run) == 1

    db_session.delete(conversation)
    db_session.flush()

    assert _count(db_session, Run) == 0


def test_deleting_a_run_takes_its_events_and_preview(db_session, make_run) -> None:
    """两张从表都是 CASCADE。"""
    run = make_run()
    db_session.add(RunEvent(run_id=run.id, seq=1, step="validate", status="ok", detail={}))
    db_session.add(RunResultPreview(run_id=run.id, columns=[], rows=[], truncated=False))
    db_session.flush()

    db_session.delete(run)
    db_session.flush()

    assert _count(db_session, RunEvent) == 0
    assert _count(db_session, RunResultPreview) == 0


def test_a_datasource_with_history_cannot_be_deleted(db_session, make_run) -> None:
    """runs.datasource_id 与 conversations.datasource_id 都是 RESTRICT：删数据源不该
    静默销毁历史问答记录。要删得先处理历史——这是**有意的摩擦**（设计 §5.1）。

    与 P2c 的 schema_cache / column_notes 用 CASCADE 是有意的不同：缓存与注释是可重建的
    派生数据，run 是不可重建的审计记录。
    """
    from chatbi.db.models import Datasource

    run = make_run()
    datasource = db_session.get(Datasource, run.datasource_id)

    db_session.delete(datasource)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_run_pins_its_own_datasource_even_when_the_conversation_points_elsewhere(
    db_session, make_conversation, make_datasource
) -> None:
    """`runs.datasource_id` 的 RESTRICT 需要**独立的**守卫。

    上一条测试其实守不住它：`make_run` 让 run 与 conversation 用同一个数据源，而
    `conversations.datasource_id` 也是 RESTRICT，所以删数据源时**conversations 那条外键
    先拦住了**。反向验证时把 `runs.datasource_id` 改成 CASCADE，上一条依然全绿——这条
    缺口就是那次发现的。

    这里让 run 指向另一个数据源，删它时只有 runs 这条外键能拦。
    """
    from chatbi.db.models import Datasource

    conversation = make_conversation()
    other = make_datasource()
    run = Run(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        datasource_id=other.id,  # 与 conversation 的不同
        question="q",
        status="drafted",
    )
    db_session.add(run)
    db_session.flush()

    db_session.delete(db_session.get(Datasource, other.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_a_parent_run_only_breaks_the_link(db_session, make_run) -> None:
    """runs.parent_run_id 是 SET NULL（F-401 下钻链路）：删掉父 run 不该连带删掉下钻
    出来的子 run，断链就够。所以这一列可空。
    """
    parent = make_run()
    child = make_run(
        conversation=db_session.get(Conversation, parent.conversation_id),
        parent_run_id=parent.id,
    )

    db_session.delete(parent)
    db_session.flush()
    db_session.expire_all()

    assert _count(db_session, Run) == 1
    assert db_session.get(Run, child.id).parent_run_id is None


def test_an_unknown_run_status_is_rejected(db_session, make_run) -> None:
    """status 的 CHECK 在 migration 里（与 users.role / datasources.kind 一致）。

    非法值必须**短于 String(20)**：写一个 23 字符的值会先撞列长度限制抛 DataError，
    于是这条测试看起来是绿的，实际守的是列宽而不是 CHECK 约束。
    """
    run = make_run()
    run.status = "nope"

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_status_constant_matches_the_check_constraint(db_session, make_run) -> None:
    """RUN_STATUSES 与 migration 0006 的 ck_runs_status 是两份字面量（migration 是历史
    快照，不引用常量）。这条把两者钉在一起——常量加了新状态但 CHECK 没改的话，那个状态
    在生产上会被 DB 拒绝，而错误出现在 P3b 的执行流里，完全不指向这里。
    """
    from chatbi.db.models import RUN_STATUSES

    run = make_run()
    for status in RUN_STATUSES:
        run.status = status
        db_session.flush()  # 每一个都必须被 CHECK 接受

    assert len(RUN_STATUSES) == 7


def test_the_same_seq_cannot_be_used_twice_for_one_run(db_session, make_run) -> None:
    """unique (run_id, seq) 是 append-only 的**真正守卫**：即使有人绕过仓储直接写，
    重放一个已用过的 seq 也会被 DB 拒绝（设计 §5.2）。
    """
    run = make_run()
    db_session.add(RunEvent(run_id=run.id, seq=1, step="validate", status="ok"))
    db_session.flush()

    db_session.add(RunEvent(run_id=run.id, seq=1, step="execute", status="ok"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_two_runs_can_both_use_seq_one(db_session, make_run) -> None:
    """唯一键是 (run_id, seq) 复合的。写成只对 seq 唯一会让第二个 run 无法记事件——
    而那个失败要到 P3b 才会出现，报错也不指向这里。
    """
    first, second = make_run(), make_run()
    db_session.add(RunEvent(run_id=first.id, seq=1, step="validate", status="ok"))
    db_session.add(RunEvent(run_id=second.id, seq=1, step="validate", status="ok"))
    db_session.flush()

    assert _count(db_session, RunEvent) == 2
