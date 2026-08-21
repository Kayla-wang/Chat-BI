"""SSE 的行格式。

一个事件三部分：`event: <名字>` 行、`data: <紧凑 JSON>` 行、一个空行。

**不引 sse-starlette**：格式就这么点，自己拼比引一个包更容易看清发出去的到底是什么，
而且少一个依赖。实测 TestClient.stream() 能读这个格式。

data 恒为一行 JSON，不做多行 data:（SSE 允许，但那需要接收端拼接，而我们的载荷都是小
JSON）。代价是长 SQL 会让那一行很长，可接受。
"""

import json
from typing import Any


def sse(event: str, data: dict[str, Any]) -> bytes:
    """拼一个 SSE 事件。

    ensure_ascii=False：载荷里有中文（错误文案、注释、chips），转义成 \\uXXXX 会让调试时
    的抓包完全不可读，而 SSE 的传输编码是 UTF-8。

    separators 去掉空格：这条流可能发很多次，没必要为可读性付带宽——需要读的时候抓包
    工具会格式化。
    """
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode()
