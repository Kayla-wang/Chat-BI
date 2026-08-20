"""run_events 的 append-only（上游 spec §2.5、§4.6，F-304）。"""

import uuid

import pytest
import sqlalchemy as sa

from chatbi.db.models import Conversation, Run, RunEvent
from chatbi.runs import repository
from chatbi.runs.repository import append_event, list_events


def _make_run(db_session, user, datasource) -> Run:
    conversation = Conversation(
        id=uuid.uuid4(), user_id=user.id, datasource_id=datasource.id, title="t"
    )
    db_session.add(conversation)
    db_session.flush()
    record = Run(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        user_id=user.id,
        datasource_id=datasource.id,
        question="q",
        status="drafted",
    )
    db_session.add(record)
    db_session.flush()
    return record


@pytest.fixture
def run(db_session, make_user, make_datasource) -> Run:
    return _make_run(db_session, make_user(), make_datasource())


def test_appending_events_keeps_them_in_seq_order(db_session, run) -> None:
    """回放按 seq 排序，**不按 at**：同毫秒内的事件顺序不确定。

    故意乱序 append，验证 list_events 仍按 seq 给出。
    """
    for seq, step in ((3, "execute"), (1, "validate"), (2, "render")):
        append_event(
            db_session,
            run_id=run.id,
            seq=seq,
            step=step,
            status="ok",
            duration_ms=seq * 10,
            detail=None,
        )

    events = list_events(db_session, run.id)

    assert [event.seq for event in events] == [1, 2, 3]
    assert [event.step for event in events] == ["validate", "render", "execute"]


def test_the_repository_has_no_update_or_delete_path(db_session, run) -> None:
    """append-only 的落实方式是**仓储的形状**（设计 §5.2）：模块里不存在 update/delete
    函数。这条测试防的是「有人为了修一个 bug 顺手加一个 update_event」——那会让 F-304
    的承诺失效，而没有任何测试会因此变红。

    不加数据库层的触发器：应用账号必须能 INSERT，用触发器禁 UPDATE 会让 migration 的
    downgrade 变复杂，而收益只是防住故意绕过仓储的人——那种人也能改触发器。
    """
    exported = [name for name in dir(repository) if not name.startswith("_")]

    assert "append_event" in exported
    assert "list_events" in exported
    forbidden = [name for name in exported if "update" in name or "delete" in name]
    assert forbidden == []


def test_list_events_does_not_leak_another_runs_events(
    db_session, run, make_user, make_datasource
) -> None:
    other = _make_run(db_session, make_user(), make_datasource())

    append_event(db_session, run_id=run.id, seq=1, step="validate", status="ok", duration_ms=None)
    append_event(db_session, run_id=other.id, seq=1, step="execute", status="ok", duration_ms=None)

    assert [event.step for event in list_events(db_session, run.id)] == ["validate"]


def test_detail_accepts_none_and_a_dict(db_session, run) -> None:
    """detail 可空。**不放结果行内容**（上游 §4.6：只记行数）——那条约束的执行在 P3b
    写事件的地方，这里只钉住这一列能存 None 与普通 dict。
    """
    append_event(db_session, run_id=run.id, seq=1, step="validate", status="ok")
    append_event(
        db_session,
        run_id=run.id,
        seq=2,
        step="execute",
        status="ok",
        duration_ms=42,
        detail={"row_count": 100},
    )

    events = list_events(db_session, run.id)

    assert events[0].detail is None
    assert events[1].detail == {"row_count": 100}
    assert events[1].duration_ms == 42


def test_events_are_ordered_by_seq_not_by_id(db_session, run) -> None:
    """seq 故意留空档（1, 5, 10）。

    按 id 排和按 seq 排在这个用例下结果相同，所以它单独存在时守不住排序——必须配合上面
    那条乱序 append 的用例。两条一起才能证明是按 seq。
    """
    for seq in (1, 5, 10):
        append_event(db_session, run_id=run.id, seq=seq, step="s", status="ok")

    assert [event.seq for event in list_events(db_session, run.id)] == [1, 5, 10]
    assert db_session.scalar(sa.select(sa.func.count()).select_from(RunEvent)) == 3
