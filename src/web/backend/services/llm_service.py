"""LLM 流式调用服务（火山引擎 豆包，Responses API 协议 + 内置联网搜索）。

端点行为均为 2026-10-07 实测结论（scripts/verify_responses.py T1-T9，全部 PASS）：
- 系统提示走 instructions 参数；system/assistant/user 文本消息可直接作为
  input 项回放（T1）
- 正文增量: response.output_text.delta（delta 字段）；
  思考摘要增量: response.reasoning_summary_text.delta（delta 字段）；
  thinking.type = enabled/disabled 均被接受，不传默认开启思考（T2/T3）
- 流式以 data: [DONE] 终止；usage 在 response.completed 事件的
  response.usage（input_tokens / output_tokens / total_tokens）（T2）
- function 工具为扁平声明 {type:"function", name, description, parameters}；
  流式经 response.output_item.added（item 含 call_id/name）与
  response.function_call_arguments.delta 分片；结果回放用
  {type:"function_call", call_id, name, arguments} +
  {type:"function_call_output", call_id, output}（T6）
- web_search 为服务端工具 {type:"web_search"}：流式事件
  response.web_search_call.in_progress/searching/completed（query 在流中不可见）；
  搜索词与引用在 response.completed 的 output 里
  （web_search_call.action.query、message.content[].annotations[].url_citation）；
  usage.tool_usage.web_search 为计费计数（T7）
- web_search 与 function 工具可共存，模型按需选择（T8）
- 视觉：content 数组 {type:"input_text"} + {type:"input_image", image_url: "data:..."}
  （image_url 为字符串，不嵌套对象）（T4）
- 本机以外的外部服务调用走系统代理没问题（httpx 默认 trust_env=True）。
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

# 思考过程与正文之间可能出现空内容事件，读取超时给足余量即可；
# 开启联网搜索时单轮可达 90s（verify_responses T8 实测 83.8s）
LLM_TIMEOUT = httpx.Timeout(180.0, connect=10.0)

# 允许携带的图片类型与单张大小上限（与前端约束一致）
ALLOWED_IMAGE_MIMES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# 引用列表上限（url_citation 可能重复/过多，超出截断）
MAX_CITATIONS = 10


def build_system_prompt(skill_manifest: list[dict[str, str]]) -> str:
    """基础人设 + 技能清单（渐进式披露第一层：只有名称与简介常驻）。"""
    if not skill_manifest:
        return BASE_PROMPT
    lines = "\n".join(f"- {s['name']}: {s['description']}" for s in skill_manifest)
    return BASE_PROMPT + SKILL_PROMPT_TEMPLATE.format(lines=lines)


def build_llm_input(
    history: list[dict[str, Any]],
    content: str,
    images: list[str],
    skill_manifest: list[dict[str, str]] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """组装 (instructions, input_items)：全部文字历史 + 仅当前这条消息携带图片。

    history: [{"role": "user"|"assistant", "content": str}, ...]（不含本次）
    """
    items: list[dict[str, Any]] = [{"role": h["role"], "content": h["content"]} for h in history]
    if images:
        parts: list[dict[str, Any]] = [{"type": "input_text", "text": content or "（见图）"}]
        parts.extend({"type": "input_image", "image_url": url} for url in images)
        items.append({"role": "user", "content": parts})
    else:
        items.append({"role": "user", "content": content})
    return build_system_prompt(skill_manifest or []), items


async def stream_chat(
    instructions: str,
    input_items: list[dict[str, Any]],
    function_tools: list[dict[str, Any]] | None = None,
    web_search: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """流式调用 Responses API，产出统一事件：

    {"type": "thinking_delta"|"content_delta", "text": str}
    {"type": "usage", "prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
    {"type": "web_search", "query": str|None}          # 服务端发起搜索（流中查不到词）
    {"type": "web_result", "queries": [str], "citations": [{title,url,site_name}]}
                                                       # 本轮结束时一次性给出
    {"type": "tool_calls", "calls": [{"id", "name", "arguments"}]}  # function 工具

    连接失败 / 非 200 抛 LLMError；上游中断自然结束迭代。
    """
    body: dict[str, Any] = {
        "model": settings.llm.model,
        "instructions": instructions,
        "input": input_items,
        "stream": True,
        "thinking": {"type": "enabled"},
    }
    tools: list[dict[str, Any]] = []
    if web_search:
        tools.append({"type": "web_search"})
    if function_tools:
        tools.extend(function_tools)
    if tools:
        body["tools"] = tools
    headers = {"Authorization": f"Bearer {settings.llm.api_key}"}
    url = f"{settings.llm.base_url.rstrip('/')}/responses"

    # function_call 分片累积（T6 实测：call_id/name 随 output_item.added 下发一次，
    # arguments 为 JSON 字符串分片，按 output_index 对齐）
    fc_acc: dict[int, dict[str, str]] = {}
    search_queries: list[str] = []
    citations: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    def collect_web_result(resp: dict[str, Any]) -> None:
        """从 response.completed 的 output 提取搜索词与 url_citation 引用（T7）。"""
        for item in resp.get("output") or []:
            if item.get("type") == "web_search_call":
                q = (item.get("action") or {}).get("query")
                if q and q not in search_queries:
                    search_queries.append(q)
            elif item.get("type") == "message":
                for part in item.get("content") or []:
                    for a in part.get("annotations") or []:
                        if a.get("type") != "url_citation":
                            continue
                        u = a.get("url") or ""
                        if u and u not in seen_urls and len(citations) < MAX_CITATIONS:
                            seen_urls.add(u)
                            citations.append({
                                "title": a.get("title") or u,
                                "url": u,
                                "site_name": a.get("site_name") or "",
                            })

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
                        ev = json.loads(payload)
                    except ValueError:
                        continue
                    etype = ev.get("type", "")
                    if etype in ("response.failed", "response.error"):
                        err = (ev.get("response") or {}).get("error") or ev
                        raise LLMError(f"LLM 流内错误: {json.dumps(err, ensure_ascii=False)[:300]}")
                    elif etype == "response.output_text.delta":
                        if ev.get("delta"):
                            yield {"type": "content_delta", "text": ev["delta"]}
                    elif etype == "response.reasoning_summary_text.delta":
                        if ev.get("delta"):
                            yield {"type": "thinking_delta", "text": ev["delta"]}
                    elif etype == "response.output_item.added":
                        item = ev.get("item") or {}
                        if item.get("type") == "function_call":
                            fc_acc[ev.get("output_index", 0)] = {
                                "id": item.get("call_id") or "",
                                "name": item.get("name") or "",
                                "arguments": "",
                            }
                        elif item.get("type") == "web_search_call":
                            yield {"type": "web_search",
                                   "query": (item.get("action") or {}).get("query")}
                    elif etype == "response.function_call_arguments.delta":
                        acc = fc_acc.setdefault(
                            ev.get("output_index", 0), {"id": "", "name": "", "arguments": ""}
                        )
                        if ev.get("delta"):
                            acc["arguments"] += ev["delta"]
                    elif etype == "response.completed":
                        finished = ev.get("response") or {}
                        u = finished.get("usage") or {}
                        if u:
                            yield {
                                "type": "usage",
                                "prompt_tokens": u.get("input_tokens"),
                                "completion_tokens": u.get("output_tokens"),
                                "total_tokens": u.get("total_tokens"),
                            }
                        collect_web_result(finished)
        except httpx.HTTPError as e:
            raise LLMError(f"LLM 连接异常: {type(e).__name__}: {e}") from e

    if search_queries or citations:
        yield {"type": "web_result", "queries": search_queries, "citations": citations}
    if fc_acc:
        yield {"type": "tool_calls", "calls": [fc_acc[i] for i in sorted(fc_acc)]}


class LLMError(RuntimeError):
    """LLM 调用失败（网络/鉴权/上游拒绝）。"""
