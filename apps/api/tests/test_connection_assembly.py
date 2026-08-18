"""模型 → ConnectionInfo 的组装。这是明文密码从仓储走向驱动的唯一一段路。"""

from chatbi.datasources.connection import connection_info


def test_connection_info_carries_the_model_fields(make_datasource) -> None:
    datasource = make_datasource(
        kind="mysql", host="mysql.internal", port=3306, database="sales", username="reader"
    )

    info = connection_info(datasource)

    assert info.kind == "mysql"
    assert info.host == "mysql.internal"
    assert info.port == 3306
    assert info.database == "sales"
    assert info.username == "reader"


def test_connection_info_carries_the_decrypted_password(make_datasource) -> None:
    """组装必须解密——驱动拿到密文是连不上的，而那种 bug 表现为「密码错误」，
    会让人去查凭据配置而不是查这一行。
    """
    datasource = make_datasource(password="ds-pw-123456")

    assert connection_info(datasource).password == "ds-pw-123456"


def test_connection_info_has_no_password_when_none_is_stored(make_datasource) -> None:
    datasource = make_datasource(password=None)

    assert connection_info(datasource).password is None


def test_connection_info_passes_options_through(make_datasource) -> None:
    """options 原样透传给驱动（sslmode 之类）。P2a 不校验内容，驱动自己认。"""
    datasource = make_datasource(options={"sslmode": "require"})

    assert connection_info(datasource).options == {"sslmode": "require"}


def test_the_assembled_info_hides_the_password_in_repr(make_datasource) -> None:
    """上游的 ConnectionInfo 已经掩码了，这条钉的是「组装没绕过它」——
    比如有人图省事返回了一个普通 dataclass 或 dict。
    """
    datasource = make_datasource(password="ds-pw-123456")

    assert "ds-pw-123456" not in repr(connection_info(datasource))
