"""假 provider 的五种行为 + provider 选择（P3c 设计 §3.4、§3.5）。

无夹具：这一层不碰库、不碰 HTTP。
"""

import pytest

from chatbi.config import Settings
from chatbi.llm.base import LLMTimeout, LLMUnavailable
from chatbi.llm.fake import FakeLLMProvider
from chatbi.llm.registry import get_provider

_TIMEOUTS = {"first_token_timeout": 1.0, "total_timeout": 2.0}


async def _collect(provider: FakeLLMProvider) -> str:
    return "".join([chunk async for chunk in provider.stream("p", **_TIMEOUTS)])


@pytest.mark.asyncio
async def test_the_fake_yields_its_chunks_in_order() -> None:
    provider = FakeLLMProvider(chunks=("select ", "city ", "from t"))

    assert await _collect(provider) == "select city from t"
    assert provider.calls == 1
    assert provider.prompts == ["p"]


@pytest.mark.asyncio
async def test_the_fake_can_fail_before_the_first_chunk() -> None:
    """首 token 超时：一个 token 都没吐出来。管线在这条路径上不该产出任何草稿。"""
    provider = FakeLLMProvider(raises=LLMTimeout("first_token", 60))

    with pytest.raises(LLMTimeout) as excinfo:
        await _collect(provider)

    assert excinfo.value.kind == "first_token"
    assert "60" in str(excinfo.value)


@pytest.mark.asyncio
async def test_the_fake_can_fail_after_some_chunks() -> None:
    """**吐了一半才超时**——这是最难处理的一条路径（设计 §9.3：半截稿不落库但前端
    不清空）。收到的片段必须能被调用方看见，异常也必须真的抛出来。
    """
    provider = FakeLLMProvider(
        chunks=("select ", "pg_sleep("), raises_after=LLMTimeout("total", 180)
    )
    seen: list[str] = []

    with pytest.raises(LLMTimeout) as excinfo:
        async for chunk in provider.stream("p", **_TIMEOUTS):
            seen.append(chunk)

    assert seen == ["select ", "pg_sleep("], "超时前吐出的片段丢了——半截稿就无从谈起"
    assert excinfo.value.kind == "total"


@pytest.mark.asyncio
async def test_the_fake_can_be_unavailable() -> None:
    provider = FakeLLMProvider(raises=LLMUnavailable())

    with pytest.raises(LLMUnavailable):
        await _collect(provider)


def test_the_timeout_kind_is_validated() -> None:
    """kind 打错字时立刻炸，而不是产出一句意义不明的 message。"""
    with pytest.raises(ValueError):
        LLMTimeout("firsttoken", 60)


def test_the_unavailable_message_does_not_leak_the_address() -> None:
    """spec §4.4：地址端口进服务端日志、不进响应。**LLMUnavailable 连参数都不收**，
    所以「顺手把 url 拼进消息」这件事做不到。
    """
    assert "http" not in str(LLMUnavailable())


def test_the_provider_is_chosen_by_configuration() -> None:
    """**这条就是「可插拔」的证据**（设计 §3.5）：换一个配置值就换一个实现，不需要
    改任何调用方。
    """
    settings = Settings(secret_key="s", llm_provider="fake", llm_model="m")

    provider = get_provider(settings)

    assert provider.name == "fake"
    assert provider.model == "m"


def test_an_unknown_provider_is_a_clear_error() -> None:
    """错字要指向配置，而不是在第一次调用时以 AttributeError 出现在管线里。"""
    settings = Settings(secret_key="s", llm_provider="ollam")

    with pytest.raises(ValueError, match="ollam"):
        get_provider(settings)
