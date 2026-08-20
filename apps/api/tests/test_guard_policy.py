"""Policy 注入点（上游 spec §4.2、§6；设计 §6.1）。"""

import uuid

import pytest

from chatbi.guard.policy import EmptyPolicyResolver, Policy
from chatbi.guard.validator import validate_sql


def test_the_v2_1_resolver_always_returns_an_empty_policy() -> None:
    policy = EmptyPolicyResolver().resolve(user_id=uuid.uuid4(), datasource_id=uuid.uuid4())

    assert policy.is_empty is True


def test_a_non_empty_policy_is_not_silently_ignored() -> None:
    """V2-1 不可能触发这条（只有 EmptyPolicyResolver），它是 **V2-2 的护栏**：

    一个非空 policy 被无声丢掉，等于行列级权限「看起来生效了实际没有」——那是最坏的
    一类安全失败，因为没有任何症状。宁可让 V2-2 的实施者撞上一个 NotImplementedError。
    """
    with pytest.raises(NotImplementedError):
        validate_sql(
            "select 1",
            dialect="postgres",
            max_rows=1000,
            policy=Policy(row_filters=("tenant_id = 1",)),
        )


def test_a_policy_with_only_denied_columns_also_raises() -> None:
    """两个字段各自都要能触发。只检查 row_filters 的实现会静默忽略列级策略。"""
    with pytest.raises(NotImplementedError):
        validate_sql(
            "select 1",
            dialect="postgres",
            max_rows=1000,
            policy=Policy(denied_columns=frozenset({"salary"})),
        )
