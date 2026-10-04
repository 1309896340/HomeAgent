"""路由层示例：/items 相关 endpoint。

routers 只负责 HTTP 协议适配（解析请求 schema、调用 services、返回响应 schema），
不包含业务逻辑。
"""

from fastapi import APIRouter

from web.backend.schemas.item import ItemCreate, ItemOut
from web.backend.services import item_service

router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=list[ItemOut])
def list_items() -> list[ItemOut]:
    """列出全部条目。"""
    return item_service.list_items()


@router.post("", response_model=ItemOut, status_code=201)
def create_item(payload: ItemCreate) -> ItemOut:
    """创建条目。"""
    return item_service.create_item(payload)
