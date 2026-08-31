"""run 的 generating 状态

Revision ID: 0006
Revises: 0005

草稿生成期间的状态（P3c 设计 §7）。加它而不是复用现有状态的三条理由：
状态机诚实（被断开的问答流能记成 generating -> cancelled）· 免费收紧执行入口
（P3b 的「非 drafted 一律 409」自动拦住「草稿还在流就点运行」）· P3d 的历史列表
需要它才能正确渲染。

CHECK 用字面量而不是引用 db.models.RUN_STATUSES —— migration 是历史快照，不该在
将来因为那个常量被改而改变含义（与 0005 同一条约定）。两者一致由
tests/test_run_models.py 钉住。
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_OLD = "status in ('drafted','blocked','running','succeeded','failed','cancelled')"
_NEW = "status in ('generating','drafted','blocked','running','succeeded','failed','cancelled')"


def upgrade() -> None:
    op.drop_constraint("ck_runs_status", "runs", type_="check")
    op.create_check_constraint("ck_runs_status", "runs", _NEW)


def downgrade() -> None:
    # 先把 generating 的行清成 failed，否则旧 CHECK 建不上去。
    # 语义是对的：一条停在 generating 的 run 没有草稿，回退后它确实是失败的。
    op.execute(sa.text("update runs set status = 'failed' where status = 'generating'"))
    op.drop_constraint("ck_runs_status", "runs", type_="check")
    op.create_check_constraint("ck_runs_status", "runs", _OLD)
