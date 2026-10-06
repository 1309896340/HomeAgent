"""FastAPI 应用入口。

可通过 `uv run uvicorn web.backend.app:app` 启动，
HOST / PORT 等外部参数由环境变量提供（见 config.py）。
"""

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from web.backend.config import settings
from web.backend.db import init_schema
from web.backend.routers import chat, items
from web.backend.schemas.message import Message

init_schema()

app = FastAPI(title="HomeAgent Backend", version="0.1.0")

app.include_router(items.router)
app.include_router(chat.router)

# 消息图片静态服务（db/uploads/ 下的落盘文件）
# 前端经反向代理访问 /api/chat/uploads/xxx，代理剥掉 /api 前缀后命中此挂载
app.mount(
    "/chat/uploads",
    StaticFiles(directory=settings.db_dir / "uploads"),
    name="chat-uploads",
)


@app.get("/health", response_model=Message)
def health() -> Message:
    """健康检查，供前端 / 前置代理探测。"""
    return Message(message="ok")


@app.get("/", response_model=Message)
def root() -> Message:
    """健康检查 / 欢迎信息。"""
    return Message(message="HomeAgent backend is running")
