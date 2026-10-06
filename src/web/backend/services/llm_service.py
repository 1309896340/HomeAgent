"""LLM 流式调用服务（火山引擎 豆包，OpenAI 兼容协议）。

端点行为均为 2026-10-07 实测结论（scripts/verify_llm.py T1-T6）：
- thinking.type = enabled/disabled，不传默认开启思考
- 思考内容在 delta.reasoning_content，正文在 delta.content
- usage 在流式最后 1-2 个 chunk，stream_options.include_usage 开启
- data: [DONE] 终止
- 工具调用：delta.tool_calls[].{index,id,function.name,function.arguments}
  分片拼接；工具轮 finish_reason=tool_calls 且 content 为空；
  role:"tool" 回填后二轮正常；每轮请求各带一份 usage（多轮需累加）

本机以外的外部服务调用走系统代理没问题（httpx 默认 trust_env=True）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from web.backend.config import settings

BASE_PROMPT = (
    "你是 HomeAgent，一个运行在用户家中的智能助手。回答用中文，简洁准确。"
)

SKILL_PROMPT_TEMPLATE = """

## 可用技能（仅名称与简介）
{lines}

当对话涉及上述技能领域时，先调用 read_skill 工具获取该技能的完整说明，再严格按说明行动（工具/数据规则以技能说明为准）。
"""

# 思考过程与正文之间可能出现空内容 chunk，读取超时给足余量即可
LLM_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# 允许携带的图片类型与单张大小上限（与前端约束一致）
ALLOWED_IMAGE_MIMES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def build_system_prompt(skill_manifest: list[dict[str, str]]) -> str:
    """基础人设 + 技能清单（渐进式披露第一层：只有名称与简介常驻）。"""
    if not skill_manifest:
        return BASE_PROMPT
    lines = "\n".join(f"- {s['name']}: {s['description']}" for s in skill_manifest)
    return BASE_PROMPT + SKILL_PROMPT_TEMPLATE.format(lines=lines)


def build_llm_messages(
    history: list[dict[str, Any]],
    content: str,
    images: list[str],
    skill_manifest: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """组装上下文：全部文字历史 + 仅当前这条消息携带图片。

    history: [{"role": "user"|"assistant", "content": str}, ...]（不含本次）
    """
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(skill_manifest or [])}
    ]
    for h in history:
        msgs.append({"role": h["role"], "content": h["content"]})
    if images:
        parts: list[dict[str, Any]] = [{"type": "text", "text": content or "（见图）"}]
        parts.extend({"type": "image_url", "image_url": {"url": url}} for url in images)
        msgs.append({"role": "user", "content": parts})
    else:
        msgs.append({"role": "user", "content": content})
    return msgs


async def stream_chat(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
) -> AsyncIterator[dict[str, Any]]:
    """流式调用 LLM，产出统一事件：

    {"type": "thinking_delta"|"content_delta", "text": str}
    {"type": "usage", "prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
    {"type": "tool_calls", "calls": [{"id", "name", "arguments"}]}   # 流结束后一次性给出

    连接失败 / 非 200 抛 LLMError；上游中断自然结束迭代。
    """
    body: dict[str, Any] = {
        "model": settings.llm.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "thinking": {"type": "enabled"},
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    headers = {"Authorization": f"Bearer {settings.llm.api_key}"}
    url = f"{settings.llm.base_url.rstrip('/')}/chat/completions"

    # tool_calls 分片累积（T6 实测：arguments 为 JSON 字符串分片，id 下发一次）
    tc_acc: dict[int, dict[str, str]] = {}

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
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            acc = tc_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            if tc.get("id"):
                                acc["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                acc["name"] += fn["name"]
                            if fn.get("arguments"):
                                acc["arguments"] += fn["arguments"]
        except httpx.HTTPError as e:
            raise LLMError(f"LLM 连接异常: {type(e).__name__}: {e}") from e

    if tc_acc:
        yield {"type": "tool_calls", "calls": [tc_acc[i] for i in sorted(tc_acc)]}


class LLMError(RuntimeError):
    """LLM 调用失败（网络/鉴权/上游拒绝）。"""
