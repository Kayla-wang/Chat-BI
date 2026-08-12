from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

_hasher = PasswordHasher()  # 默认算法即 argon2id


def hash_password(plaintext: str) -> str:
    return _hasher.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    """密码是否匹配。哈希串损坏时返回 False 而不是抛异常——
    调用方在登录路径上，不该因为库里一条脏数据就 500。"""
    try:
        return _hasher.verify(hashed, plaintext)
    except (Argon2Error, InvalidHashError):
        return False
