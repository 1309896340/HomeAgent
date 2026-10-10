"""FastAPI 应用入口。

可通过 `uv run uvicorn web.backend.app:app` 启动，
HOST / PORT 等外部参数由环境变量提供（见 config.py）。
"""

from fastapi import FastAPI

import logging

# INFO 级可见（网段检测等启动日志走 homeagent.* logger）；httpx 每请求一条太吵，压回 WARNING
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

from web.backend.db import init_schema
from web.backend.routers import auth, chat, devices, items
from web.backend.services import lan_service

init_schema()
lan_service.detect_network()  # 启动时检测网段并以固定格式打印 console 日志
lan_service.find_nmap()  # 启动时检测 nmap（缺失仅 warning，端口扫描降级）

app = FastAPI(title="HomeAgent Backend", version="0.1.0")

app.include_router(auth.router)
app.include_router(auth.admin_router)
app.include_router(items.router)
app.include_router(chat.router)
app.include_router(devices.router)
# 消息图片由 chat.py 的受保护端点提供（/chat/uploads/{name}，需登录）


@app.get("/health", response_model=None)
def health():
    """健康检查，供前端 / 前置代理探测（保持开放，不要求登录）。"""
    return {"message": "ok"}


@app.get("/", response_model=None)
def root():
    """健康检查 / 欢迎信息。"""
    return {"message": "HomeAgent backend is running"}
