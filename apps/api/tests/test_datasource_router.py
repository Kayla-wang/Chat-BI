"""/api/datasources 的端点测试。

全部走真 app（`client` 夹具只覆盖 get_db），所以 router 注册、异常处理器、
OpenAPI 声明都在被测范围内。P1 §10.4 接缝 ② 的教训：自建 app 的夹具会把
「真 app 上注册失效」这类问题整类掩盖掉。
"""

import uuid

from fastapi.testclient import TestClient

PAYLOAD = {
    "name": "生产只读库",
    "kind": "postgres",
    "host": "db.internal",
    "port": 5432,
    "database": "analytics",
    "username": "ro_user",
    "password": "ds-pw-123456",
}


def test_unauthenticated_listing_is_rejected(client: TestClient) -> None:
    response = client.get("/api/datasources")

    assert response.status_code == 401
    assert response.json() == {"code": "NOT_AUTHENTICATED", "message": "请先登录"}


def test_admin_creates_a_datasource(admin_client: TestClient) -> None:
    response = admin_client.post("/api/datasources", json=PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "生产只读库"
    assert body["has_password"] is True
    # 只读验证由 P2b 的 /test 端点写，建的时候必须是 false，不能默认「已验证」
    assert body["is_readonly_verified"] is False


def test_the_create_response_never_echoes_the_password(admin_client: TestClient) -> None:
    """扫响应原文，不只扫 JSON 的键。

    某天有人加一个把请求体回显进去的 detail 字段，只查键名的断言会放过它。

    先断言 201：没有这一句，路由不存在时的 404 {"detail":"Not Found"} 也「不含
    密码」，这条测试会空洞通过（实施时第一次跑就是这样绿的）。
    """
    response = admin_client.post("/api/datasources", json=PAYLOAD)

    assert response.status_code == 201
    assert "ds-pw-123456" not in response.text
    for key in ("password", "secret_ciphertext", "secret_nonce"):
        assert key not in response.json()


def test_creating_with_a_duplicate_name_returns_409(admin_client: TestClient) -> None:
    admin_client.post("/api/datasources", json=PAYLOAD)

    response = admin_client.post("/api/datasources", json=PAYLOAD)

    assert response.status_code == 409
    assert response.json()["code"] == "DATASOURCE_NAME_EXISTS"


def test_creating_with_an_unsupported_kind_is_a_validation_error(
    admin_client: TestClient,
) -> None:
    """kind 由 Literal 守住，422 来自 Pydantic——router 里不需要自己写校验。"""
    response = admin_client.post("/api/datasources", json=PAYLOAD | {"kind": "oracle"})

    assert response.status_code == 422


def test_analyst_cannot_create(client: TestClient, make_user, login_as) -> None:
    login_as(make_user(role="analyst"))

    response = client.post("/api/datasources", json=PAYLOAD)

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_viewer_cannot_create(client: TestClient, make_user, login_as) -> None:
    login_as(make_user(role="viewer"))

    assert client.post("/api/datasources", json=PAYLOAD).status_code == 403


def test_analyst_only_lists_granted_datasources(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    granted = make_datasource(name="已授权")
    make_datasource(name="未授权")
    set_grant(db_session, datasource_id=granted.id, user_id=analyst.id, can_query=True)

    response = client.get("/api/datasources")

    assert response.status_code == 200
    assert [d["name"] for d in response.json()] == ["已授权"]


def test_getting_an_unknown_id_returns_404(admin_client: TestClient) -> None:
    response = admin_client.get(f"/api/datasources/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "DATASOURCE_NOT_FOUND"


def test_getting_an_ungranted_datasource_returns_403(
    client: TestClient, make_user, make_datasource, login_as
) -> None:
    login_as(make_user(role="analyst"))
    datasource = make_datasource()

    response = client.get(f"/api/datasources/{datasource.id}")

    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"
    # 无权限的响应不回显地址、端口、库名、用户名（spec §4.4）
    for leak in ("db.internal", "5432", "analytics", "ro_user"):
        assert leak not in response.text


def test_analyst_can_get_a_granted_datasource(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    response = client.get(f"/api/datasources/{datasource.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(datasource.id)


def test_admin_patches_a_datasource(admin_client: TestClient, make_datasource) -> None:
    datasource = make_datasource(host="old.internal")

    response = admin_client.patch(
        f"/api/datasources/{datasource.id}", json={"host": "new.internal"}
    )

    assert response.status_code == 200
    assert response.json()["host"] == "new.internal"


def test_patching_the_password_does_not_echo_it(
    admin_client: TestClient, make_datasource
) -> None:
    datasource = make_datasource()

    response = admin_client.patch(
        f"/api/datasources/{datasource.id}", json={"password": "rotated-pw-9999"}
    )

    assert response.status_code == 200
    assert "rotated-pw-9999" not in response.text
    assert response.json()["has_password"] is True


def test_analyst_cannot_patch_even_a_granted_datasource(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    """写操作是 admin 专属：can_query 授权给的是读，不是写（spec §4.2）。"""
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    response = client.patch(f"/api/datasources/{datasource.id}", json={"host": "x.internal"})

    assert response.status_code == 403


def test_admin_deletes_a_datasource(admin_client: TestClient, make_datasource) -> None:
    datasource = make_datasource()

    assert admin_client.delete(f"/api/datasources/{datasource.id}").status_code == 204
    assert admin_client.get(f"/api/datasources/{datasource.id}").status_code == 404


def test_analyst_cannot_delete_even_a_granted_datasource(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    """必须先授权，否则测的是可见性而不是写权限。

    不 set_grant 的版本照样返回 403——但那个 403 来自 require_datasource 的
    可见性判定，删掉 delete 上的 admin 闸门它依然绿（实施时反向验证抓到的）。
    授权之后，403 就只能来自 admin 闸门。
    """
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    assert client.delete(f"/api/datasources/{datasource.id}").status_code == 403


def test_every_route_declares_its_error_envelope() -> None:
    """Pydantic 模型是 OpenAPI 唯一真相源（Global Constraints）。

    漏一个 responses 声明，P4 生成的前端类型就不知道这个端点会返回
    {code, message}，那条分支要到运行时才崩。422 由 FastAPI 自动补，
    所以用子集比较而不是相等。
    """
    from chatbi.main import app

    expected = {
        ("/api/datasources", "get"): {"200", "401"},
        ("/api/datasources", "post"): {"201", "401", "403", "409"},
        ("/api/datasources/{datasource_id}", "get"): {"200", "401", "403", "404"},
        ("/api/datasources/{datasource_id}", "patch"): {"200", "401", "403", "404", "409"},
        ("/api/datasources/{datasource_id}", "delete"): {"204", "401", "403", "404"},
    }

    paths = app.openapi()["paths"]
    for (path, method), codes in expected.items():
        declared = set(paths[path][method]["responses"])
        assert codes <= declared, (path, method, sorted(codes - declared))
