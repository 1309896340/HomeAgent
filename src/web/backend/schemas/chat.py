"""对话模块的请求/响应模型。"""

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = "新对话"


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class MessageCreate(BaseModel):
    content: str = ""
    images: list[str] = Field(default_factory=list, description="data URL 形式的图片，最多 4 张")


class SessionOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    thinking: str | None = None
    images: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    status: str
    created_at: str
