"""LLM 流式调用服务（火山引擎 豆包，OpenAI 兼容协议）。

端点行为均为 2026-10-07 实测结论（scripts/verify_llm.py）：
- thinking.type = enabled/disabled，不传默认开启思考
- 思考内容在 delta.reasoning_content，正文在 delta.content
- usage 在流式最后 1-2 个 chunk，stream_options.include_usage 开启
- data: [DONE] 终止

本机以外的外部服务调用走系统代理没问题（httpx 默认 trust_env=True）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from web.backend.config import settings

SYSTEM_PROMPT = (
    "你是 HomeAgent，一个运行在用户家中的智能助手。"
    "回答用中文，简洁准确；涉及操作类请求时说明你目前只能对话，设备控制能力后续开放。"
)

# 思考过程与正文之间可能出现空内容 chunk，读取超时给足余量即可
LLM_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# 允许携带的图片类型与单张大小上限（与前端约束一致）
ALLOWED_IMAGE_MIMES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def build_llm_messages(
    history: list[dict[str, Any]],
    content: str,
    images: list[str],
) -> list[dict[str, Any]]:
    """组装上下文：全部文字历史 + 仅当前这条消息携带图片。

    history: [{"role": "user"|"assistant", "content": str}, ...]（不含本次）
    """
    msgs: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history:
        msgs.append({"role": h["role"], "content": h["content"]})
    if images:
        parts: list[dict[str, Any]] = [{"type": "text", "text": content or "（见图）"}]
        parts.extend({"type": "image_url", "image_url": {"url": url}} for url in images)
        msgs.append({"role": "user", "content": parts})
    else:
        msgs.append({"role": "user", "content": content})
    return msgs


async def stream_chat(messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    """流式调用 LLM，产出统一事件：

    {"type": "thinking_delta"|"content_delta", "text": str}
    {"type": "usage", "prompt_tokens": int, "completion_tokens": int, "total_tokens": int}

    连接失败 / 非 200 抛 LLMError；上游中断自然结束迭代。
    """
    body = {
        "model": settings.llm.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "thinking": {"type": "enabled"},
    }
    headers = {"Authorization": f"Bearer {settings.llm.api_key}"}
    url = f"{settings.llm.base_url.rstrip('/')}/chat/completions"

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        try:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    detail = (await resp.aread()).decode(errors="replace")[:300]
                    raise LLMError(f"LLM 服务返回 {resp.status_code}: {detail}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(payload)
                    except ValueError:
                        continue
                    if chunk.get("usage"):
                        u = chunk["usage"]
                        yield {
                            "type": "usage",
                            "prompt_tokens": u.get("prompt_tokens"),
                            "completion_tokens": u.get("completion_tokens"),
                            "total_tokens": u.get("total_tokens"),
                        }
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta") or {}
                        rc = delta.get("reasoning_content")
                        if rc:
                            yield {"type": "thinking_delta", "text": rc}
                        c = delta.get("content")
                        if c:
                            yield {"type": "content_delta", "text": c}
        except httpx.HTTPError as e:
            raise LLMError(f"LLM 连接异常: {type(e).__name__}: {e}") from e


class LLMError(RuntimeError):
    """LLM 调用失败（网络/鉴权/上游拒绝）。"""
