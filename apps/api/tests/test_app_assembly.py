"""针对 main.py 装配本身的测试。

P1 §10.4 接缝 ②：`role_client` 那类夹具会自己重建 app 并重新注册异常处理器，
因此真 app 上注册失效时它们照样绿。本文件只用真 app（`client` 夹具只覆盖 get_db）。
"""

from fastapi.testclient import TestClient

from chatbi.api.routers import ALL_ROUTERS


def test_all_routers_are_mounted_on_the_real_app() -> None:
    """用 OpenAPI 的 paths 而不是 app.routes 的 path 集合。

    FastAPI 0.141 起 include_router 在 app.routes 里留下的是**一个**
    `_IncludedRouter` 包装对象，不再把子路由摊平进去，因此按 route.path 收集
    会得到一个不含任何业务路径的集合（本条测试第一次跑就是这样红的）。
    OpenAPI 的 paths 跨版本稳定，而且它表达的正是「对外暴露了哪些路径」。
    """
    from chatbi.main import app

    exposed = set(app.openapi()["paths"])
    for router in ALL_ROUTERS:
        for route in router.routes:
            assert getattr(route, "path", None) in exposed


def test_real_app_returns_the_error_envelope_on_401(client: TestClient) -> None:
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"code": "NOT_AUTHENTICATED", "message": "请先登录"}
