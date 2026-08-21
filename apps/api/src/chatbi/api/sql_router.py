"""/api/datasources/{id}/sql/validate 的 HTTP 编排。

**本文件是唯一同时认识 Datasource 与 guard 的地方**：从 datasource.kind 取方言、从
Settings 取行数上限、从依赖取 policy，然后调纯函数。guard 自己不认识数据源模型（它是
安全红线，必须能脱离库穷举边界）。

不写 db.commit()：这个端点不写库（设计 §4.3——它每 300ms 就可能被调一次，为每次按键建
审计记录会把 run_events 变成击键日志，而 F-304 要审计的是执行，不是编辑过程）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from chatbi.auth.deps import current_user
from chatbi.auth.schemas import ErrorResponse
from chatbi.config import get_settings
from chatbi.datasources.deps import require_datasource
from chatbi.datasources.schemas import SqlValidateRequest, SqlValidateResponse
from chatbi.db.models import Datasource, User
from chatbi.guard.deps import policy_resolver_for
from chatbi.guard.policy import PolicyResolver
from chatbi.guard.validator import validate_sql

router = APIRouter(prefix="/api/datasources", tags=["sql"])

_CurrentUser = Annotated[User, Depends(current_user)]
_Target = Annotated[Datasource, Depends(require_datasource)]
_Resolver = Annotated[PolicyResolver, Depends(policy_resolver_for)]

_TARGET = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}

# kind -> sqlglot 方言名。三者现在同名，但**显式写出来**而不是直接传 kind：两套命名空间
# 的巧合不是契约，将来加一个 kind（比如 "trino"）时映射可能不同。
#
# 这张表的键必须覆盖 db.models.DATASOURCE_KINDS 全部三个——漏一个会让那种数据源的
# /sql/validate 抛 KeyError 500。tests/test_sql_router.py 有一条测试遍历那个常量。
_DIALECTS = {"postgres": "postgres", "mysql": "mysql", "clickhouse": "clickhouse"}


@router.post(
    "/{datasource_id}/sql/validate",
    response_model=SqlValidateResponse,
    responses=_TARGET,
)
def validate(
    payload: SqlValidateRequest,
    datasource: _Target,
    resolver: _Resolver,
    user: _CurrentUser,
) -> SqlValidateResponse:
    """闸 2 + 闸 3 的判定（上游 spec §2.4）。

    **判定失败返回 200 + ok=false**，不是 4xx——见 SqlValidateResponse 的文档字符串。
    """
    verdict = validate_sql(
        payload.sql,
        dialect=_DIALECTS[datasource.kind],
        max_rows=get_settings().max_result_rows,
        policy=resolver.resolve(user_id=user.id, datasource_id=datasource.id),
    )
    return SqlValidateResponse(
        ok=verdict.ok,
        code=verdict.code,
        reason=verdict.reason,
        effective_sql=verdict.effective_sql,
        limit_applied=verdict.limit_applied,
        warnings=list(verdict.warnings),
    )
