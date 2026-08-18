"""数据源凭据的 AEAD 封装。

只认识 bytes 与 str：不 import 任何 chatbi.db.*，也不认识 ORM（spec §1.3）。
"""

import os
import uuid
from dataclasses import dataclass
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from chatbi.config import get_settings

KEY_BYTES = 32  # AES-256
NONCE_BYTES = 12  # AES-GCM 的标准 nonce 长度；换长度会让已存密文解不开
# HKDF 的 info 做域分隔：将来别的用途（比如导出签名）从同一主密钥派生时，
# 换一个 info 就是一把互不相关的子密钥。带 :v1 是为了留轮换的余地。
HKDF_INFO = b"chatbi:datasource-secret:v1"


class SecretDecryptionError(Exception):
    """密文与主密钥或 AAD 不匹配。异常本身不携带密文、密钥或明文。"""


@dataclass(frozen=True)
class SealedSecret:
    """一条已加密的凭据。两个字段直接对应表里的两列。"""

    ciphertext: bytes
    nonce: bytes


class MasterKey:
    """派生出的 AES-256 密钥。

    repr/str 恒为掩码：这个对象会出现在异常回溯的局部变量表里，而 pytest 的
    `--showlocals`、以及大多数错误上报工具都会把局部变量原样打出来。
    密钥材料只在 aesgcm() 内部使用，不提供任何取出它的公开途径（spec §4.4）。
    """

    __slots__ = ("_material",)

    def __init__(self, material: bytes) -> None:
        if len(material) != KEY_BYTES:
            raise ValueError(f"派生密钥必须是 {KEY_BYTES} 字节，收到 {len(material)}")
        self._material = material

    def __repr__(self) -> str:
        return "MasterKey(***)"

    __str__ = __repr__

    def aesgcm(self) -> AESGCM:
        return AESGCM(self._material)


@lru_cache
def get_master_key() -> MasterKey:
    """从配置里的主密钥派生 AEAD 密钥。

    salt 恒为 None（RFC 5869 允许）：派生必须确定性，否则重启后解不开旧密文。
    改主密钥后测试里要 get_settings.cache_clear() + get_master_key.cache_clear()。
    """
    secret = get_settings().secret_key
    # 声明类型是 SecretStr | None，但 Settings 的 after-validator 保证实例化后必非 None
    assert secret is not None, "主密钥未配置——Settings 校验本应已拦下"
    material = HKDF(
        algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=HKDF_INFO
    ).derive(secret.get_secret_value().encode("utf-8"))
    return MasterKey(material)


def aad_for_datasource(datasource_id: uuid.UUID) -> bytes:
    """把密文绑定到它所属的数据源，防止密文行被搬到另一个数据源上。"""
    return f"datasource:{datasource_id}".encode()


def seal(plaintext: str, *, aad: bytes) -> SealedSecret:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = get_master_key().aesgcm().encrypt(nonce, plaintext.encode("utf-8"), aad)
    return SealedSecret(ciphertext=ciphertext, nonce=nonce)


def unseal(sealed: SealedSecret, *, aad: bytes) -> str:
    try:
        raw = get_master_key().aesgcm().decrypt(sealed.nonce, sealed.ciphertext, aad)
    except InvalidTag as exc:
        # 不用 from exc 之外的方式携带上下文：InvalidTag 本身不含明文，
        # 但消息里绝不能拼进密文或 AAD。
        raise SecretDecryptionError("凭据无法解密") from exc
    return raw.decode("utf-8")
