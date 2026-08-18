"""demo_sales example schema

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_TABLES = """
create schema if not exists demo_sales;

create table demo_sales.customers (
    id integer primary key,
    name text not null,
    city text not null,
    segment text not null
);
comment on table demo_sales.customers is '客户';
comment on column demo_sales.customers.id is '客户 ID';
comment on column demo_sales.customers.name is '客户名称';
comment on column demo_sales.customers.city is '所在城市';
comment on column demo_sales.customers.segment is '客户分层：企业 / 中小 / 个人';

create table demo_sales.products (
    id integer primary key,
    name text not null,
    category text not null,
    unit_price numeric(12, 2) not null
);
comment on table demo_sales.products is '商品';
comment on column demo_sales.products.id is '商品 ID';
comment on column demo_sales.products.name is '商品名称';
comment on column demo_sales.products.category is '商品类目';
comment on column demo_sales.products.unit_price is '单价（元）';

create table demo_sales.orders (
    id integer primary key,
    customer_id integer not null references demo_sales.customers(id),
    product_id integer not null references demo_sales.products(id),
    quantity integer not null,
    amount numeric(12, 2) not null,
    ordered_at timestamptz not null
);
comment on table demo_sales.orders is '订单';
comment on column demo_sales.orders.id is '订单 ID';
comment on column demo_sales.orders.customer_id is '客户 ID';
comment on column demo_sales.orders.product_id is '商品 ID';
comment on column demo_sales.orders.quantity is '数量';
comment on column demo_sales.orders.amount is '订单金额（元）= 数量 × 单价';
comment on column demo_sales.orders.ordered_at is '下单时间';
"""

# 用 generate_series 造数而不是写几百行 INSERT：migration 文件要能被读完。
# 金额与数量用确定性表达式，不用 random()——随机数会让「示例库的截图和文档对不上」，
# 也会让基于示例库的测试无法断言具体数值。
#
# 步长 12 小时：240 行跨约 120 天（2026-01-01 起，覆盖 4 个月份）。计划原写 7 小时，
# 那只跨 70 天恰好 3 个月份，刚好卡在 months >= 3 的边界上没有余量。
_SEED = """
insert into demo_sales.customers (id, name, city, segment)
select i,
       '客户' || i,
       (array['北京', '上海', '广州', '深圳', '成都'])[1 + (i % 5)],
       (array['企业', '中小', '个人'])[1 + (i % 3)]
from generate_series(1, 20) as i;

insert into demo_sales.products (id, name, category, unit_price)
select i,
       '商品' || i,
       (array['硬件', '软件', '服务'])[1 + (i % 3)],
       (100 + i * 37 % 900)::numeric(12, 2)
from generate_series(1, 12) as i;

insert into demo_sales.orders (id, customer_id, product_id, quantity, amount, ordered_at)
select i,
       1 + (i % 20),
       1 + (i % 12),
       1 + (i % 5),
       ((1 + (i % 5)) * (100 + (1 + (i % 12)) * 37 % 900))::numeric(12, 2),
       timestamptz '2026-01-01 09:00:00+08' + (i * interval '12 hours')
from generate_series(1, 240) as i;
"""


def upgrade() -> None:
    op.execute(_TABLES)
    op.execute(_SEED)


def downgrade() -> None:
    # 角色不在这里删——它是 seed-demo 建的，而且是集群级对象，
    # 一个库的 downgrade 去删集群级角色会影响同集群的其他库。
    op.execute("drop schema if exists demo_sales cascade")
