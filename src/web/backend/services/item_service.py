"""业务逻辑层示例。

services 层封装业务规则与（未来的）数据库读写，
routers 层只做参数校验和调用，不直接操作数据。
"""

from web.backend.schemas.item import ItemCreate, ItemOut

# 内存中的假数据源，模拟数据库；接入真实 DB 后由 models 层替换。
_FAKE_ITEMS: dict[int, ItemOut] = {
    1: ItemOut(id=1, name="apple", description="a fruit"),
}
_NEXT_ID = 2


def list_items() -> list[ItemOut]:
    """返回全部条目。"""
    return list(_FAKE_ITEMS.values())


def create_item(payload: ItemCreate) -> ItemOut:
    """根据请求体创建条目并返回。"""
    global _NEXT_ID
    item = ItemOut(id=_NEXT_ID, name=payload.name, description=payload.description)
    _NEXT_ID += 1
    _FAKE_ITEMS[item.id] = item
    return item
