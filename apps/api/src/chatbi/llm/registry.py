"""name → provider。与 datasources/registry.py 同形（惰性 import）。

**「可插拔」的证据是这个文件加一条测试**（设计 §1.2、§3.5）。上游 spec §1.2 还列了
openai_compatible.py，本份**不做**：本机没有 OpenAI 兼容端点可验，而一份跑不过的
provider 比没有更糟——它会让「可插拔」看起来已经被证明。要接云端 LLM 时再加，那时有
端点可验。这一处偏离记在 P3c 设计 §12。
"""

from chatbi.config import Settings
from chatbi.llm.base import LLMProvider


def get_provider(settings: Settings) -> LLMProvider:
    """按配置造一个 provider。

    **settings 是显式参数不是 get_settings()**：测试要能喂不同配置而不动环境变量，
    与 P2b 驱动的 timeout_seconds、P3a guard 的 max_rows 同一条约定。

    惰性 import：`llm/base.py` 只 import 标准库，所以在没装 httpx 的环境里 import 本
    模块也不会炸——只有真的要 ollama 时才会碰 httpx。
    """
    if settings.llm_provider == "fake":
        from chatbi.llm.fake import FakeLLMProvider

        return FakeLLMProvider(model=settings.llm_model)
    # Task 3 在这里加 ollama 分支。**在那之前默认配置会走到下面那行 ValueError**，
    # 这是有意的：本份分任务提交，一个只认识 fake 的注册表比一个 import 不存在模块的
    # 注册表更容易定位问题。
    raise ValueError(f"未知的 LLM provider：{settings.llm_provider}")
