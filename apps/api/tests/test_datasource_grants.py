"""授权端点与可见性的联动。

这些测试的重点不是「PUT 返回 200」，而是「授权之后 GET /api/datasources 的结果
真的变了」——授权表写对了但可见性查询没用上它，是这一层最容易出的错。
"""

import uuid

from fastapi.testclient import TestClient


def _names(client: TestClient) -> list[str]:
    return [d["name"] for d in client.get("/api/datasources").json()]


def _become(client: TestClient, db_session, user) -> None:
    """把 client 切换成另一个用户的身份。

    admin_client 与 client 是同一个 TestClient 实例（同一条夹具链），所以要观察
    analyst 的视角必须显式换掉 cookie。
    """
    from chatbi.auth.deps import SESSION_COOKIE
    from chatbi.auth.sessions import create_session

    client.cookies.set(SESSION_COOKIE, str(create_session(db_session, user).id))


def test_admin_grants_and_the_analyst_immediately_sees_it(
    admin_client: TestClient, db_session, make_user, make_datasource
) -> None:
    datasource = make_datasource(name="生产库")
    analyst = make_user(role="analyst")

    response = admin_client.put(
        f"/api/datasources/{datasource.id}/grants",
        json={"user_id": str(analyst.id), "can_query": True},
    )

    assert response.status_code == 200
    assert response.json() == {
        "datasource_id": str(datasource.id),
        "user_id": str(analyst.id),
        "can_query": True,
    }

    _become(admin_client, db_session, analyst)
    assert _names(admin_client) == ["生产库"]


def test_granting_twice_keeps_a_single_row(
    admin_client: TestClient, make_user, make_datasource
) -> None:
    datasource = make_datasource()
    analyst = make_user(role="analyst")
    body = {"user_id": str(analyst.id), "can_query": True}

    first = admin_client.put(f"/api/datasources/{datasource.id}/grants", json=body)
    second = admin_client.put(f"/api/datasources/{datasource.id}/grants", json=body)

    # 先断言两次 PUT 都成功：没有这两句，路由不存在时的 404 响应体
    # {"detail": "Not Found"} 的 len() 恰好也是 1，这条测试会空洞通过
    assert first.status_code == second.status_code == 200
    listed = admin_client.get(f"/api/datasources/{datasource.id}/grants")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_setting_can_query_false_hides_the_datasource(
    admin_client: TestClient, db_session, make_user, make_datasource
) -> None:
    datasource = make_datasource()
    analyst = make_user(role="analyst")
    granted = admin_client.put(
        f"/api/datasources/{datasource.id}/grants",
        json={"user_id": str(analyst.id), "can_query": True},
    )
    revoked = admin_client.put(
        f"/api/datasources/{datasource.id}/grants",
        json={"user_id": str(analyst.id), "can_query": False},
    )

    # 两句状态码断言是下限：否则路由不存在时 _names() 也是 []，测试空洞通过
    assert granted.status_code == revoked.status_code == 200
    assert revoked.json()["can_query"] is False
    _become(admin_client, db_session, analyst)
    assert _names(admin_client) == []


def test_revoking_a_grant_hides_the_datasource_again(
    admin_client: TestClient, db_session, make_user, make_datasource
) -> None:
    datasource = make_datasource()
    analyst = make_user(role="analyst")
    admin_client.put(
        f"/api/datasources/{datasource.id}/grants",
        json={"user_id": str(analyst.id), "can_query": True},
    )
    # 先确认它真的可见过——验证的是状态迁移，不是「终态恰好为空」
    _become(admin_client, db_session, analyst)
    assert _names(admin_client) == [datasource.name]

    _become(admin_client, db_session, make_user(role="admin"))
    revoked = admin_client.delete(f"/api/datasources/{datasource.id}/grants/{analyst.id}")

    assert revoked.status_code == 204
    _become(admin_client, db_session, analyst)
    assert _names(admin_client) == []


def test_revoking_twice_is_idempotent(
    admin_client: TestClient, make_user, make_datasource
) -> None:
    """本段不新增错误码，而「授权本来就不存在」没有语义正确的现成码。"""
    datasource = make_datasource()
    analyst = make_user(role="analyst")
    path = f"/api/datasources/{datasource.id}/grants/{analyst.id}"

    assert admin_client.delete(path).status_code == 204
    assert admin_client.delete(path).status_code == 204


def test_admin_lists_grants(admin_client: TestClient, make_user, make_datasource) -> None:
    datasource = make_datasource()
    first = make_user(role="analyst")
    second = make_user(role="viewer")
    for user in (first, second):
        admin_client.put(
            f"/api/datasources/{datasource.id}/grants",
            json={"user_id": str(user.id), "can_query": True},
        )

    listed = admin_client.get(f"/api/datasources/{datasource.id}/grants").json()

    assert {row["user_id"] for row in listed} == {str(first.id), str(second.id)}


def test_analyst_cannot_grant(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    """连自己已被授权的数据源也不能改授权——否则一次授权等于放开整棵权限树。"""
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    response = client.put(
        f"/api/datasources/{datasource.id}/grants",
        json={"user_id": str(analyst.id), "can_query": True},
    )

    assert response.status_code == 403


def test_listing_grants_requires_admin(
    client: TestClient, db_session, make_user, make_datasource, login_as
) -> None:
    from chatbi.datasources.repository import set_grant

    analyst = login_as(make_user(role="analyst"))
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    assert client.get(f"/api/datasources/{datasource.id}/grants").status_code == 403


def test_granting_on_an_unknown_datasource_returns_404(
    admin_client: TestClient, make_user
) -> None:
    analyst = make_user(role="analyst")

    response = admin_client.put(
        f"/api/datasources/{uuid.uuid4()}/grants",
        json={"user_id": str(analyst.id), "can_query": True},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "DATASOURCE_NOT_FOUND"


def test_granting_to_an_unknown_user_returns_404(
    admin_client: TestClient, make_datasource
) -> None:
    """P1 遗留 5：USER_NOT_FOUND 终于有调用方。

    没有这道检查，授权表会攒下指向不存在用户的行——外键会挡住，但错误表面会是
    500 而不是 404。
    """
    datasource = make_datasource()

    response = admin_client.put(
        f"/api/datasources/{datasource.id}/grants",
        json={"user_id": str(uuid.uuid4()), "can_query": True},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


def test_every_grant_route_declares_its_error_envelope() -> None:
    from chatbi.main import app

    expected = {
        ("/api/datasources/{datasource_id}/grants", "get"): {"200", "401", "403", "404"},
        ("/api/datasources/{datasource_id}/grants", "put"): {"200", "401", "403", "404"},
        ("/api/datasources/{datasource_id}/grants/{user_id}", "delete"): {
            "204",
            "401",
            "403",
            "404",
        },
    }

    paths = app.openapi()["paths"]
    for (path, method), codes in expected.items():
        declared = set(paths[path][method]["responses"])
        assert codes <= declared, (path, method, sorted(codes - declared))
