"""FastAPI 应用入口。

可通过 `uv run uvicorn web.backend.app:app` 启动，
HOST / PORT 等外部参数由环境变量提供（见 config.py）。
"""

from fastapi import FastAPI

from web.backend.routers import items
from web.backend.schemas.message import Message

app = FastAPI(title="HomeAgent Backend", version="0.1.0")

app.include_router(items.router)


@app.get("/health", response_model=Message)
def health() -> Message:
    """健康检查，供前端 / 前置代理探测。"""
    return Message(message="ok")


@app.get("/", response_model=Message)
def root() -> Message:
    """健康检查 / 欢迎信息。"""
    return Message(message="HomeAgent backend is running")
