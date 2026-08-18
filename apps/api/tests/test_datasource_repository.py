"""仓储层测试。不起 TestClient——这一层不认识 HTTP。"""

import uuid
from typing import get_args

import pytest
from sqlalchemy.exc import IntegrityError

from chatbi.datasources.repository import (
    create_datasource,
    datasource_exists,
    delete_datasource,
    get_visible,
    list_grants,
    list_visible,
    read_password,
    revoke_grant,
    set_grant,
    update_datasource,
)
from chatbi.datasources.schemas import DatasourceCreate, DatasourceResponse, DatasourceUpdate
from chatbi.db.models import DATASOURCE_KINDS
from chatbi.errors import ApiError


def _payload(**overrides) -> DatasourceCreate:
    base = {
        "name": "生产只读库",
        "kind": "postgres",
        "host": "db.internal",
        "port": 5432,
        "database": "analytics",
        "username": "ro_user",
        "password": "ds-pw-123456",
    }
    return DatasourceCreate(**(base | overrides))


def test_create_stores_the_password_as_ciphertext(db_session, make_user) -> None:
    admin = make_user(role="admin")

    datasource = create_datasource(db_session, payload=_payload(), created_by=admin.id)

    assert datasource.secret_ciphertext is not None
    assert datasource.secret_nonce is not None
    assert b"ds-pw-123456" not in datasource.secret_ciphertext


def test_create_round_trips_the_password(db_session, make_user) -> None:
    admin = make_user(role="admin")

    datasource = create_datasource(db_session, payload=_payload(), created_by=admin.id)

    assert read_password(datasource) == "ds-pw-123456"


def test_create_without_a_password_leaves_both_secret_columns_null(db_session, make_user) -> None:
    admin = make_user(role="admin")

    datasource = create_datasource(
        db_session, payload=_payload(password=None), created_by=admin.id
    )

    assert datasource.secret_ciphertext is None
    assert datasource.secret_nonce is None
    assert read_password(datasource) is None
    assert datasource.has_password is False


def test_duplicate_name_raises_api_error_and_leaves_the_transaction_usable(
    db_session, make_user
) -> None:
    """这条钉的是 insert + 捕获 IntegrityError 的写法。

    check-then-insert 也能让第一个断言通过，但过不了最后一句：IntegrityError
    未被 savepoint 隔离时，同一事务后续任何语句都会抛 PendingRollbackError，
    而 HTTP 层正是要靠这个事务把 409 返回出去。
    """
    admin = make_user(role="admin")
    create_datasource(db_session, payload=_payload(name="重名库"), created_by=admin.id)

    with pytest.raises(ApiError) as exc_info:
        create_datasource(db_session, payload=_payload(name="重名库"), created_by=admin.id)

    assert exc_info.value.code == "DATASOURCE_NAME_EXISTS"
    assert exc_info.value.status_code == 409
    # 事务还能继续用
    assert len(list_visible(db_session, admin)) == 1


def test_a_non_name_integrity_error_is_not_disguised_as_a_name_conflict(db_session) -> None:
    """created_by 指向不存在的用户会撞外键。把它也翻成 409「名称已存在」是撒谎——
    应当原样抛出，让真问题以 500 暴露，而不是被伪装成一个用户能理解的错误。
    """
    with pytest.raises(IntegrityError):
        create_datasource(db_session, payload=_payload(), created_by=uuid.uuid4())


def test_admin_sees_every_datasource(db_session, make_user, make_datasource) -> None:
    admin = make_user(role="admin")
    make_datasource(name="甲")
    make_datasource(name="乙")

    names = {d.name for d in list_visible(db_session, admin)}

    assert names == {"甲", "乙"}


def test_analyst_sees_only_granted_datasources(db_session, make_user, make_datasource) -> None:
    analyst = make_user(role="analyst")
    granted = make_datasource(name="已授权")
    make_datasource(name="未授权")
    set_grant(db_session, datasource_id=granted.id, user_id=analyst.id, can_query=True)

    assert [d.name for d in list_visible(db_session, analyst)] == ["已授权"]


def test_can_query_false_does_not_grant_visibility(db_session, make_user, make_datasource) -> None:
    """授权行存在但 can_query=false 等于没授权，不是「只读可见」。"""
    viewer = make_user(role="viewer")
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=viewer.id, can_query=False)

    assert list_visible(db_session, viewer) == []
    assert get_visible(db_session, viewer, datasource.id) is None


def test_get_visible_returns_none_for_an_ungranted_datasource(
    db_session, make_user, make_datasource
) -> None:
    analyst = make_user(role="analyst")
    datasource = make_datasource()

    assert get_visible(db_session, analyst, datasource.id) is None


def test_get_visible_returns_none_for_an_unknown_id(db_session, make_user) -> None:
    admin = make_user(role="admin")

    assert get_visible(db_session, admin, uuid.uuid4()) is None


def test_datasource_exists_separates_unknown_from_unauthorized(db_session, make_datasource) -> None:
    """get_visible 对两种情况都返回 None，deps 靠这个函数把 404 与 403 分开。"""
    datasource = make_datasource()

    assert datasource_exists(db_session, datasource.id) is True
    assert datasource_exists(db_session, uuid.uuid4()) is False


def test_updating_the_password_rotates_the_nonce(db_session, make_user) -> None:
    """每次写入换新 nonce。AES-GCM 下同密钥重用 nonce 直接泄露明文异或。"""
    admin = make_user(role="admin")
    datasource = create_datasource(db_session, payload=_payload(), created_by=admin.id)
    old_nonce = datasource.secret_nonce

    update_datasource(db_session, datasource, DatasourceUpdate(password="brand-new-pw"))

    assert datasource.secret_nonce != old_nonce
    assert read_password(datasource) == "brand-new-pw"


def test_update_without_a_password_leaves_the_credential_untouched(db_session, make_user) -> None:
    admin = make_user(role="admin")
    datasource = create_datasource(db_session, payload=_payload(), created_by=admin.id)
    before = (datasource.secret_ciphertext, datasource.secret_nonce)

    update_datasource(db_session, datasource, DatasourceUpdate(host="moved.internal"))

    assert (datasource.secret_ciphertext, datasource.secret_nonce) == before
    assert datasource.host == "moved.internal"
    assert read_password(datasource) == "ds-pw-123456"


def test_renaming_onto_an_existing_name_raises_api_error(db_session, make_user) -> None:
    admin = make_user(role="admin")
    create_datasource(db_session, payload=_payload(name="甲"), created_by=admin.id)
    second = create_datasource(db_session, payload=_payload(name="乙"), created_by=admin.id)

    with pytest.raises(ApiError) as exc_info:
        update_datasource(db_session, second, DatasourceUpdate(name="甲"))

    assert exc_info.value.code == "DATASOURCE_NAME_EXISTS"
    assert len(list_visible(db_session, admin)) == 2


def test_set_grant_is_idempotent(db_session, make_user, make_datasource) -> None:
    """同一 (datasource, user) 只有一行，重复授权是改 can_query 而不是插第二行。"""
    analyst = make_user(role="analyst")
    datasource = make_datasource()

    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=False)

    grants = list_grants(db_session, datasource.id)
    assert len(grants) == 1
    assert grants[0].can_query is False


def test_revoke_grant_reports_whether_anything_was_removed(
    db_session, make_user, make_datasource
) -> None:
    analyst = make_user(role="analyst")
    datasource = make_datasource()
    set_grant(db_session, datasource_id=datasource.id, user_id=analyst.id, can_query=True)

    assert revoke_grant(db_session, datasource_id=datasource.id, user_id=analyst.id) is True
    assert revoke_grant(db_session, datasource_id=datasource.id, user_id=analyst.id) is False
    assert list_grants(db_session, datasource.id) == []


def test_delete_removes_the_datasource_from_every_listing(
    db_session, make_user, make_datasource
) -> None:
    admin = make_user(role="admin")
    datasource = make_datasource()

    delete_datasource(db_session, datasource)

    assert list_visible(db_session, admin) == []


def test_the_response_model_declares_no_credential_fields() -> None:
    """spec §4.4 的红线：靠模型不含字段，而不是靠序列化时记得排除。"""
    forbidden = {"password", "secret", "secret_ciphertext", "secret_nonce", "ciphertext", "nonce"}

    assert not (set(DatasourceResponse.model_fields) & forbidden)


def test_the_kind_literal_matches_the_model_constant() -> None:
    """Literal 存在是为了让 OpenAPI 出 enum（P4 生成前端类型要用），
    但它和 DATASOURCE_KINDS 是两处声明，这条防它们漂移。
    """
    annotation = DatasourceCreate.model_fields["kind"].annotation

    assert set(get_args(annotation)) == set(DATASOURCE_KINDS)
