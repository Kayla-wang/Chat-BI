"""数据源与授权的持久化、可见性过滤、密码存取。

不 import fastapi：可见性判断是领域逻辑，必须能脱离 HTTP 测（spec §1.3 规则 2）。
ApiError 是错误契约不是框架依赖，可以用。
"""

import uuid
from collections.abc import Callable

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatbi.datasources.crypto import SealedSecret, aad_for_datasource, seal, unseal
from chatbi.datasources.schemas import DatasourceCreate, DatasourceUpdate
from chatbi.db.integrity import violated_constraint
from chatbi.db.models import Datasource, DatasourceGrant, User
from chatbi.errors import DATASOURCE_NAME_EXISTS, ApiError

# 只有 admin 无条件看全部；analyst/viewer 一律走 datasource_grants（spec §4.2）
_UNRESTRICTED_ROLES = frozenset({"admin"})
_NAME_CONSTRAINT = "ix_datasources_name"


def _visible_where(user: User):
    """加在 select(Datasource) 上的可见性条件。

    非 admin 用 EXISTS 而不是 JOIN：EXISTS 表达的是「存在一条有效授权」，语义与
    意图一致；JOIN 的行数依赖授权表不出现重复行，那是靠复合主键的间接保证。
    """
    if user.role in _UNRESTRICTED_ROLES:
        return sa.true()
    return sa.exists().where(
        DatasourceGrant.datasource_id == Datasource.id,
        DatasourceGrant.user_id == user.id,
        DatasourceGrant.can_query.is_(True),
    )


def _is_name_conflict(exc: IntegrityError) -> bool:
    """只把唯一名冲突翻成 409，别的 IntegrityError 原样抛。

    把外键或 CHECK 违规也报成「名称已存在」是撒谎，会让真 bug 伪装成用户错误。
    约束名取不到时 violated_constraint 返回 None，这里就判 False——宁可暴露一个
    500，也不谎报一个用户能理解的 409。
    """
    return violated_constraint(exc) == _NAME_CONSTRAINT


def _within_savepoint(session: Session, mutate: Callable[[], None]) -> None:
    """在 savepoint 里执行改动 + flush，把唯一名冲突翻成 409。

    改动必须发生在 savepoint **内部**：快照在 begin_nested() 那一刻拍下，之前做的
    add/赋值不会被回滚，会在下一次 flush 时原地再炸一次。
    需要 savepoint 是因为 IntegrityError 之后事务不可用，而 HTTP 层还要靠同一个
    事务把 409 发出去。不用 check-then-insert：并发下两个请求都会查到「没有」。
    """
    savepoint = session.begin_nested()
    try:
        mutate()
        session.flush()
    except IntegrityError as exc:
        savepoint.rollback()
        if not _is_name_conflict(exc):
            raise
        raise ApiError(*DATASOURCE_NAME_EXISTS) from exc
    savepoint.commit()


def _store_password(datasource: Datasource, password: str) -> None:
    """每次调用都换新 nonce（seal 内部 os.urandom）。nonce 绝不复用。"""
    sealed = seal(password, aad=aad_for_datasource(datasource.id))
    datasource.secret_ciphertext = sealed.ciphertext
    datasource.secret_nonce = sealed.nonce


def create_datasource(
    session: Session, *, payload: DatasourceCreate, created_by: uuid.UUID
) -> Datasource:
    # id 在应用侧生成：AAD 绑的是数据源 id，加密前就得知道它
    datasource = Datasource(
        id=uuid.uuid4(),
        name=payload.name,
        kind=payload.kind,
        host=payload.host,
        port=payload.port,
        database=payload.database,
        username=payload.username,
        options=payload.options,
        created_by=created_by,
    )
    if payload.password is not None:
        _store_password(datasource, payload.password)
    _within_savepoint(session, lambda: session.add(datasource))
    return datasource


def update_datasource(
    session: Session, datasource: Datasource, payload: DatasourceUpdate
) -> Datasource:
    def mutate() -> None:
        for field in ("name", "kind", "host", "port", "database", "username", "options"):
            value = getattr(payload, field)
            if value is not None:
                setattr(datasource, field, value)
        if payload.password is not None:
            _store_password(datasource, payload.password)

    _within_savepoint(session, mutate)
    return datasource


def delete_datasource(session: Session, datasource: Datasource) -> None:
    session.delete(datasource)
    session.flush()


def list_visible(session: Session, user: User) -> list[Datasource]:
    statement = sa.select(Datasource).where(_visible_where(user)).order_by(Datasource.name)
    return list(session.scalars(statement))


def get_visible(session: Session, user: User, datasource_id: uuid.UUID) -> Datasource | None:
    """取 + 判定一步完成，没有「先取出来再判断」之间的窗口。

    不存在与无权限都返回 None；把 404 与 403 分开是 deps 的事（用 datasource_exists）。
    """
    statement = sa.select(Datasource).where(Datasource.id == datasource_id, _visible_where(user))
    return session.scalars(statement).one_or_none()


def datasource_exists(session: Session, datasource_id: uuid.UUID) -> bool:
    """不带可见性条件——只回答「这个 id 在不在」，给 deps 区分 404 与 403 用。"""
    count = session.scalar(
        sa.select(sa.func.count()).select_from(Datasource).where(Datasource.id == datasource_id)
    )
    return bool(count)


def read_password(datasource: Datasource) -> str | None:
    """解出明文密码。没有 session 参数——纯函数，只读 ORM 对象上的两列。

    调用方只有 P2b 的驱动层。返回值不得进日志、不得进 HTTP 响应。
    """
    if datasource.secret_ciphertext is None or datasource.secret_nonce is None:
        return None
    sealed = SealedSecret(ciphertext=datasource.secret_ciphertext, nonce=datasource.secret_nonce)
    return unseal(sealed, aad=aad_for_datasource(datasource.id))


def set_grant(
    session: Session, *, datasource_id: uuid.UUID, user_id: uuid.UUID, can_query: bool
) -> DatasourceGrant:
    """幂等：同一 (datasource, user) 只有一行，重复授权是改 can_query。"""
    grant = session.get(DatasourceGrant, {"datasource_id": datasource_id, "user_id": user_id})
    if grant is None:
        grant = DatasourceGrant(datasource_id=datasource_id, user_id=user_id, can_query=can_query)
        session.add(grant)
    else:
        grant.can_query = can_query
    session.flush()
    return grant


def revoke_grant(session: Session, *, datasource_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """撤销授权，返回是否真删到了行。

    HTTP 层的 DELETE 按 HTTP 语义幂等，**不消费**这个返回值（重复撤销一样 204）。
    它存在是因为「重复撤销不报错、且第二次确实没删到东西」这条性质要能被断言。
    """
    result = session.execute(
        sa.delete(DatasourceGrant).where(
            DatasourceGrant.datasource_id == datasource_id,
            DatasourceGrant.user_id == user_id,
        )
    )
    session.flush()
    return bool(result.rowcount)


def list_grants(session: Session, datasource_id: uuid.UUID) -> list[DatasourceGrant]:
    statement = (
        sa.select(DatasourceGrant)
        .where(DatasourceGrant.datasource_id == datasource_id)
        .order_by(DatasourceGrant.user_id)
    )
    return list(session.scalars(statement))
