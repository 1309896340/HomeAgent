"""简单的消息 schema 示例。"""

from pydantic import BaseModel


class Message(BaseModel):
    """通用消息响应体，如 {"message": "..."}。"""

    message: str
