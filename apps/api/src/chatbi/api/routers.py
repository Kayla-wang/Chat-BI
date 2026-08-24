from fastapi import APIRouter

from chatbi.api.auth_router import router as auth_router
from chatbi.api.datasource_router import router as datasource_router
from chatbi.api.run_router import router as run_router
from chatbi.api.schema_router import router as schema_router
from chatbi.api.sql_router import router as sql_router
from chatbi.api.user_router import router as user_router

# 挂载顺序即声明顺序。新增 router 只改这一处——main.py 从此不随功能增长而变。
#
# schema_router 与 datasource_router 同 prefix，但路径多一段（/{id}/schema），不会
# 与 /{datasource_id} 抢匹配——与 grants 路由同一个情形，声明顺序无所谓。放在后面
# 只是让「先 CRUD 再元数据」的阅读顺序与功能层次一致。
ALL_ROUTERS: tuple[APIRouter, ...] = (
    auth_router,
    datasource_router,
    run_router,
    schema_router,
    sql_router,
    user_router,
)
