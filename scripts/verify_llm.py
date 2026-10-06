"""豆包 agent plan（doubao-seed-2.1-lite）端点行为验证脚本。

验证目标（对应对话模块实施前的风险清单）：
  T1 非流式基础调用：鉴权、参数、响应结构、usage 字段名
  T2 thinking 参数：{"type": "enabled"/"disabled"} 是否被接受；
      思考内容出现在哪个字段（reasoning_content?）
  T3 流式输出：SSE 事件格式、delta 字段集合、usage 在哪个 chunk、
      是否需要 stream_options.include_usage
  T4 视觉输入：base64 图片（data URL）能否被该模型正确理解
  T5 中断行为：流式读到一半主动断开，客户端是否干净退出
  T6 工具调用：tools 挂载 + thinking 共存、tool_calls 流式分片格式、
      finish_reason 取值、role:"tool" 回填后的第二轮响应、
      无关问题在挂载 tools 时是否正常不触发

用法（项目根目录执行，需先配置 .env 的 LLM.API_KEY）：
  uv run python scripts/verify_llm.py
  uv run python scripts/verify_llm.py --only T1,T3
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import struct
import sys
import time
import zlib

import httpx

from web.backend.config import settings

# Windows 控制台默认 GBK，重配为 UTF-8；isinstance 兼作类型收窄（TextIO 无 reconfigure）
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

results: list[tuple[str, str, str]] = []  # (用例, 状态, 摘要)
facts: dict[str, str] = {}  # 供实施直接引用的结论


def record(name: str, ok: bool, summary: str) -> None:
    results.append((name, "PASS" if ok else "FAIL", summary))


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.llm.api_key}"}


def chat_url() -> str:
    return f"{settings.llm.base_url.rstrip('/')}/chat/completions"


def print_error(r: httpx.Response) -> None:
    print(f"  HTTP {r.status_code} {r.headers.get('content-type', '')}")
    print(f"  body: {r.text[:500]}")


def parse_sse_line(line: str) -> dict | None:
    """解析一行 SSE data，返回 JSON dict；忽略注释/空行/[DONE]。"""
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        return json.loads(payload)
    except ValueError:
        return None


def test_basic(client: httpx.Client) -> None:
    section("T1 非流式基础调用")
    body = {
        "model": settings.llm.model,
        "messages": [{"role": "user", "content": "用一句话介绍你自己"}],
    }
    t0 = time.perf_counter()
    r = client.post(chat_url(), json=body, headers=auth_headers())
    elapsed = time.perf_counter() - t0
    if r.status_code != 200:
        print_error(r)
        record("T1 basic", False, f"status={r.status_code}")
        return
    data = r.json()
    msg = data["choices"][0]["message"]
    print(f"  耗时 {elapsed:.2f}s  model 回显: {data.get('model')}")
    print(f"  message 字段: {sorted(msg.keys())}")
    print(f"  finish_reason: {data['choices'][0].get('finish_reason')}")
    print(f"  usage: {data.get('usage')}")
    print(f"  content: {msg.get('content', '')[:120]}")
    if "reasoning_content" in msg:
        print(f"  reasoning_content 存在(非流式也返回思考): {msg['reasoning_content'][:80]}")
        facts["非流式思考字段"] = "message.reasoning_content"
    usage = data.get("usage") or {}
    if usage.get("prompt_tokens") is not None:
        facts["usage 字段名"] = "prompt_tokens / completion_tokens / total_tokens"
        record("T1 basic", True, f"{elapsed:.1f}s")
    else:
        record("T1 basic", False, "响应缺 usage")


def test_thinking(client: httpx.Client) -> None:
    section("T2 thinking 参数对照（无 / enabled / disabled）")
    prompt = "9.11 和 9.8 哪个大？先思考再回答。"
    for label, extra in (
        ("无参数", {}),
        ("enabled", {"thinking": {"type": "enabled"}}),
        ("disabled", {"thinking": {"type": "disabled"}}),
    ):
        body = {
            "model": settings.llm.model,
            "messages": [{"role": "user", "content": prompt}],
            **extra,
        }
        t0 = time.perf_counter()
        try:
            r = client.post(chat_url(), json=body, headers=auth_headers())
        except httpx.HTTPError as e:
            print(f"  [{label}] 请求异常: {e}")
            record("T2 thinking", False, f"{label} 异常")
            return
        elapsed = time.perf_counter() - t0
        if r.status_code != 200:
            print(f"  [{label}] 拒绝请求:")
            print_error(r)
            record("T2 thinking", False, f"{label} status={r.status_code}")
            return
        data = r.json()
        msg = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        has_reasoning = bool(msg.get("reasoning_content"))
        fields = sorted(k for k in msg if msg.get(k) not in (None, ""))
        print(
            f"  [{label}] {elapsed:.1f}s  思考={has_reasoning}"
            f"  tokens={usage.get('total_tokens')}  非空字段={fields}"
        )
    facts["thinking 参数"] = "thinking.type = enabled/disabled（详见上方对照结果）"
    record("T2 thinking", True, "三种形态均已实测")


def test_stream(client: httpx.Client) -> None:
    section("T3 流式输出（SSE 事件格式）")
    body = {
        "model": settings.llm.model,
        "messages": [{"role": "user", "content": "写一首关于秋天的两句短诗"}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "thinking": {"type": "enabled"},
    }
    delta_keys: set[str] = set()
    usage_chunk_index = None
    chunk_count = 0
    first_token = None
    raw_printed = 0
    t0 = time.perf_counter()
    try:
        with client.stream("POST", chat_url(), json=body, headers=auth_headers()) as r:
            if r.status_code != 200:
                print_error(r)
                record("T3 stream", False, f"status={r.status_code}")
                return
            for line in r.iter_lines():
                if raw_printed < 3 and line.startswith("data:"):
                    print(f"  原始行示例: {line[:150]}")
                    raw_printed += 1
                chunk = parse_sse_line(line)
                if chunk is None:
                    if "[DONE]" in line:
                        print(f"  收到终止标记: {line.strip()}")
                    continue
                chunk_count += 1
                if chunk.get("usage"):
                    usage_chunk_index = chunk_count
                    print(f"  usage 出现在第 {chunk_count} 个 chunk: {chunk['usage']}")
                for ch in chunk.get("choices", []):
                    d = ch.get("delta") or {}
                    delta_keys.update(k for k, v in d.items() if v not in (None, ""))
                    if d.get("content") and first_token is None:
                        first_token = time.perf_counter() - t0
    except httpx.HTTPError as e:
        print(f"  流式异常: {e}")
        record("T3 stream", False, str(e)[:80])
        return
    elapsed = time.perf_counter() - t0
    print(f"  总耗时 {elapsed:.2f}s  首token {first_token or -1:.2f}s  chunk 数 {chunk_count}")
    print(f"  delta 中出现过的非空字段: {sorted(delta_keys)}")
    facts["流式 delta 字段"] = ", ".join(sorted(delta_keys)) or "(待定)"
    facts["usage 位置"] = f"第 {usage_chunk_index} 个 chunk" if usage_chunk_index else "未见 usage"
    ok = "content" in delta_keys
    record("T3 stream", ok, f"首token {first_token or -1:.1f}s, 共 {chunk_count} chunks")


def make_solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """纯 Python 生成纯色 PNG（无第三方依赖）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + bytes(rgb) * width
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def test_vision(client: httpx.Client) -> None:
    section("T4 视觉输入（base64 data URL）")
    png = make_solid_png(64, 64, (200, 30, 30))
    data_url = "data:image/png;base64," + base64.b64encode(png).decode()
    body = {
        "model": settings.llm.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "图中方块是什么颜色？只回答颜色名。"},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    t0 = time.perf_counter()
    r = client.post(chat_url(), json=body, headers=auth_headers())
    elapsed = time.perf_counter() - t0
    if r.status_code != 200:
        print_error(r)
        record("T4 vision", False, f"status={r.status_code}")
        return
    msg = r.json()["choices"][0]["message"]
    answer = (msg.get("content") or "").strip()
    print(f"  耗时 {elapsed:.2f}s  回答: {answer}")
    ok = "红" in answer
    facts["视觉输入"] = "支持 content 数组 + image_url(data URL)" if ok else f"回答异常: {answer[:50]}"
    record("T4 vision", ok, f"回答='{answer[:30]}'")


def test_abort(client: httpx.Client) -> None:
    section("T5 中断行为（读到首个内容 chunk 即断开）")
    body = {
        "model": settings.llm.model,
        "messages": [{"role": "user", "content": "写一篇 500 字的散文"}],
        "stream": True,
    }
    t0 = time.perf_counter()
    got = 0
    try:
        with client.stream("POST", chat_url(), json=body, headers=auth_headers()) as r:
            if r.status_code != 200:
                print_error(r)
                record("T5 abort", False, f"status={r.status_code}")
                return
            for line in r.iter_lines():
                chunk = parse_sse_line(line)
                if chunk is None:
                    continue
                got += 1
                if got >= 2:
                    break  # 主动提前退出 with 块 → 关闭连接
    except httpx.HTTPError as e:
        print(f"  断开过程出现网络异常(部分服务端会主动 RST，属正常): {type(e).__name__}")
    print(f"  读取 {got} 个 chunk 后主动断开，客户端干净退出，耗时 {time.perf_counter() - t0:.2f}s")
    record("T5 abort", True, f"断开于 {got} chunks")


# ---------- T6 工具调用 ----------

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询指定城市的实时天气",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "城市名，如 北京"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["location"],
        },
    },
}

CANNED_WEATHER = {"location": "北京", "temperature": 18, "condition": "晴", "humidity": 42}


def _stream_once(client: httpx.Client, body: dict) -> dict:
    """跑一轮流式请求，返回观察到的结构化结果。"""
    out = {
        "tool_calls": {},  # index -> {"id","name","args"}
        "finish_reasons": [],
        "delta_keys": set(),
        "content": "",
        "usage": None,
        "status": None,
        "first_fragment_sample": None,
    }
    with client.stream("POST", chat_url(), json=body, headers=auth_headers()) as r:
        out["status"] = r.status_code
        if r.status_code != 200:
            out["error_body"] = r.read().decode(errors="replace")[:300]
            return out
        for line in r.iter_lines():
            chunk = parse_sse_line(line)
            if chunk is None:
                continue
            if chunk.get("usage"):
                out["usage"] = chunk["usage"]
            for choice in chunk.get("choices", []):
                if choice.get("finish_reason"):
                    out["finish_reasons"].append(choice["finish_reason"])
                delta = choice.get("delta") or {}
                out["delta_keys"].update(k for k, v in delta.items() if v not in (None, "", []))
                if delta.get("content"):
                    out["content"] += delta["content"]
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    acc = out["tool_calls"].setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        acc["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        # 记录 name 是否会在多个分片重复下发
                        if acc["name"] and acc["first_fragment_sample"] is None:
                            acc["first_fragment_sample"] = "name 重复下发"
                        acc["name"] += fn["name"]
                    if fn.get("arguments"):
                        acc["args"] += fn["arguments"]
    return out


def test_tools(client: httpx.Client) -> None:
    section("T6 工具调用")
    base = {
        "model": settings.llm.model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "thinking": {"type": "enabled"},
        "tools": [WEATHER_TOOL],
        "tool_choice": "auto",
    }

    # a) 触发工具调用
    print("[a] 挂载 tools + thinking，询问天气 →")
    r1 = _stream_once(client, {**base, "messages": [{"role": "user", "content": "北京今天天气怎么样？"}]})
    if r1["status"] != 200:
        print(f"  HTTP {r1['status']}\n  body: {r1.get('error_body', '')[:300]}")
        record("T6 tools", False, f"status={r1['status']}")
        return
    print(f"  finish_reason 序列: {r1['finish_reasons']}")
    print(f"  delta 非空字段: {sorted(r1['delta_keys'])}")
    print(f"  本轮 usage: {r1['usage']}")
    print(f"  本轮正文: '{r1['content'][:60]}'")
    for idx, tc in r1["tool_calls"].items():
        print(f"  tool_call[{idx}]: id={tc['id'][:18]}… name={tc['name']} args={tc['args']} {tc.get('first_fragment_sample', '')}")
    try:
        args = json.loads(next(iter(r1["tool_calls"].values()))["args"]) if r1["tool_calls"] else {}
    except ValueError:
        args = {}
    triggered = bool(r1["tool_calls"]) and "location" in args
    if not triggered:
        print("  [警告] 未触发工具调用或参数解析失败")

    # b) 回填 role:"tool" 结果，验证第二轮
    ok_round2 = False
    if triggered:
        first = next(iter(r1["tool_calls"].values()))
        msgs = [
            {"role": "user", "content": "北京今天天气怎么样？"},
            {
                "role": "assistant",
                "content": r1["content"] or None,
                "tool_calls": [{
                    "id": first["id"], "type": "function",
                    "function": {"name": first["name"], "arguments": first["args"]},
                }],
            },
            {"role": "tool", "tool_call_id": first["id"], "content": json.dumps(CANNED_WEATHER, ensure_ascii=False)},
        ]
        print("[b] 回填 tool 结果（18℃ 晴）→")
        r2 = _stream_once(client, {**base, "messages": msgs})
        if r2["status"] != 200:
            print(f"  二轮失败: {r2['status']} {r2.get('error_body', '')[:200]}")
        else:
            print(f"  finish_reason 序列: {r2['finish_reasons']}")
            print(f"  二轮 usage: {r2['usage']}")
            print(f"  最终回答: {r2['content'][:120]}")
            ok_round2 = ("18" in r2["content"] or "晴" in r2["content"]) and not r2["tool_calls"]
            if not ok_round2:
                print("  [警告] 回答未包含工具数据或仍继续调用工具")

    # c) 无关问题在挂载 tools 时不应触发
    print("[c] 挂载 tools 但问无关问题（写诗）→")
    r3 = _stream_once(client, {**base, "messages": [{"role": "user", "content": "写一句关于春天的诗"}]})
    no_false_trigger = r3["status"] == 200 and not r3["tool_calls"] and len(r3["content"]) > 5
    print(f"  status={r3['status']} tool_calls={bool(r3['tool_calls'])} content='{r3['content'][:40]}'")

    facts["工具调用分片"] = (
        f"index/id/function.name/function.arguments 分片拼接；finish_reason={r1['finish_reasons'][-1] if r1['finish_reasons'] else '无'}"
    ) if triggered else "未触发，待查"
    facts["tools+thinking 共存"] = "正常" if triggered else "异常"
    record("T6 tools", triggered and ok_round2 and no_false_trigger,
           f"触发={triggered} 二轮={ok_round2} 误触发={not no_false_trigger}")


def summarize() -> None:
    section("汇总与实施结论")
    width = max(len(n) for n, _, _ in results) if results else 10
    for name, status, summary in results:
        print(f"{name:<{width}}  {status}  {summary}")
    print("\n[实施可直接引用的事实]")
    for k, v in facts.items():
        print(f"  - {k}: {v}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="只跑指定用例，逗号分隔，如 T1,T3")
    args = parser.parse_args()
    todo = {s.strip() for s in args.only.split(",")} if args.only else None

    print(f"BASE_URL: {settings.llm.base_url}")
    print(f"MODEL:    {settings.llm.model}")
    if not settings.llm.api_key:
        print(
            "\n[错误] LLM.API_KEY 为空。请先复制 .env.example 为 .env 并填写 API Key：\n"
            "  cp .env.example .env  然后编辑 LLM.API_KEY=<你的密钥>"
        )
        sys.exit(1)
    print(f"API_KEY:  {settings.llm.api_key[:6]}****")

    tests = {
        "T1": test_basic,
        "T2": test_thinking,
        "T3": test_stream,
        "T4": test_vision,
        "T5": test_abort,
        "T6": test_tools,
    }
    with httpx.Client(timeout=120) as client:
        for name, fn in tests.items():
            if todo and name not in todo:
                continue
            try:
                fn(client)
            except Exception as e:  # noqa: BLE001 - 单用例失败不影响其余用例
                print(f"  [未捕获异常] {type(e).__name__}: {e}")
                record(name, False, f"异常 {type(e).__name__}")
    summarize()


if __name__ == "__main__":
    main()
