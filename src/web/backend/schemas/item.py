"""Pydantic 请求体 / 响应体 schema 示例。"""

from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    """POST /items 的请求体。"""

    name: str = Field(..., min_length=1, max_length=64, examples=["apple"])
    description: str | None = Field(None, max_length=256)


class ItemOut(BaseModel):
    """GET /items 的响应体。"""

    id: int
    name: str
    description: str | None = None
