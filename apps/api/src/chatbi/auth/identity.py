from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from chatbi.auth.hashing import hash_password, verify_password
from chatbi.db.models import User

# 邮箱不存在时也走一次哈希校验，让成功与失败路径耗时接近，不泄露账号是否存在
_DUMMY_HASH = hash_password("timing-equalizer")


def normalize_email(email: str) -> str:
    return email.strip().lower()


class IdentityProvider(Protocol):
    """身份来源抽象。V2-1 只有本地账号；OIDC/LDAP 换实现不改调用方。"""

    def authenticate(self, session: Session, email: str, password: str) -> User | None: ...


class LocalIdentityProvider:
    def authenticate(self, session: Session, email: str, password: str) -> User | None:
        user = session.scalar(select(User).where(User.email == normalize_email(email)))
        if user is None:
            verify_password(password, _DUMMY_HASH)
            return None
        password_ok = verify_password(password, user.password_hash)
        # is_active 的判断必须在校验之后：提前 return 会让「存在但被禁用」
        # 比其他失败路径快一个 Argon2 的时间，等于把账号状态泄漏给计时攻击。
        if not password_ok or not user.is_active:
            return None
        return user


def get_identity_provider() -> IdentityProvider:
    return LocalIdentityProvider()
