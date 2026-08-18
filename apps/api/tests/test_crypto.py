"""crypto.py 的单元测试。整个文件不需要数据库——这正是把它与 repository 分开的意义。"""

import os
import uuid

import pytest

from chatbi.config import get_settings
from chatbi.datasources.crypto import (
    NONCE_BYTES,
    MasterKey,
    SealedSecret,
    SecretDecryptionError,
    aad_for_datasource,
    get_master_key,
    seal,
    unseal,
)

AAD = aad_for_datasource(uuid.UUID("11111111-1111-1111-1111-111111111111"))
OTHER_AAD = aad_for_datasource(uuid.UUID("22222222-2222-2222-2222-222222222222"))


def test_seal_then_unseal_returns_the_original_password() -> None:
    sealed = seal("p@ssw0rd 带中文", aad=AAD)

    assert unseal(sealed, aad=AAD) == "p@ssw0rd 带中文"


def test_ciphertext_never_contains_the_plaintext() -> None:
    sealed = seal("supersecret", aad=AAD)

    assert b"supersecret" not in sealed.ciphertext


def test_every_seal_uses_a_fresh_nonce() -> None:
    """AES-GCM 下同密钥重用 nonce 会直接泄露明文异或与认证密钥，这是硬红线。"""
    sealeds = [seal("same-password", aad=AAD) for _ in range(64)]

    nonces = {s.nonce for s in sealeds}
    assert len(nonces) == 64
    assert all(len(n) == NONCE_BYTES for n in nonces)
    # 相同明文 + 相同 AAD 也必须产出不同密文，否则等值密文本身就是一条侧信道
    assert len({s.ciphertext for s in sealeds}) == 64


def test_tampered_ciphertext_is_rejected() -> None:
    sealed = seal("p@ssw0rd", aad=AAD)
    flipped = bytearray(sealed.ciphertext)
    flipped[0] ^= 0x01

    with pytest.raises(SecretDecryptionError):
        unseal(SealedSecret(ciphertext=bytes(flipped), nonce=sealed.nonce), aad=AAD)


def test_tampered_nonce_is_rejected() -> None:
    sealed = seal("p@ssw0rd", aad=AAD)

    with pytest.raises(SecretDecryptionError):
        unseal(SealedSecret(ciphertext=sealed.ciphertext, nonce=os.urandom(NONCE_BYTES)), aad=AAD)


def test_ciphertext_is_bound_to_its_datasource() -> None:
    """把 A 的密文行搬到 B 上不能解开：AAD 绑定了数据源 id。

    否则一个能写库的攻击者可以把生产库的凭据密文挪到一个指向自己主机的
    数据源上，让后端拿着生产密码去连他的服务器。
    """
    sealed = seal("p@ssw0rd", aad=AAD)

    with pytest.raises(SecretDecryptionError):
        unseal(sealed, aad=OTHER_AAD)


def test_decryption_error_leaks_nothing() -> None:
    sealed = seal("supersecret", aad=AAD)

    with pytest.raises(SecretDecryptionError) as exc_info:
        unseal(sealed, aad=OTHER_AAD)

    text = str(exc_info.value)
    assert "supersecret" not in text
    assert sealed.ciphertext.hex() not in text
    assert get_settings().secret_key.get_secret_value() not in text


def test_master_key_is_masked_in_repr_and_str() -> None:
    """密钥对象会出现在异常回溯的局部变量表里，那里是日志的一条旁路。"""
    key = get_master_key()
    material = os.environ["CHATBI_SECRET_KEY"]

    assert repr(key) == "MasterKey(***)"
    assert str(key) == "MasterKey(***)"
    assert material not in repr(key)
    assert not any("material" in name and not name.startswith("_") for name in dir(key))


def test_key_derivation_is_deterministic_and_key_dependent(monkeypatch) -> None:
    """同主密钥重启后仍能解开旧密文；换主密钥则解不开（而不是解出乱码）。"""
    sealed = seal("p@ssw0rd", aad=AAD)
    original = os.environ["CHATBI_SECRET_KEY"]

    def rebuild(secret: str) -> None:
        monkeypatch.setenv("CHATBI_SECRET_KEY", secret)
        get_settings.cache_clear()
        get_master_key.cache_clear()

    rebuild(original)
    assert unseal(sealed, aad=AAD) == "p@ssw0rd"

    rebuild("a-completely-different-master-key")
    with pytest.raises(SecretDecryptionError):
        unseal(sealed, aad=AAD)

    # 缓存必须还原，否则后续测试会拿着假密钥跑
    rebuild(original)
    get_settings.cache_clear()
    get_master_key.cache_clear()


def test_master_key_rejects_wrong_length_material() -> None:
    with pytest.raises(ValueError):
        MasterKey(b"too-short")
