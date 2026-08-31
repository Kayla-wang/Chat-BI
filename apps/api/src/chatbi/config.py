from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。主密钥永不出现在 repr 或日志中（SecretStr 负责脱敏）。"""

    model_config = SettingsConfigDict(env_prefix="CHATBI_", extra="ignore")

    database_url: str = "postgresql+psycopg://chatbi:chatbi@localhost:5432/chatbi"
    secret_key: SecretStr | None = None
    secret_key_file: Path | None = None
    # 默认失败即安全：生产环境必须带 Secure。本地 HTTP 开发通过
    # CHATBI_COOKIE_SECURE=0 显式关闭。
    cookie_secure: bool = True
    session_ttl_hours: int = 12
    # spec §4.3 闸 4 与闸 3 的默认值，两者都「可配」。驱动的 execute() 仍然把它们
    # 作为显式参数接收，不自己读 get_settings()——驱动不该有隐式全局依赖，
    # 否则契约测要靠改环境变量才能测超时。
    query_timeout_seconds: int = 60
    max_result_rows: int = 1000
    # 预览上限，与 max_result_rows 是**两个不同的上限**（P3b 设计 §9.1）：
    #   max_result_rows(1000) 限制从库里取回多少行（闸 3 注入 LIMIT + 驱动 truncate）
    #   preview_rows(100)     限制存进 run_result_previews 与发给前端多少行
    # 一次执行可能取回 1000 行而只预览前 100 行，此时 row_count=1000、truncated=False。
    # 混用这两个数会让「已截断」的含义错掉（上游 spec §2.5、§3.5）。
    preview_rows: int = 100
    # ---- LLM（P3c 设计 §3.5、§5.2）----
    llm_provider: str = "ollama"
    llm_model: str = "qwen3:8b"
    llm_base_url: str = "http://127.0.0.1:11434"
    # **两个超时不是一个**（设计 §3.2）：上游 spec §4.5 的单一 30s 已被实测推翻。
    #   首 token 迟迟不来 = 模型在加载或服务不可达。本机冷启动含模型加载实测 36s，
    #     而模型被换出内存后还会再发生，所以给 60s。
    #   首 token 来了之后 = 模型在正常吐字只是慢（实测 4.1 tok/s），这时要管的是
    #     「别无限吐下去」（进入重复循环时会一直生成），180s 约容得下 700 token。
    # 单一超时无论取什么值都同时对这两件事说话：30s 则冷启动必然误报，180s 则
    # 「服务根本没起来」也要等 3 分钟才告诉用户。
    llm_first_token_timeout: float = 60.0
    llm_total_timeout: float = 180.0
    # 让模型常驻内存，避免 36s 冷启动反复落在用户头上。内存紧张的部署要能调小，
    # 所以它是配置而不是硬编码。
    llm_keep_alive: str = "30m"
    # prompt 的 token 预算（设计 §5.2）。超了就砍表，**并在 warnings 里写明砍了几张**
    # ——静默截断的表现是「SQL 是垃圾但没人知道为什么」。
    llm_prompt_token_budget: int = 6000

    @model_validator(mode="after")
    def _resolve_secret_key(self) -> "Settings":
        if self.secret_key is not None:
            return self
        if self.secret_key_file is None:
            raise ValueError("主密钥未配置：请设置 CHATBI_SECRET_KEY 或 CHATBI_SECRET_KEY_FILE")
        if not self.secret_key_file.is_file():
            raise ValueError(f"CHATBI_SECRET_KEY_FILE 指向的文件不存在：{self.secret_key_file}")
        text = self.secret_key_file.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError("CHATBI_SECRET_KEY_FILE 指向的文件为空")
        self.secret_key = SecretStr(text)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
