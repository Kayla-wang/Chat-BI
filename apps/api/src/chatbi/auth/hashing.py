from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

_hasher = PasswordHasher()  # 默认算法即 argon2id


def hash_password(plaintext: str) -> str:
    return _hasher.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    """密码是否匹配。

    哈希串损坏时返回 False 而不是抛异常——调用方在登录路径上，不该因为库里
    一条脏数据就 500。这里只对「存储的哈希」宽容：非字符串或空串直接判为不匹配。
    plaintext 的类型错误仍然让它抛出去，那是调用方的 bug，不该被静默吞掉。
    """
    if not isinstance(hashed, str) or not hashed:
        return False
    try:
        return _hasher.verify(hashed, plaintext)
    except (Argon2Error, InvalidHashError):
        return False
