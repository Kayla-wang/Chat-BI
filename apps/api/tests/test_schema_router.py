"""GET /api/datasources/{id}/schema 与 PATCH .../schema/columns/{col_id}。

用假驱动覆盖 driver_for，因此不依赖任何外部数据库。这里测的是编排：鉴权、缓存行为、
错误映射、响应脱敏，以及 F-201 AC1「refresh 后人工注释不丢」。
"""

import uuid

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from chatbi.datasources.drivers.base import (
    ColumnSchema,
    ConnectionFailed,
    SchemaSnapshot,
    TableSchema,
)
from chatbi.db.models import ColumnNote

CITY_COL = "demo_sales.customers.city"


def _snapshot(*, city_comment: str | None = None) -> SchemaSnapshot:
    return SchemaSnapshot(
        tables=(
            TableSchema(
                name="customers",
                schema_name="demo_sales",
                comment="客户",
                columns=(
                    ColumnSchema(
                        name="id", data_type="integer", is_numeric=True, comment="客户 ID"
                    ),
                    ColumnSchema(name="city", data_type="text", comment=city_comment),
                ),
            ),
        )
    )


class _FakeDriver:
    """只实现 reflect——这两个端点只调它。别的方法缺失会以 AttributeError 暴露，
    那正好说明端点调了它不该调的东西（与 P2b 的 /test 假驱动同形）。
    """

    kind = "fake"
    default_port = 1234

    def __init__(self, *, snapshot: SchemaSnapshot | None = None, fail: bool = False) -> None:
        self._snapshot = snapshot if snapshot is not None else _snapshot()
        self._fail = fail
        self.reflect_calls = 0

    def reflect(self, info) -> SchemaSnapshot:
        self.reflect_calls += 1
        if self._fail:
            raise ConnectionFailed()
        return self._snapshot


@pytest.fixture
def with_driver(admin_client: TestClient):
    """把假驱动装进依赖。返回 (driver) -> client。"""
    from chatbi.datasources.deps import driver_for
    from chatbi.main import app

    def _install(driver: _FakeDriver) -> TestClient:
        app.dependency_overrides[driver_for] = lambda: driver
        return admin_client

    yield _install
    app.dependency_overrides.pop(driver_for, None)


# ---- GET /schema ----


def test_the_first_get_fetches_and_caches(with_driver, make_datasource) -> None:
    """缓存为空时自动拉一次——否则前端要先发一个必然失败的 GET，把实现细节暴露
    成协议。
    """
    datasource = make_datasource()
    driver = _FakeDriver()
    client = with_driver(driver)

    response = client.get(f"/api/datasources/{datasource.id}/schema")

    assert response.status_code == 200
    body = response.json()
    assert driver.reflect_calls == 1
    assert body["tables"][0]["name"] == "customers"
    assert body["tables"][0]["comment"] == "客户"
    assert body["fetched_at"]


def test_a_second_get_does_not_touch_the_external_database(with_driver, make_datasource) -> None:
    """缓存的全部意义。这条是唯一守它的测试——去掉缓存分支后其余 GET 测试全绿。"""
    datasource = make_datasource()
    driver = _FakeDriver()
    client = with_driver(driver)

    client.get(f"/api/datasources/{datasource.id}/schema")
    client.get(f"/api/datasources/{datasource.id}/schema")

    assert driver.reflect_calls == 1


def test_refresh_forces_a_refetch(with_driver, make_datasource) -> None:
    datasource = make_datasource()
    driver = _FakeDriver()
    client = with_driver(driver)

    client.get(f"/api/datasources/{datasource.id}/schema")
    response = client.get(f"/api/datasources/{datasource.id}/schema?refresh=1")

    assert response.status_code == 200
    assert driver.reflect_calls == 2


def test_a_failed_fetch_maps_to_connection_error_without_leaking_the_address(
    with_driver, make_datasource
) -> None:
    """spec §4.4：地址端口进服务端日志，不进 HTTP 响应。"""
    datasource = make_datasource(host="secret-db.internal", port=15432)
    client = with_driver(_FakeDriver(fail=True))

    response = client.get(f"/api/datasources/{datasource.id}/schema")

    assert response.status_code == 503
    assert response.json()["code"] == "CONNECTION_ERROR"
    body = response.text
    assert "secret-db.internal" not in body
    assert "15432" not in body


def test_the_schema_response_carries_no_credentials(with_driver, make_datasource) -> None:
    """响应模型不声明凭据字段（spec §4.4）。这条也钉住 200——否则一个恒返回 401 的
    实现会「通过」所有否定断言。
    """
    datasource = make_datasource(password="ds-pw-123456")
    client = with_driver(_FakeDriver())

    response = client.get(f"/api/datasources/{datasource.id}/schema")

    assert response.status_code == 200
    body = response.text
    for leaked in ("ds-pw-123456", "secret_ciphertext", "secret_nonce", "password"):
        assert leaked not in body


def test_an_anonymous_get_is_rejected(client: TestClient, make_datasource) -> None:
    datasource = make_datasource()

    response = client.get(f"/api/datasources/{datasource.id}/schema")

    assert response.status_code == 401


def test_a_missing_datasource_is_404(with_driver) -> None:
    client = with_driver(_FakeDriver())

    response = client.get(f"/api/datasources/{uuid.uuid4()}/schema")

    assert response.status_code == 404
    assert response.json()["code"] == "DATASOURCE_NOT_FOUND"


def test_an_analyst_without_a_grant_is_403(
    client: TestClient, make_datasource, make_user, login_as
) -> None:
    """未授权数据源不该泄露它的表结构——那是最直接的结构信息泄露。"""
    datasource = make_datasource()
    login_as(make_user(role="analyst"))

    response = client.get(f"/api/datasources/{datasource.id}/schema")

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


# ---- PATCH /schema/columns/{col_id} ----


def test_patching_a_note_returns_the_updated_column(with_driver, make_datasource) -> None:
    """返回那一列的新形态而不是整个 schema——一张 200 列的表整份回传只为确认一条
    注释写成功太重。
    """
    datasource = make_datasource()
    client = with_driver(_FakeDriver())
    client.get(f"/api/datasources/{datasource.id}/schema")  # 建缓存

    response = client.patch(
        f"/api/datasources/{datasource.id}/schema/columns/{CITY_COL}",
        json={"note": "所在城市（省会优先）"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["col_id"] == CITY_COL
    assert body["note"] == "所在城市（省会优先）"
    assert body["data_type"] == "text"


def test_a_patched_note_shows_up_in_the_next_get(with_driver, make_datasource) -> None:
    """并且不覆盖库原生注释——两个字段并存（设计 §4）。"""
    datasource = make_datasource()
    client = with_driver(_FakeDriver(snapshot=_snapshot(city_comment="城市（库注释）")))
    client.get(f"/api/datasources/{datasource.id}/schema")

    client.patch(
        f"/api/datasources/{datasource.id}/schema/columns/{CITY_COL}",
        json={"note": "人工补的"},
    )
    body = client.get(f"/api/datasources/{datasource.id}/schema").json()

    city = next(c for c in body["tables"][0]["columns"] if c["name"] == "city")
    assert city["note"] == "人工补的"
    assert city["comment"] == "城市（库注释）"  # 库原生注释没被覆盖


def test_a_manual_note_survives_a_refresh(with_driver, make_datasource) -> None:
    """**F-201 AC1 / spec §8.1 验收项 11 —— 本段的退出标准。**

    这是 column_notes 与 schema_cache 分成两张表的全部理由：refresh 整行覆盖
    payload，注释若存在其中就会跟着丢。
    """
    datasource = make_datasource()
    client = with_driver(_FakeDriver())
    client.get(f"/api/datasources/{datasource.id}/schema")
    client.patch(
        f"/api/datasources/{datasource.id}/schema/columns/{CITY_COL}",
        json={"note": "刷新也不该丢"},
    )

    body = client.get(f"/api/datasources/{datasource.id}/schema?refresh=1").json()

    city = next(c for c in body["tables"][0]["columns"] if c["name"] == "city")
    assert city["note"] == "刷新也不该丢"


def test_patching_an_unknown_column_is_404(with_driver, make_datasource) -> None:
    datasource = make_datasource()
    client = with_driver(_FakeDriver())
    client.get(f"/api/datasources/{datasource.id}/schema")

    response = client.patch(
        f"/api/datasources/{datasource.id}/schema/columns/demo_sales.customers.nope",
        json={"note": "无处安放"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "COLUMN_NOT_FOUND"


def test_patching_before_anything_was_fetched_is_404(with_driver, make_datasource) -> None:
    """PATCH 不顺带拉取——那会让一次注释编辑因为数据源临时不可达而失败。

    正常流程里前端必然先 GET /schema 才拿得到 col_id，所以这条 404 不会被真实用户
    撞到；它钉住的是「PATCH 不连外部库」这个设计承诺。
    """
    datasource = make_datasource()
    driver = _FakeDriver()
    client = with_driver(driver)

    response = client.patch(
        f"/api/datasources/{datasource.id}/schema/columns/{CITY_COL}",
        json={"note": "还没拉过"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "COLUMN_NOT_FOUND"
    assert driver.reflect_calls == 0  # 一次都没连


def test_an_analyst_with_a_grant_can_patch_a_note(
    client: TestClient, db_session, make_datasource, make_user, login_as
) -> None:
    """F-201 是分析师的工作流——知道 segment 在业务上意味着什么的人是他。要 admin
    代录这个功能基本不会被用（设计 §5.2）。
    """
    from chatbi.datasources.metadata import write_cache
    from chatbi.datasources.repository import set_grant

    datasource = make_datasource()
    analyst = make_user(role="analyst")
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)
    write_cache(db_session, datasource.id, _snapshot())  # 直接建缓存，不走 admin
    login_as(analyst)

    response = client.patch(
        f"/api/datasources/{datasource.id}/schema/columns/{CITY_COL}",
        json={"note": "分析师补的"},
    )

    assert response.status_code == 200
    assert response.json()["note"] == "分析师补的"


def test_an_empty_note_clears_it_but_keeps_the_audit_row(
    with_driver, db_session, make_datasource
) -> None:
    """空字符串是「清空」，保留行——删行会让「谁把注释清掉了」的痕迹消失
    （spec §4.6）。
    """
    datasource = make_datasource()
    client = with_driver(_FakeDriver())
    client.get(f"/api/datasources/{datasource.id}/schema")
    client.patch(
        f"/api/datasources/{datasource.id}/schema/columns/{CITY_COL}", json={"note": "先写一条"}
    )

    response = client.patch(
        f"/api/datasources/{datasource.id}/schema/columns/{CITY_COL}", json={"note": ""}
    )

    assert response.status_code == 200
    assert response.json()["note"] == ""
    assert db_session.scalar(sa.select(sa.func.count()).select_from(ColumnNote)) == 1
