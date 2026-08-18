"""ClickHouse 类型名解析。纯字符串函数，不需要真库——所以没有理由不测。"""

import pytest

from chatbi.datasources.drivers.clickhouse import _is_numeric, _unwrap


@pytest.mark.parametrize(
    ("type_name", "inner", "nullable"),
    [
        ("Int32", "Int32", False),
        ("Nullable(Int32)", "Int32", True),
        ("Decimal(12, 2)", "Decimal(12, 2)", False),
        ("Nullable(Decimal(12, 2))", "Decimal(12, 2)", True),
        ("LowCardinality(String)", "String", False),
        ("LowCardinality(Nullable(String))", "String", True),
    ],
)
def test_unwrap(type_name: str, inner: str, nullable: bool) -> None:
    assert _unwrap(type_name) == (inner, nullable)


@pytest.mark.parametrize(
    ("type_name", "expected"),
    [
        ("Int8", True),
        ("UInt64", True),
        ("Float32", True),
        ("Decimal(12, 2)", True),
        ("Nullable(Int32)", True),
        ("String", False),
        ("LowCardinality(String)", False),
        ("DateTime64(3)", False),
        ("Array(Int32)", False),
    ],
)
def test_is_numeric(type_name: str, expected: bool) -> None:
    assert _is_numeric(type_name) is expected
