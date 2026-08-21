"""POST /api/datasources/{id}/sql/validate。

只测**编排**：鉴权、判定失败仍 200、响应字段完整、方言按 kind 选。闸 2/闸 3 的清单在
tests/test_guard_gate2.py 与 test_guard_gate3.py 已经测过，在 HTTP 层再跑一遍只是让同
一件事慢十倍（设计 §8.5）。
"""

import uuid

from fastapi.testclient import TestClient


def _post(client: TestClient, datasource_id, sql: str):
    return client.post(f"/api/datasources/{datasource_id}/sql/validate", json={"sql": sql})


def test_a_valid_query_comes_back_ok_with_the_effective_sql(admin_client, make_datasource) -> None:
    datasource = make_datasource()

    response = _post(admin_client, datasource.id, "select * from demo_sales.orders")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["code"] is None
    assert "LIMIT 1000" in body["effective_sql"]
    assert body["limit_applied"] is True
    assert body["warnings"] == []


def test_a_write_statement_is_rejected_with_200(admin_client, make_datasource) -> None:
    """**判定失败也是 200**，ok=false 在体内（设计 §4.1）。编辑器每 300ms 调一次，用
    4xx 会让前端把正常输入过程当成错误流。
    """
    datasource = make_datasource()

    response = _post(admin_client, datasource.id, "insert into t values (1)")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["code"] == "WRITE_BLOCKED"
    assert body["reason"]  # 非空——用户要知道为什么
    assert body["effective_sql"] is None


def test_the_dialect_follows_the_datasource_kind(admin_client, make_datasource) -> None:
    """同一条 SQL 在两个 kind 下判定不同，这条钉住「方言不是猜的」——也正是这个端点必须
    挂在数据源下的理由（设计 §4）。

    用 ClickHouse 的 SETTINGS 子句：实测只有 clickhouse 方言接受它，postgres 与 mysql
    都是 ParseError。**别用 `limit 3 by x` 做这个区分**——实测 sqlglot 在三个方言下都能
    解析它（见 test_a_limit_by_query_carries_a_warning 的注释）。
    """
    ch = make_datasource(kind="clickhouse", port=8123)
    pg = make_datasource(kind="postgres")
    sql = "select * from t settings max_threads = 1"

    assert _post(admin_client, ch.id, sql).json()["ok"] is True
    pg_body = _post(admin_client, pg.id, sql).json()
    assert pg_body["ok"] is False
    assert pg_body["code"] == "SQL_PARSE_ERROR"


def test_every_datasource_kind_has_a_dialect_mapping(admin_client, make_datasource) -> None:
    """_DIALECTS 的键必须覆盖 DATASOURCE_KINDS 全部三个——漏一个会让那种数据源的
    /sql/validate 抛 KeyError 500。上一条只覆盖了 postgres 与 clickhouse。
    """
    from chatbi.db.models import DATASOURCE_KINDS

    for kind in DATASOURCE_KINDS:
        datasource = make_datasource(kind=kind)
        response = _post(admin_client, datasource.id, "select 1")

        assert response.status_code == 200, f"kind={kind} 没有方言映射"
        assert response.json()["ok"] is True


def test_a_limit_by_query_carries_a_warning(admin_client, make_datasource) -> None:
    """`LIMIT n BY x` 走「原样保留 + warning」那条分支（设计 §2.2）。

    **实测澄清一处**：`limit 3 by x` 在 postgres / mysql / clickhouse 三个方言下 sqlglot
    都能解析（都产生带 expressions 的 exp.Limit），所以这条分支不是 ClickHouse 独占的。
    对 Postgres 数据源，这条语句会被 guard 放过然后由库侧报语法错——那是可接受的反馈
    路径（P3b 会返回 QUERY_FAILED 并带库的原文，用户据此改 SQL），guard 不做语法教师。
    """
    ch = make_datasource(kind="clickhouse", port=8123)

    body = _post(admin_client, ch.id, "select * from t limit 3 by x").json()

    assert body["ok"] is True
    assert body["limit_applied"] is False
    assert body["warnings"]  # 非空


def test_an_anonymous_request_is_rejected(client: TestClient, make_datasource) -> None:
    """401 是真的 HTTP 错误，与「判定失败」不同。"""
    assert _post(client, make_datasource().id, "select 1").status_code == 401


def test_a_missing_datasource_is_404(admin_client) -> None:
    response = _post(admin_client, uuid.uuid4(), "select 1")

    assert response.status_code == 404
    assert response.json()["code"] == "DATASOURCE_NOT_FOUND"


def test_an_analyst_without_a_grant_is_403(
    client: TestClient, make_datasource, make_user, login_as
) -> None:
    datasource = make_datasource()
    login_as(make_user(role="analyst"))

    response = _post(client, datasource.id, "select 1")

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_an_analyst_with_a_grant_can_validate(
    client: TestClient, db_session, make_datasource, make_user, login_as
) -> None:
    """analyst 是这个端点的主要用户——他在编辑器里改 SQL（F-302）。"""
    from chatbi.datasources.repository import set_grant

    datasource = make_datasource()
    analyst = make_user(role="analyst")
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)
    login_as(analyst)

    assert _post(client, datasource.id, "select 1").json()["ok"] is True


def test_an_empty_sql_is_a_422(admin_client, make_datasource) -> None:
    """Pydantic 的 min_length=1 挡在 guard 之前。422 而不是 200+ok=false：空请求体是
    **协议错误**，不是一次得出「不通过」的校验。
    """
    response = admin_client.post(
        f"/api/datasources/{make_datasource().id}/sql/validate", json={"sql": ""}
    )

    assert response.status_code == 422


def test_the_response_carries_no_credentials(admin_client, make_datasource) -> None:
    """只做否定断言的测试**必须钉住状态码下限**，否则它会空洞通过：路由还不存在时
    FastAPI 返回 {"detail": "Not Found"}，里面当然也没有凭据。

    P2c 的自查记录记过同一个坑，这次写的时候还是漏了——所以它值得留在注释里。
    """
    datasource = make_datasource(password="ds-pw-123456")

    response = _post(admin_client, datasource.id, "select 1")

    assert response.status_code == 200
    for leaked in ("ds-pw-123456", "secret_ciphertext", "secret_nonce"):
        assert leaked not in response.text
