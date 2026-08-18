from fastapi import APIRouter

from chatbi.api.auth_router import router as auth_router

# 挂载顺序即声明顺序。新增 router 只改这一处——main.py 从此不随功能增长而变。
ALL_ROUTERS: tuple[APIRouter, ...] = (auth_router,)
