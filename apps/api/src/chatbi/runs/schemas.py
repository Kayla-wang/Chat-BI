"""run 的请求/响应模型。

P3c 会往这里加问答流的请求、P3d 加历史与回放的响应。放在 runs/ 而不是
datasources/schemas.py：那个文件已经装了数据源、schema 元数据、SQL 校验三类模型
（12 个类），再加会让「这个文件装什么」说不清。
"""

from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)
    """**编辑器当前内容，不是草稿**（上游 spec §2.3）。服务端把它记为 run.final_sql，
    与 run.generated_sql（LLM 原始版）构成 F-302 AC2 diff 的两侧。

    上限与 /sql/validate 的 SqlValidateRequest 一致（100k 字符）。
    """
