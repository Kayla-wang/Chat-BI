"""确定性的假 provider。**自动化测试一律用它**（上游 spec §5.1）。

三个旋钮覆盖五种要测的行为——旋钮比行为少是有意的，每个旋钮都对应一件真实会发生的事：

| 要测的路径 | 怎么配 |
|---|---|
| 正常出草稿 | `chunks=("select 1",)` |
| 首 token 超时 | `raises=LLMTimeout("first_token", 60)` |
| 吐了一半才超时 | `chunks=(...), raises_after=LLMTimeout("total", 180)` |
| 模型跑偏出垃圾 | `chunks=("这是一段说明文字，不是 SQL",)` |
| 服务不可用 | `raises=LLMUnavailable()` |

**缺 embed / chat 之类方法是故意的**（与 P2b、p3b1 的假驱动同形）：管线若调了协议之外
的方法，会以 AttributeError 暴露而不是静默走一条没设计过的路。

**不睡真实的时间**：超时行为用「直接抛 LLMTimeout」模拟。真的 await 一个 60 秒的 sleep
会让测试跑 60 秒，而超时**机制**本身该由 ollama.py 自己的测试守（Task 3 用
httpx.MockTransport）。这里要测的是「管线拿到 LLMTimeout 之后怎么办」。
"""

from collections.abc import AsyncIterator, Iterable

from chatbi.llm.base import LLMError


class FakeLLMProvider:
    name = "fake"

    def __init__(
        self,
        *,
        chunks: Iterable[str] = ("select 1",),
        model: str = "fake-model",
        raises: LLMError | None = None,
        raises_after: LLMError | None = None,
    ) -> None:
        self.model = model
        self._chunks = tuple(chunks)
        self._raises = raises
        self._raises_after = raises_after
        self.calls = 0
        self.prompts: list[str] = []
        """每次调用的 prompt 原文。测试靠它断言 prompt 里有什么、没有什么。"""

    async def stream(
        self, prompt: str, *, first_token_timeout: float, total_timeout: float
    ) -> AsyncIterator[str]:
        self.calls += 1
        self.prompts.append(prompt)
        if self._raises is not None:
            raise self._raises
        for chunk in self._chunks:
            yield chunk
        if self._raises_after is not None:
            raise self._raises_after
