"""Ollama 的 /api/generate 流式调用（P3c 设计 §3.3）。

两个超时的实现方式不同，这是本文件的核心：
  first_token —— 用 asyncio.timeout 包住「拿到第一个片段」这段等待。
  total       —— 用一个 deadline 在每次拿到片段后检查，超了就 break 并抛。
**不要用一个 asyncio.timeout 包住整个循环**：那样两种失败会抛出同一个异常，而它们的
运维含义完全不同（设计 §3.2），运维手上只有那句 message。

取消是免费的：调用方取消这个生成器 → async with client.stream 退出 → 连接关闭 →
Ollama 侧停止生成。**这里不需要任何显式的取消动作**，与 execution/registry.py 那种
「另开一条连接发 pg_cancel_backend」是两个世界（P3c 设计 §3.1）。
"""

import asyncio
import json
from collections.abc import AsyncIterator

import httpx

from chatbi.llm.base import LLMTimeout, LLMUnavailable

_TIMEOUT_FLOOR = 0.001


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        keep_alive: str = "30m",
        temperature: float = 0.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._keep_alive = keep_alive
        self._temperature = temperature
        self._client = client
        """可注入 —— 测试塞一个 MockTransport 的 client 进来。None 时每次调用自己建
        一个（单机部署下一次问答一条连接，不值得维护一个长命 client）。"""

    async def stream(
        self, prompt: str, *, first_token_timeout: float, total_timeout: float
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": self._keep_alive,
            # temperature 默认 0：出 SQL 不需要创造力，而确定性让「同一个问题两次给
            # 不同 SQL」这种最难排查的现象消失（设计 §3.3）
            "options": {"temperature": self._temperature},
        }
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            async for chunk in self._stream_with(
                client, payload, first_token_timeout, total_timeout
            ):
                yield chunk
        finally:
            if owns_client:
                await client.aclose()

    async def _stream_with(
        self,
        client: httpx.AsyncClient,
        payload: dict,
        first_token_timeout: float,
        total_timeout: float,
    ) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + total_timeout
        first = True
        try:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=httpx.Timeout(None, connect=first_token_timeout),
            ) as response:
                if response.status_code >= 400:
                    # **不读响应体也不进消息**：Ollama 的错误体可能带模型路径
                    raise LLMUnavailable()
                lines = response.aiter_lines()
                while True:
                    budget = (
                        first_token_timeout
                        if first
                        else max(deadline - loop.time(), _TIMEOUT_FLOOR)
                    )
                    try:
                        async with asyncio.timeout(budget):
                            line = await anext(lines)
                    except StopAsyncIteration:
                        return
                    except TimeoutError:
                        raise LLMTimeout(
                            "first_token" if first else "total",
                            first_token_timeout if first else total_timeout,
                        ) from None
                    first = False
                    piece, done = _parse_line(line)
                    if piece:
                        yield piece
                    if done:
                        return
                    if loop.time() >= deadline:
                        raise LLMTimeout("total", total_timeout)
        except httpx.HTTPError as exc:
            # 连不上、DNS 失败、读超时。**原始异常不往上带**（它的 str 里有 url）
            raise LLMUnavailable() from exc


def _parse_line(line: str) -> tuple[str, bool]:
    """一行 NDJSON → (文本片段, 是否结束)。

    **解析不了的行静默跳过**：Ollama 在流里偶尔插入空行，而为了一个空行让整次生成失败
    是不成比例的。真正的失败由状态码与超时兜住。
    """
    line = line.strip()
    if not line:
        return "", False
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return "", False
    return str(data.get("response") or ""), bool(data.get("done"))
