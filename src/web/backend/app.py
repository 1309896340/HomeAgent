"""FastAPI 应用入口。

可通过 `uv run uvicorn web.backend.app:app` 启动，
HOST / PORT 等外部参数由环境变量提供（见 config.py）。
"""

from fastapi import FastAPI

from web.backend.db import init_schema
from web.backend.routers import auth, chat, items

init_schema()

app = FastAPI(title="HomeAgent Backend", version="0.1.0")

app.include_router(auth.router)
app.include_router(auth.admin_router)
app.include_router(items.router)
app.include_router(chat.router)
# 消息图片由 chat.py 的受保护端点提供（/chat/uploads/{name}，需登录）


@app.get("/health", response_model=None)
def health():
    """健康检查，供前端 / 前置代理探测（保持开放，不要求登录）。"""
    return {"message": "ok"}


@app.get("/", response_model=None)
def root():
    """健康检查 / 欢迎信息。"""
    return {"message": "HomeAgent backend is running"}
