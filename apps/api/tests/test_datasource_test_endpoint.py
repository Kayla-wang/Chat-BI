"""POST /api/datasources/{id}/test。

用假驱动覆盖 driver_for，因此不依赖任何外部数据库。这里测的是编排：
鉴权、探测结果落库、错误映射、响应脱敏、OpenAPI 声明。
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from chatbi.datasources.drivers.base import ConnectionFailed, ProbeResult


class _FakeDriver:
    """只实现 probe——/test 端点只调它。别的方法缺失会以 AttributeError 暴露，
    那正好说明端点调了它不该调的东西。
    """

    kind = "fake"
    default_port = 1234

    def __init__(self, *, can_write: bool = False, fail: bool = False) -> None:
        self._can_write = can_write
        self._fail = fail
        self.calls: list[str] = []

    def probe(self, info):
        self.calls.append(info.host)
        if self._fail:
            raise ConnectionFailed()
        return ProbeResult(reachable=True, server_version="FakeDB 1.2.3", can_write=self._can_write)


@pytest.fixture
def with_driver(admin_client: TestClient):
    """把假驱动装进依赖。返回一个 (driver) -> client 的函数。"""
    from chatbi.datasources.deps import driver_for
    from chatbi.main import app

    def _install(driver: _FakeDriver) -> TestClient:
        app.dependency_overrides[driver_for] = lambda: driver
        return admin_client

    yield _install
    app.dependency_overrides.pop(driver_for, None)


def test_admin_gets_a_probe_result(with_driver, make_datasource) -> None:
    datasource = make_datasource()
    client = with_driver(_FakeDriver())

    response = client.post(f"/api/datasources/{datasource.id}/test")

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is True
    assert body["server_version"] == "FakeDB 1.2.3"
    assert body["can_write"] is False
    assert body["is_readonly_verified"] is True


def test_a_read_only_account_persists_the_verified_flag(with_driver, make_datasource) -> None:
    """落库，不只是响应里说一声——下次列表要显示这个状态。"""
    datasource = make_datasource(is_readonly_verified=False)
    client = with_driver(_FakeDriver(can_write=False))

    client.post(f"/api/datasources/{datasource.id}/test")

    assert client.get(f"/api/datasources/{datasource.id}").json()["is_readonly_verified"] is True


def test_a_writable_account_clears_the_flag_but_still_returns_200(
    with_driver, make_datasource
) -> None:
    """spec §4.3 闸 1：探到可写要告警并把标记置 false，**但不阻止保存**。

    有些环境拿不到只读账号，把它变成一个错误会让这些用户没法用产品；
    但不告警又等于假装安全。所以是 200 + can_write=true + 标记 false。
    """
    datasource = make_datasource(is_readonly_verified=True)
    client = with_driver(_FakeDriver(can_write=True))

    response = client.post(f"/api/datasources/{datasource.id}/test")

    assert response.status_code == 200
    assert response.json()["can_write"] is True
    assert response.json()["is_readonly_verified"] is False
    assert client.get(f"/api/datasources/{datasource.id}").json()["is_readonly_verified"] is False


def test_connection_failure_maps_to_connection_error(with_driver, make_datasource) -> None:
    datasource = make_datasource(host="db.internal", port=5432, username="ro_user")
    client = with_driver(_FakeDriver(fail=True))

    response = client.post(f"/api/datasources/{datasource.id}/test")

    assert response.status_code == 503
    assert response.json()["code"] == "CONNECTION_ERROR"
    # spec §4.4：不回显地址、端口、库名、用户名
    for leak in ("db.internal", "5432", "analytics", "ro_user"):
        assert leak not in response.text


def test_a_failed_probe_does_not_touch_the_verified_flag(with_driver, make_datasource) -> None:
    """连不上时不能把 is_readonly_verified 改成 false。

    「连不上」和「账号可写」是两件事；混在一起会让一次网络抖动把一个已验证
    只读的数据源降级，而用户不会再去点一次 /test。
    """
    datasource = make_datasource(is_readonly_verified=True)
    client = with_driver(_FakeDriver(fail=True))

    failed = client.post(f"/api/datasources/{datasource.id}/test")

    # 下限：没有这句，路由不存在时的 404 也让标记「保持为 True」，测试空洞通过
    assert failed.status_code == 503
    assert client.get(f"/api/datasources/{datasource.id}").json()["is_readonly_verified"] is True


def test_the_response_carries_no_credentials(with_driver, make_datasource) -> None:
    datasource = make_datasource(password="ds-pw-123456")
    client = with_driver(_FakeDriver())

    response = client.post(f"/api/datasources/{datasource.id}/test")

    assert response.status_code == 200  # 下限：404 的响应体也「不含密码」
    assert "ds-pw-123456" not in response.text
    for key in ("password", "secret_ciphertext", "secret_nonce"):
        assert key not in response.json()


def test_analyst_cannot_test_even_a_granted_datasource(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    """写操作专属 admin：/test 会改 is_readonly_verified。

    名字里的 granted 是功能性的——不授权的话 403 来自可见性判定，
    删掉 admin 闸门这条测试照样绿（P2a Task 5 踩过）。
    """
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    assert client.post(f"/api/datasources/{datasource.id}/test").status_code == 403


def test_unknown_datasource_returns_404(admin_client: TestClient) -> None:
    response = admin_client.post(f"/api/datasources/{uuid.uuid4()}/test")

    assert response.status_code == 404
    assert response.json()["code"] == "DATASOURCE_NOT_FOUND"


def test_the_test_route_declares_its_error_envelope() -> None:
    from chatbi.main import app

    responses = app.openapi()["paths"]["/api/datasources/{datasource_id}/test"]["post"]["responses"]

    assert {"200", "401", "403", "404", "503"} <= set(responses)
