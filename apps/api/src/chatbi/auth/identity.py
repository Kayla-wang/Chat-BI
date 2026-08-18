from functools import cache, lru_cache
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from chatbi.auth.hashing import hash_password, verify_password
from chatbi.db.models import User


@cache
def _dummy_hash() -> str:
    """邮箱不存在时也走一次哈希校验，让成功与失败路径耗时接近，不泄露账号是否存在。

    惰性算：放模块级会让每次 CLI 调用和每轮 pytest 收集都白付一次 Argon2。
    """
    return hash_password("timing-equalizer")


def normalize_email(email: str) -> str:
    return email.strip().lower()


class IdentityProvider(Protocol):
    """身份来源抽象。V2-1 只有本地账号；OIDC/LDAP 换实现不改调用方。"""

    def authenticate(self, session: Session, email: str, password: str) -> User | None: ...


class LocalIdentityProvider:
    def authenticate(self, session: Session, email: str, password: str) -> User | None:
        user = session.scalar(select(User).where(User.email == normalize_email(email)))
        if user is None:
            verify_password(password, _dummy_hash())
            return None
        password_ok = verify_password(password, user.password_hash)
        # is_active 的判断必须在校验之后：提前 return 会让「存在但被禁用」
        # 比其他失败路径快一个 Argon2 的时间，等于把账号状态泄漏给计时攻击。
        if not password_ok or not user.is_active:
            return None
        return user


@lru_cache
def get_identity_provider() -> IdentityProvider:
    """provider 无状态，共享一个实例即可。

    加 lru_cache 不影响 dependency_overrides：FastAPI 是按函数对象作键替换，
    根本不会调到这个函数。
    """
    return LocalIdentityProvider()
