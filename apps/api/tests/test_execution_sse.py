"""SSE 行格式（纯函数，无夹具）。"""

from chatbi.execution.sse import sse


def test_an_event_has_three_parts() -> None:
    """event 行、data 行、一个空行。少了那个空行接收端不会认为事件结束。"""
    assert sse("done", {"status": "succeeded"}) == (
        b'event: done\ndata: {"status":"succeeded"}\n\n'
    )


def test_chinese_is_not_escaped() -> None:
    """载荷里有中文错误文案。转义成 \\uXXXX 会让抓包不可读。"""
    raw = sse("error", {"message": "查询已取消"})

    assert "查询已取消".encode() in raw
    assert b"\\u" not in raw


def test_an_empty_payload_is_still_valid_json() -> None:
    """ping 的载荷是空的 {}（上游 spec §2.3：不假装有进度条）。"""
    assert sse("ping", {}) == b"event: ping\ndata: {}\n\n"


def test_no_spaces_in_the_json() -> None:
    """紧凑分隔符。这条不是风格洁癖——它钉住 separators 参数没被删掉，否则每个事件多出
    几十字节，而这条流一次执行可能发上百个事件。
    """
    assert b'{"a":1,"b":2}' in sse("x", {"a": 1, "b": 2})
