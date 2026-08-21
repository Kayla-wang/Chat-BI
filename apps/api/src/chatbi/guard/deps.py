"""guard 的 FastAPI 依赖。

policy_resolver_for 做成依赖**只为可测**：P3b 的执行器测试要能塞一个返回非空策略的假
resolver，验证 validate_sql 真的会抛 NotImplementedError。P1 遗留 2 是反例
（get_identity_provider 当初不是依赖，测试里换不掉，拖到 P2a Task 1 才补）。

这个文件是 guard/ 里**唯一**与 FastAPI 有关的东西，其余模块（validator / policy /
schemas）一个 fastapi 都不 import——那是安全红线代码能脱离 HTTP 穷举边界的前提。
"""

from chatbi.guard.policy import EmptyPolicyResolver, PolicyResolver


def policy_resolver_for() -> PolicyResolver:
    """V2-1 恒返回 EmptyPolicyResolver（上游 spec §4.2）。"""
    return EmptyPolicyResolver()
