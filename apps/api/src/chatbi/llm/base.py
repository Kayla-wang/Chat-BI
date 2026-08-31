"""LLMProvider 协议与它的三个失败。

**这一层是 async 的，与 P2b 的数据库驱动有意不同型**（P3c 设计 §3.1）。驱动是同步的、
由执行器包 to_thread，因为 psycopg / pymysql / clickhouse-connect 没有可用的 async
实现；而 LLM 就是一个 HTTP 接口，httpx 原生支持 async 流式读。这个差异买到两件事：

1. **省掉线程与事件循环之间的胶水。** 同步实现要把 token 从线程送回事件循环，得自己
   接一个 queue + 哨兵值，而那层胶水在取消时有真实的坑——p3b1 实测过「to_thread 的
   task 被 cancel 后线程会继续跑到底」。
2. **取消是免费的。** 生成器被取消 → httpx 关连接 → Ollama 自己停止生成。**不需要
   注册表、不需要另开一条连接发取消**——对比 execution/registry.py，那整个模块都是
   为了「掐掉库侧查询」而存在的。

**别把这一层「顺手统一成同步」**：那会把上面第 2 条免费的取消变成一个要重新造注册表
的问题。

只 import 标准库——与 drivers/base.py 同一条约定：协议层在没装 httpx 的环境里也能
import 成功，registry 的惰性加载依赖这一点。
"""

from collections.abc import AsyncIterator
from typing import Protocol


class LLMError(Exception):
    """LLM 层全部失败的共同基类。调用方用一个 except 兜住它。"""


class LLMTimeout(LLMError):
    """两个超时之一（设计 §3.2）。

    kind 区分它们，因为**两种失败的运维含义完全不同**：`first_token` 说明模型在加载
    或服务不可达（本机冷启动含模型加载实测 36s），`total` 说明模型在正常吐字但跑飞了
    （进入重复循环时会一直生成）。message 要能让人一眼分辨——出问题时运维手上往往
    只有这一句话。
    """

    def __init__(self, kind: str, seconds: float) -> None:
        if kind not in ("first_token", "total"):
            raise ValueError(f"kind 只能是 first_token 或 total，收到 {kind!r}")
        self.kind = kind
        self.seconds = seconds
        message = (
            f"模型未在 {seconds:g} 秒内响应"
            if kind == "first_token"
            else f"生成超过 {seconds:g} 秒已中止"
        )
        super().__init__(message)


class LLMUnavailable(LLMError):
    """连不上推理服务，或它返回了错误状态。

    **消息不带 base_url**：与 P2b 的 ConnectionFailed 同一条（spec §4.4，地址端口进
    服务端日志、不进响应）。它连一个能塞地址的入口都不给，这样「顺手把 url 拼进
    消息里」这件事做不到。
    """

    def __init__(self) -> None:
        super().__init__("模型服务不可用")


class LLMProvider(Protocol):
    """一次性的文本生成。**只有一个方法**——本段不需要对话历史、不需要函数调用。

    name / model 落进 runs.llm_provider 与 runs.llm_model（spec §4.6 要求每次 run 记下
    用了哪个模型，否则「同一个问题上周还能出对 SQL」这类问题无法排查）。
    """

    name: str
    model: str

    def stream(
        self, prompt: str, *, first_token_timeout: float, total_timeout: float
    ) -> AsyncIterator[str]:
        """流式吐出文本片段。**片段不保证是完整 token 或完整行**，调用方自己拼。

        两个超时都是**必传关键字参数**，不给默认值：与 P2b 驱动的 timeout_seconds 同
        一条约定——安全或体验相关的参数不要让调用方「忘了传就用一个隐含的默认」。

        抛 LLMTimeout（两种 kind）或 LLMUnavailable，不抛别的。
        """
        ...
