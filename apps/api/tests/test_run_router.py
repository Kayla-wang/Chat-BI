"""POST / DELETE /api/runs/{run_id}/execute（上游 spec §2.3）。

用假驱动覆盖驱动层——**但注意执行流不用 driver_for 依赖**，它直接调
registry.get_driver()，因为方言与驱动都要从 run.datasource_id 取。所以这里 monkeypatch
掉 api/run_stream.py 里 import 的那个名字（见 with_driver 夹具的说明）。

事件序列的编排在 `api/run_stream.py`（router 只留鉴权与包装），所以本文件的 monkeypatch
目标是 `chatbi.api.run_stream.*` 而不是 router。

**本文件最重要的两条**：test_the_failure_path_commits_before_the_stream_ends（设计 §2
那个只影响失败路径的坑）与 test_cancelling_the_stream_cancels_the_query（客户端断开时
必须掐掉库侧查询）。两条的文档字符串都写了「为什么只能这么测」，改它们之前先读。
"""

import asyncio
import threading
import uuid

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from chatbi.datasources.drivers.base import (
    ColumnSchema,
    ConnectionFailed,
    QueryFailed,
    QueryHandle,
    QueryResult,
    QueryTimeout,
)
from chatbi.db.models import Conversation, Run, RunEvent, RunResultPreview

_RESULT = QueryResult(
    columns=(
        ColumnSchema(name="city", data_type="text"),
        ColumnSchema(name="amount", data_type="numeric", is_numeric=True),
    ),
    rows=(("北京", 100), ("上海", 200)),
    row_count=2,
    truncated=False,
)


class _FakeDriver:
    """只实现 execute 与 cancel。缺 probe / reflect 是**故意**的。"""

    kind = "postgres"  # 必须是真 kind——_DIALECTS 与 connection_info 都按它走

    def __init__(self, *, result=_RESULT, raises=None, block=False) -> None:
        self._result, self._raises, self._block = result, raises, block
        self._released = threading.Event()
        self.started = threading.Event()
        self.cancelled: list[str] = []

    def execute(self, info, sql, *, timeout_seconds, max_rows, on_start=None):
        if on_start is not None:
            on_start(QueryHandle(token="4242"))
        self.started.set()
        if self._raises is ConnectionFailed:
            # **ConnectionFailed 不接受消息参数**（P2b 刻意如此：spec §4.4 要求
            # CONNECTION_ERROR 不回显地址端口，所以它连一个能塞地址的入口都不给）。
            # 与下面那行带原文的 raise 分开写，正是这个区别本身。
            raise ConnectionFailed()
        if self._raises is not None:
            raise self._raises("库侧报错：column x does not exist")
        if self._block:
            self._released.wait(timeout=10)
            from chatbi.datasources.drivers.base import QueryCancelled

            raise QueryCancelled("查询已取消")
        return self._result

    def cancel(self, info, handle) -> None:
        self.cancelled.append(handle.token)
        self._released.set()


@pytest.fixture
def with_driver(monkeypatch):
    """换掉 run_router 里的 get_driver。

    **不能用 dependency_overrides**：run_router 不通过 FastAPI 依赖取驱动（方言与驱动都
    要从 run.datasource_id 推，而那要先取到 run）。
    """

    def _install(driver: _FakeDriver) -> _FakeDriver:
        monkeypatch.setattr("chatbi.api.run_stream.get_driver", lambda kind: driver)
        return driver

    return _install


@pytest.fixture
def make_run(db_session, make_user, make_datasource, login_as, client: TestClient):
    """建一个 drafted 的 run，并把它的所有者登录进 client。

    所有者必须有 can_query——require_run 会重新检查（授权可能在 run 创建后被撤销）。
    admin 无条件可见所有数据源，所以用 admin 最省事。
    """
    from chatbi.execution import registry

    registry.clear()

    def _make(status: str = "drafted") -> Run:
        owner = make_user(role="admin")
        datasource = make_datasource(kind="postgres")
        conversation = Conversation(
            id=uuid.uuid4(), user_id=owner.id, datasource_id=datasource.id, title="t"
        )
        db_session.add(conversation)
        db_session.flush()
        run = Run(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            user_id=owner.id,
            datasource_id=datasource.id,
            question="上个月各城市营收",
            status=status,
        )
        db_session.add(run)
        db_session.flush()
        login_as(owner)
        return run

    yield _make
    registry.clear()


def _events(response) -> list[tuple[str, str]]:
    """把 SSE 流解析成 [(event, data), ...]。"""
    events, current = [], None
    for line in response.iter_lines():
        if line.startswith("event: "):
            current = line.removeprefix("event: ")
        elif line.startswith("data: ") and current is not None:
            events.append((current, line.removeprefix("data: ")))
            current = None
    return events


def _names(events) -> list[str]:
    return [name for name, _ in events]


def test_a_successful_execution_emits_the_full_sequence(
    client: TestClient, make_run, with_driver
) -> None:
    """上游 spec §2.3 的事件序列（设计 §7.2）。"""
    run = make_run()
    with_driver(_FakeDriver())

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select city, amount from t"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _events(response)

    names = _names(events)
    assert names[0] == "validate"
    assert "execute.started" in names
    assert "result" in names
    assert "chart_spec" in names
    assert names[-1] == "done", "**每条流都以 done 结尾**——前端只需要一个终止信号"


def test_the_effective_sql_is_echoed(client: TestClient, make_run, with_driver) -> None:
    """spec §2.3：effective_sql「必须回显（可审计的前提）」。它是注入 LIMIT 后的版本，
    与用户提交的 sql 不同——即使一个字都没改，sqlglot 也会重写整条语句。
    """
    run = make_run()
    with_driver(_FakeDriver())

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select city from t"}
    ) as response:
        events = dict(_events(response))

    assert "LIMIT 1000" in events["execute.started"]


def test_a_blocked_sql_ends_the_stream_without_an_error_event(
    client: TestClient, db_session, make_run, with_driver
) -> None:
    """spec §2.3：「ok=false 时流即结束，run 置 blocked」。

    **不发 error 事件**——判定失败是这条流的正常出口，不是异常（与 P3a 的
    /sql/validate 返回 200 同一个道理）。
    """
    run = make_run()
    with_driver(_FakeDriver())

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "insert into t values (1)"}
    ) as response:
        events = _events(response)

    names = _names(events)
    assert "error" not in names
    assert "execute.started" not in names, "被拒的语句不该下发"
    assert names[-1] == "done"
    assert "WRITE_BLOCKED" in dict(events)["validate"]

    db_session.expire_all()
    assert db_session.get(Run, run.id).status == "blocked"


def test_a_failed_execution_still_records_the_audit_trail(
    client: TestClient, db_session, make_run, with_driver
) -> None:
    """失败路径也要写审计（F-304 要审计的恰恰是失败与被取消的执行）。

    **这条守的是「写了没有」，不是「提交了没有」**——两者在本套件里无法用同一条测试
    区分，见下面 test_the_failure_path_commits_before_the_stream_ends 的说明。别把这条
    的名字理解成它守住了四个提交点。

    用 expire_all() 之后再查：不这样会命中 identity map，连「写了没有」都守不住
    （P2c1 与 p3a2 各踩过一次同形的坑）。
    """
    run = make_run()
    with_driver(_FakeDriver(raises=QueryTimeout))

    with client.stream("POST", f"/api/runs/{run.id}/execute", json={"sql": "select 1"}) as response:
        events = dict(_events(response))

    assert "QUERY_TIMEOUT" in events["error"]

    db_session.expire_all()
    refreshed = db_session.get(Run, run.id)
    assert refreshed.status == "failed"
    assert refreshed.error_code == "QUERY_TIMEOUT"
    steps = db_session.scalars(
        sa.select(RunEvent.step).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)
    ).all()
    assert steps == ["validate", "execute"], "失败路径的事件被回滚了——四个提交点漏了"


def _spy_actions(db_session, monkeypatch) -> list[str]:
    """记录「写 → commit」的先后顺序。

    **为什么守顺序而不是守落库结果**——落库结果在本套件里**无法观察**，这是实施期
    实测出来的（p3b2 反向验证 1、2 都全绿）：

    1. 测试把 get_db 覆盖成共享的 db_session，而未提交的写入对**它自己的事务**本来就
       可见。`expire_all()` 只强制重新 SELECT，那次 SELECT 仍在同一个事务里，照样看得
       见没提交的行。
    2. 换另一个连接去查也不行：夹具的外层事务从头到尾不提交，所以另一条连接**什么都
       看不见**，有没有 commit 都一样。
    3. 唯一让 commit 变得可观察的生产机制是「流中途抛异常 → get_db 回滚」，而
       实测 fastapi 0.141.1 下带 yield 的依赖，退出代码跑在流**之后**：被 catch 掉的
       失败路径（QueryTimeout / QueryFailed / ConnectionFailed）不抛异常，get_db 自己
       会 commit。真正会触发回滚的是**客户端断开**——而 TestClient 造不出断开
       （设计 §11.3 实测 is_disconnected 恒 False）。

    所以这两条测试守的是「写完一段就 commit」这个**代码形状**。守的东西是真的：客户端
    在流中途断开时，没提交的那一段审计会被 get_db 回滚，而 F-304 要审计的恰恰是被取消
    与失败的执行。生产路径由 Task 5 的手工真跑验（断开后审计必须落库）。
    """
    from chatbi.api import run_stream as module

    actions: list[str] = []
    real_commit, real_append, real_mark_running = (
        db_session.commit,
        module.append_event,
        module.mark_running,
    )

    def spy_commit() -> None:
        actions.append("commit")
        real_commit()

    def spy_append(session, **kwargs):
        actions.append(f"append:{kwargs['step']}/{kwargs['status']}")
        return real_append(session, **kwargs)

    def spy_mark_running(session, run_id, **kwargs):
        actions.append("mark_running")
        return real_mark_running(session, run_id, **kwargs)

    monkeypatch.setattr(db_session, "commit", spy_commit)
    monkeypatch.setattr("chatbi.api.run_stream.append_event", spy_append)
    monkeypatch.setattr("chatbi.api.run_stream.mark_running", spy_mark_running)
    return actions


def test_every_write_is_committed_before_the_stream_continues(
    client: TestClient, db_session, make_run, monkeypatch
) -> None:
    """**提交点 1、2、3**（设计 §2）。见 _spy_actions 的说明。

    顺序里两处是硬要求：
    - `mark_running` 之后**紧跟** commit，且在语句下发（execute）**之前**——否则历史
      列表里那条 run 一直显示 drafted，而前端的取消按钮是按状态渲染的。
    - 每次 yield 事件之前，那条事件对应的写入已经提交（先写库再发事件，反过来会出现
      「事件发出去了但没落库」，回放里就缺一条）。
    """
    run = make_run()
    driver = _FakeDriver()
    actions = _spy_actions(db_session, monkeypatch)
    real_execute = driver.execute

    def spy_execute(*args, **kwargs):
        actions.append("execute")
        return real_execute(*args, **kwargs)

    driver.execute = spy_execute
    monkeypatch.setattr("chatbi.api.run_stream.get_driver", lambda kind: driver)

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select city, amount from t"}
    ) as response:
        _events(response)

    assert actions == [
        "append:validate/ok",
        "commit",  # ← 提交点 1
        "mark_running",
        "commit",  # ← 提交点 2，必须在 execute 之前
        "execute",
        "append:execute/ok",
        "append:render/ok",
        "commit",  # ← 提交点 3
    ], f"写与提交的顺序变了（实际 {actions}）"


def test_the_failure_path_commits_before_the_stream_ends(
    client: TestClient, db_session, make_run, with_driver, monkeypatch
) -> None:
    """**提交点 4**，本文件最重要的一条。见 _spy_actions 的说明。

    它的价值在 p3b2 反向验证 1 里得到确认：去掉 `_finish_with_error` 的 commit 之后
    **只有这一条转红**，其余 20 条全绿——包括那条名字里带「审计」的。
    """
    run = make_run()
    with_driver(_FakeDriver(raises=QueryTimeout))
    actions = _spy_actions(db_session, monkeypatch)

    with client.stream("POST", f"/api/runs/{run.id}/execute", json={"sql": "select 1"}) as response:
        _events(response)

    assert actions[-2:] == ["append:execute/failed", "commit"], (
        f"失败路径写完事件之后没有紧跟 commit（实际 {actions}）"
        "——客户端在看到 error 事件后立刻断开时，这段审计会被 get_db 回滚掉"
    )


def test_a_query_failure_carries_the_database_message(
    client: TestClient, make_run, with_driver
) -> None:
    """QUERY_FAILED 的 message **带库的原始报错**——分析师要靠它改 SQL（P2b 的
    QueryFailed 刻意保留了原文）。与 spec §4.4 不冲突：那条针对连接类错误。
    """
    run = make_run()
    with_driver(_FakeDriver(raises=QueryFailed))

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select x from t"}
    ) as response:
        events = dict(_events(response))

    assert "column x does not exist" in events["error"]


def test_a_connection_failure_does_not_leak_the_address(
    client: TestClient, make_run, with_driver
) -> None:
    """spec §4.4：地址端口进服务端日志，不进响应。"""
    run = make_run()
    with_driver(_FakeDriver(raises=ConnectionFailed))

    with client.stream("POST", f"/api/runs/{run.id}/execute", json={"sql": "select 1"}) as response:
        body = "".join(line for line in response.iter_lines())

    assert "CONNECTION_ERROR" in body
    assert "db.internal" not in body  # make_datasource 的默认 host
    assert "5432" not in body


def test_the_result_preview_is_stored(
    client: TestClient, db_session, make_run, with_driver
) -> None:
    run = make_run()
    with_driver(_FakeDriver())

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select city, amount from t"}
    ) as response:
        _events(response)

    db_session.expire_all()
    preview = db_session.get(RunResultPreview, run.id)
    assert preview.rows == [["北京", 100], ["上海", 200]]
    assert preview.truncated is False


def test_the_chart_spec_follows_the_columns(client: TestClient, make_run, with_driver) -> None:
    """1 维度（city）+ 1 度量（amount）→ 柱状（spec §3.5）。"""
    run = make_run()
    with_driver(_FakeDriver())

    with client.stream(
        "POST", f"/api/runs/{run.id}/execute", json={"sql": "select city, amount from t"}
    ) as response:
        events = dict(_events(response))

    assert '"type":"bar"' in events["chart_spec"]
    assert '"x":"city"' in events["chart_spec"]


@pytest.mark.parametrize("status", ["running", "succeeded", "failed", "cancelled", "blocked"])
def test_a_run_can_only_be_executed_once(
    client: TestClient, make_run, with_driver, status: str
) -> None:
    """**409 在流开始之前**（设计 §5）：一旦开了 SSE 流就只能在流里发 error，而那对
    「你点重复了」是很差的体验（前端要解析流才知道请求没被接受）。

    `running` 也在列表里——那正是双击运行按钮的防护。
    """
    run = make_run(status)
    with_driver(_FakeDriver())

    response = client.post(f"/api/runs/{run.id}/execute", json={"sql": "select 1"})

    assert response.status_code == 409
    assert response.json()["code"] == "RUN_NOT_EXECUTABLE"


def test_an_anonymous_request_is_rejected(client: TestClient, make_run) -> None:
    run = make_run()
    client.cookies.clear()

    assert client.post(f"/api/runs/{run.id}/execute", json={"sql": "select 1"}).status_code == 401


def test_an_unknown_run_is_404(client: TestClient, make_run) -> None:
    make_run()  # 登录一个用户

    response = client.post(f"/api/runs/{uuid.uuid4()}/execute", json={"sql": "select 1"})

    assert response.status_code == 404
    assert response.json()["code"] == "RUN_NOT_FOUND"


def test_another_users_run_is_404_not_403(
    client: TestClient, make_run, make_user, login_as
) -> None:
    """**404 而不是 403**（设计 §6.1）：run 是私有资源，用 403 区分「不存在」与
    「存在但不是你的」会确认那个 id 存在。

    这与 require_datasource 的做法**有意不同**——数据源是共享资源，知道「有这么个数据源
    但我没被授权」是合理的，也是去找管理员要授权的前提。
    """
    run = make_run()
    login_as(make_user(role="admin"))  # 换成另一个 admin

    response = client.post(f"/api/runs/{run.id}/execute", json={"sql": "select 1"})

    assert response.status_code == 404
    assert response.json()["code"] == "RUN_NOT_FOUND"


def test_a_viewer_cannot_execute(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    """spec §4.2「viewer 只看历史，不能执行」。

    **这条不被「有没有 can_query」覆盖**——viewer 完全可以有 grant（grants 表不区分
    角色），漏了这条检查 viewer 就能执行查询。
    """
    from chatbi.datasources.repository import set_grant

    viewer = make_user(role="viewer")
    datasource = make_datasource(kind="postgres")
    set_grant(db_session, datasource_id=datasource.id, user_id=viewer.id, can_query=True)
    conversation = Conversation(
        id=uuid.uuid4(), user_id=viewer.id, datasource_id=datasource.id, title="t"
    )
    db_session.add(conversation)
    db_session.flush()
    run = Run(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        user_id=viewer.id,
        datasource_id=datasource.id,
        question="q",
        status="drafted",
    )
    db_session.add(run)
    db_session.flush()
    login_as(viewer)

    response = client.post(f"/api/runs/{run.id}/execute", json={"sql": "select 1"})

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_cancelling_the_stream_cancels_the_query(
    client: TestClient, db_session, make_run, monkeypatch
) -> None:
    """**客户端断开的触发点**（设计 §11.3 那条「无法自动化」的，实施期发现可以自动化）。

    计划原本用 `request.is_disconnected()` 轮询，并把它列为「只能手工真跑验」。实施期在
    真 uvicorn 上装探针实测发现：**那个轮询永远不会被执行到**——Starlette 的
    StreamingResponse 把 body 迭代器与 listen_for_disconnect 放在一个 task group 里赛跑，
    `http.disconnect` 一到就取消迭代器，所以生成器是在 `await asyncio.wait(...)` 处收到
    CancelledError 的（探针只记到 wait:enter 与 raised:CancelledError）。

    改成按真机制触发之后，这条就**不再需要一个真的 HTTP 断开**：直接取消那个在 anext 上
    等待的 task，CancelledError 会落在生成器的同一个 await 点上，与生产完全同形。仍然不
    在套件内的只剩「Starlette 真的会在 disconnect 时取消迭代器」这一条，那个由 Task 5 的
    手工真跑证明。
    """
    from chatbi.api import run_stream as module
    from chatbi.guard.deps import policy_resolver_for

    run = make_run()
    driver = _FakeDriver(block=True)  # 在线程里阻塞，直到 driver.cancel 放开它
    monkeypatch.setattr("chatbi.api.run_stream.get_driver", lambda kind: driver)

    cancelled: list[uuid.UUID] = []
    real_cancel_run = module.cancel_run

    def spy_cancel_run(db, run_id):
        cancelled.append(run_id)
        return real_cancel_run(db, run_id)

    monkeypatch.setattr("chatbi.api.run_stream.cancel_run", spy_cancel_run)

    stream = module.stream(run=run, db=db_session, resolver=policy_resolver_for(), sql="select 1")
    async for chunk in stream:  # 推到语句已下发
        if b"execute.started" in chunk:
            break

    pending = asyncio.create_task(stream.__anext__())  # 它会停在 asyncio.wait 上
    await asyncio.to_thread(driver.started.wait, 5)
    await asyncio.sleep(0.05)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert cancelled == [run.id], "断开时没有调 cancel_run——查询会继续跑在用户的库上"
    assert driver.cancelled == ["4242"], "cancel_run 没掐到库侧（只关流是 spec §4.3 点名的错误）"

    db_session.expire_all()
    refreshed = db_session.get(Run, run.id)
    assert refreshed.status == "cancelled"
    assert refreshed.error_code == "QUERY_CANCELLED"


def test_delete_returns_204_even_when_nothing_was_running(client: TestClient, make_run) -> None:
    """**恒 204**：取消一个已经结束的查询是幂等的正常情况（用户点得晚了一点），
    不是错误。
    """
    run = make_run()

    assert client.delete(f"/api/runs/{run.id}/execute").status_code == 204


def test_delete_on_another_users_run_is_404(
    client: TestClient, make_run, make_user, login_as
) -> None:
    """取消别人的查询和执行别人的 run 一样不该允许。**admin 也不例外**（设计 §6.2）。"""
    run = make_run()
    login_as(make_user(role="admin"))

    assert client.delete(f"/api/runs/{run.id}/execute").status_code == 404


def test_an_empty_sql_is_a_422(client: TestClient, make_run) -> None:
    """Pydantic 的 min_length=1 挡在 guard 之前。"""
    run = make_run()

    assert client.post(f"/api/runs/{run.id}/execute", json={"sql": ""}).status_code == 422
