"""对话模块的请求/响应模型。"""

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = "新对话"


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class MessageCreate(BaseModel):
    content: str = ""
    images: list[str] = Field(default_factory=list, description="data URL 形式的图片，最多 4 张")
    web_search: bool = Field(default=False, description="本条消息是否启用联网搜索")


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
    citations: list[dict] = Field(default_factory=list, description="联网搜索引用（assistant 消息）")
    web_search: bool = Field(default=False, description="发送时是否启用联网搜索（user 消息）")
    duration_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    status: str
    created_at: str
