"""Ollama provider：请求体、流式解析、两个超时（P3c 设计 §3.2、§3.3）。

**不连真 Ollama**。用 httpx.MockTransport 造响应——那是唯一能确定性地测「首 token
迟到」与「吐到一半超时」的办法（真服务上这两件事都不可复现）。真跑是 p3c3 的退出标准。
"""

import asyncio
import json

import httpx
import pytest

from chatbi.llm.base import LLMTimeout, LLMUnavailable
from chatbi.llm.ollama import OllamaProvider

_FAST = {"first_token_timeout": 5.0, "total_timeout": 5.0}


def _ndjson(*pieces: str, done: bool = True) -> bytes:
    lines = [json.dumps({"response": p, "done": False}) for p in pieces]
    if done:
        lines.append(json.dumps({"response": "", "done": True}))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _provider(handler, **kwargs) -> OllamaProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OllamaProvider(base_url="http://x:11434", model="m", client=client, **kwargs)


@pytest.mark.asyncio
async def test_the_pieces_are_yielded_as_they_arrive() -> None:
    provider = _provider(lambda request: httpx.Response(200, content=_ndjson("select ", "1")))

    pieces = [p async for p in provider.stream("q", **_FAST)]

    assert pieces == ["select ", "1"], "空的 done 行不该产出一个空片段"


@pytest.mark.asyncio
async def test_the_request_carries_stream_keep_alive_and_zero_temperature() -> None:
    """三个字段各有理由（设计 §3.3）：stream 决定能不能边生成边显示；keep_alive 让模型
    常驻、避免 36s 冷启动反复落在用户头上；temperature=0 让同一个问题两次给同一条 SQL。
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=_ndjson("select 1"))

    provider = _provider(handler, keep_alive="1h")
    [p async for p in provider.stream("q", **_FAST)]

    assert seen["stream"] is True
    assert seen["keep_alive"] == "1h"
    assert seen["options"]["temperature"] == 0.0
    assert seen["prompt"] == "q"


@pytest.mark.asyncio
async def test_a_malformed_line_is_skipped_not_fatal() -> None:
    """Ollama 偶尔在流里插入空行或非 JSON。**为一行垃圾让整次生成失败是不成比例的**
    ——真正的失败由状态码与超时兜住。
    """
    body = b'{"response":"a","done":false}\n\n not json \n{"response":"b","done":true}\n'
    provider = _provider(lambda request: httpx.Response(200, content=body))

    assert [p async for p in provider.stream("q", **_FAST)] == ["a", "b"]


@pytest.mark.asyncio
async def test_a_slow_first_token_raises_the_first_token_kind() -> None:
    """**首 token 超时**。kind 必须是 first_token——它告诉运维「模型在加载或服务不可
    达」，而那与「模型跑飞了」要采取的行动完全不同。
    """

    async def slow_body():
        await asyncio.sleep(1.0)
        yield _ndjson("late")

    provider = _provider(lambda request: httpx.Response(200, content=slow_body()))

    with pytest.raises(LLMTimeout) as excinfo:
        [p async for p in provider.stream("q", first_token_timeout=0.05, total_timeout=5.0)]

    assert excinfo.value.kind == "first_token"


@pytest.mark.asyncio
async def test_a_runaway_generation_raises_the_total_kind() -> None:
    """**总时长超时**：首 token 很快，但之后一直吐。这是模型进入重复循环的形态。

    断言 kind == "total" 而不只是「抛了 LLMTimeout」：**一个把两种超时合成一个异常的
    实现也能让「抛了」通过**，而那正是设计 §3.2 要防的事。
    """

    async def endless():
        yield _ndjson("a", done=False)
        while True:
            await asyncio.sleep(0.02)
            yield _ndjson("a", done=False)

    provider = _provider(lambda request: httpx.Response(200, content=endless()))
    seen: list[str] = []

    with pytest.raises(LLMTimeout) as excinfo:
        async for piece in provider.stream("q", first_token_timeout=5.0, total_timeout=0.2):
            seen.append(piece)

    assert excinfo.value.kind == "total"
    assert seen, "超时前吐出的片段丢了——半截稿就无从谈起（设计 §9.3）"


@pytest.mark.asyncio
async def test_an_error_status_is_unavailable_without_the_address() -> None:
    provider = _provider(lambda request: httpx.Response(500, text="model not found: /root/.ollama"))

    with pytest.raises(LLMUnavailable) as excinfo:
        [p async for p in provider.stream("q", **_FAST)]

    assert "ollama" not in str(excinfo.value).lower(), "响应体进了消息——它可能带模型路径"
    assert "http" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_connection_failure_is_unavailable_without_the_address() -> None:
    """spec §4.4：地址端口进服务端日志、不进响应。httpx 的原始异常 str 里**有 url**，
    所以必须换成 LLMUnavailable 而不是直接往上抛。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("failed to connect", request=request)

    provider = _provider(handler)

    with pytest.raises(LLMUnavailable) as excinfo:
        [p async for p in provider.stream("q", **_FAST)]

    assert "x:11434" not in str(excinfo.value)


def test_ollama_is_the_default_provider() -> None:
    """默认配置要能造出 ollama（Task 2 的注册表只认识 fake，本任务补上）。"""
    from chatbi.config import Settings
    from chatbi.llm.registry import get_provider

    provider = get_provider(Settings(secret_key="s"))

    assert provider.name == "ollama"
    assert provider.model == "qwen3:8b"
