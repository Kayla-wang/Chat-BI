"""执行流对真 Postgres 的验收（P3b 设计 §11.2）。

p3b1 已经验过「执行器层的 cancel_run 能掐掉库侧查询」。这里验的是**通过 DELETE 端点
触发时同样成立**——那条路径多了 to_thread、多了 require_run、多了一个并发的 HTTP 请求。

只断言「流以 QUERY_CANCELLED 结束」证明不了取消：task.cancel() 单独就能让流结束而查询
继续跑（设计 §1.1 的实测）。所以去 pg_stat_activity 里看。
"""

import os
import threading
import time
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from chatbi.db.models import Conversation, Run
from chatbi.execution import registry


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.clear()
    yield
    registry.clear()


def _pg_dsn() -> str:
    return os.environ["TEST_DATABASE_URL"].replace("postgresql+psycopg", "postgresql")


def _active_sleep_count(pid: int) -> int:
    """在**另一条连接**上问：那个 backend 还在跑 pg_sleep 吗？

    这是「真取消」唯一的直接证据。必须另开连接——被取消的那条正被查询占住。

    **必须 ilike 而不是 like**：这里跑的是 guard 重写过的 effective_sql，sqlglot 把函数名
    写成了大写（`SELECT PG_SLEEP(30) LIMIT 1000`），而 `like '%pg_sleep%'` 大小写敏感、
    一条都匹配不到。那样最后那句「取消后必须是 0」会**假绿**（本来就是 0）——实施时正是
    「取消前必须先看到 1」那句断言把它抓出来的。p3b1 的同名函数用 like 没出问题，因为
    那条测试直接调执行器、SQL 原样下发，没经过 guard。
    """
    with psycopg.connect(_pg_dsn()) as conn:
        row = conn.execute(
            "select count(*) from pg_stat_activity "
            "where pid = %s and state = 'active' and query ilike %s",
            (pid, "%pg_sleep%"),
        ).fetchone()
    return row[0]


@pytest.fixture
def real_run(db_session, make_user, login_as, client: TestClient):
    """一个指向**真库**的数据源 + 一条 drafted run，所有者已登录。

    数据源指向 TEST_DATABASE_URL 那个库（demo_sales 在里面）。用 make_datasource 不行
    ——它的默认 host 是 db.internal，连不上。
    """
    from urllib.parse import unquote, urlparse

    from chatbi.datasources.crypto import aad_for_datasource, seal
    from chatbi.db.models import Datasource

    parsed = urlparse(_pg_dsn())
    owner = make_user(role="admin")
    datasource_id = uuid.uuid4()
    sealed = seal(unquote(parsed.password or ""), aad=aad_for_datasource(datasource_id))
    datasource = Datasource(
        id=datasource_id,
        name=f"真库-{datasource_id.hex[:8]}",
        kind="postgres",
        host=parsed.hostname,
        port=parsed.port,
        database=parsed.path.lstrip("/"),
        username=unquote(parsed.username or ""),
        secret_ciphertext=sealed.ciphertext,
        secret_nonce=sealed.nonce,
        created_by=owner.id,
    )
    db_session.add(datasource)
    db_session.flush()
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
        question="q",
        status="drafted",
    )
    db_session.add(run)
    db_session.flush()
    login_as(owner)
    return run


def test_a_real_query_runs_through_the_endpoint(client: TestClient, real_run) -> None:
    """先证明这条路通，否则下面那条的红分不清「取消生效」与「根本连不上」。"""
    with client.stream(
        "POST",
        f"/api/runs/{real_run.id}/execute",
        json={"sql": "select count(*) as n from demo_sales.orders"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_lines())

    assert '"status":"succeeded"' in body
    assert '"row_count":1' in body


def test_delete_really_kills_the_backend_query(client: TestClient, real_run) -> None:
    """**本份最重要的一条。**

    TestClient 是同步的，所以流的消费与 DELETE 必须在两个线程里：主线程消费流，
    另一个线程等到语句下发（注册表登记）之后发 DELETE。

    时序：起流 → 等注册表登记（那时语句已下发）→ 确认库里**有**这条 pg_sleep →
    DELETE → 确认库里**没有**了。
    """
    observed: dict = {}

    def canceller() -> None:
        for _ in range(200):  # 等注册表登记，最多 10 秒
            if registry.is_running(real_run.id):
                break
            time.sleep(0.05)
        else:
            observed["error"] = "on_start 没登记——取消能力没有入口"
            return
        # 直接读私有字典是有意的：要的是 backend pid，那是「真取消」唯一的直接证据来源
        observed["pid"] = int(registry._RUNNING[real_run.id].handle.token)
        time.sleep(0.5)  # 让语句真的开始跑
        observed["before"] = _active_sleep_count(observed["pid"])
        observed["delete_status"] = client.delete(f"/api/runs/{real_run.id}/execute").status_code

    worker = threading.Thread(target=canceller, daemon=True)
    worker.start()
    with client.stream(
        "POST", f"/api/runs/{real_run.id}/execute", json={"sql": "select pg_sleep(30)"}
    ) as response:
        body = "".join(response.iter_lines())
    worker.join(timeout=20)

    assert "error" not in observed, observed.get("error")
    assert observed["delete_status"] == 204
    assert observed["before"] == 1, (
        "取消前库里就没有这条 pg_sleep——这条测试证明不了任何事，先查环境"
    )
    assert "QUERY_CANCELLED" in body

    time.sleep(0.3)  # 给 backend 一点时间退出
    assert _active_sleep_count(observed["pid"]) == 0, (
        "**查询还在库上跑**——只关了流没掐库侧，这是 spec §4.3 点名的错误"
    )
