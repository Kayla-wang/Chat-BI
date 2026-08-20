"""行列级策略的注入点（上游 spec §4.2、§6）。

V2-1 只有 EmptyPolicyResolver。V2-2 落地行列级权限时**只改这个文件与语义层新表**，
执行器与 guard 的调用方不动——这是 spec §4.2 的承诺，而它成立的前提是 validate_sql()
的签名现在就有 policy 参数。
"""

import uuid
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Policy:
    """V2-1 恒为空。"""

    row_filters: tuple[str, ...] = ()
    """要 AND 进 WHERE 的条件表达式。"""

    denied_columns: frozenset[str] = field(default_factory=frozenset)
    """禁止出现在结果里的列名。"""

    @property
    def is_empty(self) -> bool:
        return not self.row_filters and not self.denied_columns


class PolicyResolver(Protocol):
    def resolve(self, *, user_id: uuid.UUID, datasource_id: uuid.UUID) -> Policy: ...


class EmptyPolicyResolver:
    """V2-1 唯一实现：恒返回空策略（上游 spec §4.2）。"""

    def resolve(self, *, user_id: uuid.UUID, datasource_id: uuid.UUID) -> Policy:
        return Policy()
