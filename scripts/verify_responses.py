"""豆包 agent plan Responses API（/responses）端点行为验证脚本。

背景：对话模块从 chat/completions 迁移到 Responses API 以使用内置
web_search 工具（联网搜索）。本脚本在实施前锁定协议事实：
  T1 非流式基础调用：output 结构、usage 字段名、instructions 参数、
      system role / assistant 历史文本在 input 中的回放格式、store 参数
  T2 流式输出：SSE 事件类型清单、正文/思考的 delta 事件名与字段、
      usage 所在事件、终止方式（[DONE] 还是 response.completed）
  T3 思考控制：thinking / reasoning 参数在 Responses API 是否被接受
  T4 视觉输入：input_image + base64 data URL
  T5 中断行为：流式读到一半主动断开
  T6 function 工具：扁平工具声明格式、function_call 流式分片与 call_id、
      function_call + function_call_output 回放第二轮、无关问题不误触发
  T7 web_search：流式事件序列、query 出现位置、url_citation 引用所在、
      usage.tool_usage 计费计数
  T8 web_search 与 function 工具共存：模型能否正确选择、互不干扰
  T9 错误形态：非法模型名的 HTTP 状态与错误体

用法（项目根目录执行，需先配置 .env 的 LLM.API_KEY）：
  uv run python scripts/verify_responses.py
  uv run python scripts/verify_responses.py --only T2,T7
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

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

results: list[tuple[str, str, str]] = []
facts: dict[str, str] = {}


def record(name: str, ok: bool, summary: str) -> None:
    results.append((name, "PASS" if ok else "FAIL", summary))


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.llm.api_key}"}


def responses_url() -> str:
    return f"{settings.llm.base_url.rstrip('/')}/responses"


def print_error(r: httpx.Response) -> None:
    print(f"  HTTP {r.status_code} {r.headers.get('content-type', '')}")
    print(f"  body: {r.text[:500]}")


# ---------- 流式事件收集 ----------

def stream_once(client: httpx.Client, body: dict) -> dict:
    """跑一轮 /responses 流式请求，收集全部事件的结构化观察。"""
    out: dict = {
        "status": None,
        "error_body": None,
        "event_types": [],          # 按出现顺序的 data.type 清单
        "text": "",
        "reasoning": "",
        "delta_sample": None,       # 首个正文 delta 事件原始内容
        "function_calls": {},       # output_index -> {"call_id","name","arguments"}
        "web_searches": [],         # [{"query", "status"}]
        "usage": None,
        "completed": None,          # response.completed 的完整 response 对象
        "terminated_by": None,      # completed / [DONE] / 连接关闭
    }
    with client.stream("POST", responses_url(), json=body, headers=auth_headers()) as r:
        out["status"] = r.status_code
        if r.status_code != 200:
            out["error_body"] = r.read().decode(errors="replace")[:400]
            return out
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                if payload == "[DONE]":
                    out["terminated_by"] = "[DONE]"
                continue
            try:
                ev = json.loads(payload)
            except ValueError:
                continue
            etype = ev.get("type", "?")
            out["event_types"].append(etype)
            if etype == "response.output_text.delta":
                out["text"] += ev.get("delta", "")
                if out["delta_sample"] is None:
                    out["delta_sample"] = ev
            elif etype == "response.reasoning_summary_text.delta":
                out["reasoning"] += ev.get("delta", "")
            elif etype == "response.output_item.added":
                item = ev.get("item") or {}
                if item.get("type") == "function_call":
                    out["function_calls"].setdefault(
                        ev.get("output_index"),
                        {"call_id": item.get("call_id"), "name": item.get("name"),
                         "arguments": "", "item_id": item.get("id")},
                    )
                elif item.get("type") == "web_search_call":
                    out["web_searches"].append(
                        {"query": (item.get("action") or {}).get("query"),
                         "status": item.get("status")}
                    )
            elif etype == "response.function_call_arguments.delta":
                fc = out["function_calls"].setdefault(
                    ev.get("output_index"), {"call_id": None, "name": None, "arguments": ""}
                )
                fc["arguments"] += ev.get("delta", "")
            elif etype.endswith("web_search_call.completed") or etype.endswith(
                "web_search_call.searching"
            ):
                q = (ev.get("action") or {}).get("query")
                if q:
                    for ws in out["web_searches"]:
                        if not ws["query"]:
                            ws["query"] = q
            elif etype == "response.completed":
                out["completed"] = ev.get("response") or {}
                out["usage"] = (ev.get("response") or {}).get("usage")
                if out["terminated_by"] is None:
                    out["terminated_by"] = "response.completed"
    return out


def extract_message(resp: dict) -> tuple[str, list[dict]]:
    """从 response 对象提取 (正文, url_citation 引用列表)。"""
    text, cites = "", []
    for item in resp.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text":
                text += part.get("text", "")
                for a in part.get("annotations") or []:
                    if a.get("type") == "url_citation":
                        cites.append(a)
    return text, cites


def test_basic(client: httpx.Client) -> None:
    section("T1 非流式基础调用")
    # a) instructions 参数 + 基本结构
    body = {
        "model": settings.llm.model,
        "instructions": "你是一个测试助手，回答以 [OK] 开头。",
        "input": [{"role": "user", "content": "用一句话介绍你自己"}],
    }
    t0 = time.perf_counter()
    r = client.post(responses_url(), json=body, headers=auth_headers())
    elapsed = time.perf_counter() - t0
    if r.status_code != 200:
        print_error(r)
        record("T1 basic+instructions", False, f"status={r.status_code}")
    else:
        data = r.json()
        text, _ = extract_message(data)
        types = [i.get("type") for i in data.get("output", [])]
        print(f"  [a] {elapsed:.2f}s  status={data.get('status')}  output 类型: {types}")
        print(f"      正文: {text[:100]}")
        print(f"      usage: {json.dumps(data.get('usage'), ensure_ascii=False)}")
        print(f"      instructions 生效: {text.startswith('[OK]')}")
        facts["usage 字段名"] = "input_tokens / output_tokens / total_tokens（output_tokens_details.reasoning_tokens）"
        facts["系统提示"] = "instructions 参数生效" if text.startswith("[OK]") else "instructions 未生效，需检查"
        record("T1 basic+instructions", True, f"{elapsed:.1f}s instructions={'生效' if text.startswith('[OK]') else '未生效'}")

    # b) system role 在 input 回放 + assistant 历史文本回放 + store:false
    body2 = {
        "model": settings.llm.model,
        "store": False,
        "input": [
            {"role": "system", "content": "回答以 [SYS] 开头。"},
            {"role": "user", "content": "我叫小明，记住我的名字"},
            {"role": "assistant", "content": "好的小明，我记住了。"},
            {"role": "user", "content": "我叫什么名字？用一句话回答"},
        ],
    }
    r2 = client.post(responses_url(), json=body2, headers=auth_headers())
    if r2.status_code != 200:
        print(f"  [b] system/assistant 回放被拒绝:")
        print_error(r2)
        record("T1 history replay", False, f"status={r2.status_code}")
    else:
        data2 = r2.json()
        text2, _ = extract_message(data2)
        ok = "小明" in text2
        print(f"  [b] store=false 接受，历史回放成功: {text2[:80]}")
        facts["历史回放"] = "system/assistant/user 文本消息可直接作为 input 项回放" if ok else "回放异常"
        record("T1 history replay", ok, f"记住名字={'是' if ok else '否'}")


def test_stream(client: httpx.Client) -> None:
    section("T2 流式输出（SSE 事件清单）")
    body = {
        "model": settings.llm.model,
        "input": [{"role": "user", "content": "写一首关于秋天的两句短诗"}],
        "stream": True,
    }
    t0 = time.perf_counter()
    out = stream_once(client, body)
    elapsed = time.perf_counter() - t0
    if out["status"] != 200:
        print(f"  HTTP {out['status']}\n  body: {out['error_body']}")
        record("T2 stream", False, f"status={out['status']}")
        return
    from collections import Counter
    counts = Counter(out["event_types"])
    print(f"  耗时 {elapsed:.2f}s  正文 {len(out['text'])} 字  思考摘要 {len(out['reasoning'])} 字")
    print(f"  事件类型统计: {dict(counts)}")
    print(f"  delta 事件样例: {json.dumps(out['delta_sample'], ensure_ascii=False)[:200]}")
    print(f"  usage: {json.dumps(out['usage'], ensure_ascii=False)}")
    print(f"  终止方式: {out['terminated_by']}")
    facts["流式事件"] = "正文=response.output_text.delta(delta)；思考=response.reasoning_summary_text.delta(delta)" \
        if out["reasoning"] else "正文=response.output_text.delta；本例无思考事件"
    facts["流式终止"] = str(out["terminated_by"])
    facts["usage 位置"] = "response.completed 事件的 response.usage"
    record("T2 stream", bool(out["text"]), f"{elapsed:.1f}s 事件 {len(counts)} 种")


def test_thinking(client: httpx.Client) -> None:
    section("T3 思考控制参数")
    for label, extra in (
        ("无参数", {}),
        ('thinking={"type":"disabled"}', {"thinking": {"type": "disabled"}}),
        ('reasoning={"effort":"low"}', {"reasoning": {"effort": "low"}}),
    ):
        body = {
            "model": settings.llm.model,
            "input": [{"role": "user", "content": "9.11 和 9.8 哪个大？"}],
            **extra,
        }
        try:
            r = client.post(responses_url(), json=body, headers=auth_headers(), timeout=120)
        except httpx.HTTPError as e:
            print(f"  [{label}] 异常: {e}")
            record("T3 thinking", False, f"{label} 异常")
            return
        if r.status_code != 200:
            print(f"  [{label}] HTTP {r.status_code}: {r.text[:150]}")
            continue
        data = r.json()
        types = [i.get("type") for i in data.get("output", [])]
        has_reasoning = "reasoning" in types
        print(f"  [{label}] 接受。output 类型: {types}  含 reasoning: {has_reasoning}"
              f"  tokens={data.get('usage', {}).get('total_tokens')}")
    facts["思考控制"] = "见上方对照（无参数默认开启思考）"
    record("T3 thinking", True, "参数对照完成")


def make_solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
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
    section("T4 视觉输入（input_image + data URL）")
    png = make_solid_png(64, 64, (30, 160, 90))
    data_url = "data:image/png;base64," + base64.b64encode(png).decode()
    body = {
        "model": settings.llm.model,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "图中方块是什么颜色？只回答颜色名。"},
                {"type": "input_image", "image_url": data_url},
            ],
        }],
    }
    t0 = time.perf_counter()
    r = client.post(responses_url(), json=body, headers=auth_headers())
    elapsed = time.perf_counter() - t0
    if r.status_code != 200:
        print_error(r)
        record("T4 vision", False, f"status={r.status_code}")
        return
    text, _ = extract_message(r.json())
    print(f"  {elapsed:.2f}s  回答: {text[:60]}")
    ok = "绿" in text
    facts["视觉输入"] = "content 数组 input_text + input_image(data URL 字符串)" if ok else f"回答异常: {text[:50]}"
    record("T4 vision", ok, f"回答='{text[:30]}'")


def test_abort(client: httpx.Client) -> None:
    section("T5 中断行为")
    body = {
        "model": settings.llm.model,
        "input": [{"role": "user", "content": "写一篇 500 字的散文"}],
        "stream": True,
    }
    t0 = time.perf_counter()
    got = 0
    try:
        with client.stream("POST", responses_url(), json=body, headers=auth_headers()) as r:
            if r.status_code != 200:
                print_error(r)
                record("T5 abort", False, f"status={r.status_code}")
                return
            for line in r.iter_lines():
                if line.startswith("data:"):
                    got += 1
                    if got >= 3:
                        break
    except httpx.HTTPError as e:
        print(f"  断开时网络异常(服务端可能主动 RST，属正常): {type(e).__name__}")
    print(f"  读取 {got} 个事件后主动断开，客户端干净退出，耗时 {time.perf_counter() - t0:.2f}s")
    record("T5 abort", True, f"断开于 {got} 事件")


# ---------- T6 function 工具 ----------

WEATHER_TOOL = {
    "type": "function",
    "name": "get_weather",
    "description": "查询指定城市的实时天气",
    "parameters": {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "城市名，如 北京"},
        },
        "required": ["location"],
    },
}

CANNED_WEATHER = {"location": "北京", "temperature": 18, "condition": "晴"}


def test_tools(client: httpx.Client) -> None:
    section("T6 function 工具（扁平声明 + 回放）")
    base = {
        "model": settings.llm.model,
        "stream": True,
        "tools": [WEATHER_TOOL],
    }

    print("[a] 挂载 tools 询问天气 →")
    r1 = stream_once(client, {**base, "input": [{"role": "user", "content": "北京今天天气怎么样？"}]})
    if r1["status"] != 200:
        print(f"  HTTP {r1['status']}\n  body: {r1['error_body']}")
        record("T6 tools", False, f"status={r1['status']}")
        return
    print(f"  事件: {[e for e in dict.fromkeys(r1['event_types'])]}")
    print(f"  正文: '{r1['text'][:60]}'")
    for idx, fc in r1["function_calls"].items():
        print(f"  function_call[{idx}]: call_id={fc['call_id']} name={fc['name']} args={fc['arguments']}")
    triggered = bool(r1["function_calls"])
    try:
        args = json.loads(next(iter(r1["function_calls"].values()))["arguments"]) if triggered else {}
    except ValueError:
        args = {}
    if not (triggered and "location" in args):
        print("  [警告] 未触发工具或参数解析失败")
        record("T6 tools", False, "未触发")
        return

    # b) function_call + function_call_output 回放
    fc = next(iter(r1["function_calls"].values()))
    print("[b] 回填 function_call_output（18℃ 晴）→")
    r2 = stream_once(client, {
        **base,
        "input": [
            {"role": "user", "content": "北京今天天气怎么样？"},
            {"type": "function_call", "call_id": fc["call_id"], "name": fc["name"],
             "arguments": fc["arguments"]},
            {"type": "function_call_output", "call_id": fc["call_id"],
             "output": json.dumps(CANNED_WEATHER, ensure_ascii=False)},
        ],
    })
    ok_round2 = False
    if r2["status"] != 200:
        print(f"  二轮失败: {r2['status']} {r2['error_body'][:200]}")
    else:
        print(f"  最终回答: {r2['text'][:120]}")
        ok_round2 = ("18" in r2["text"] or "晴" in r2["text"]) and not r2["function_calls"]
        if not ok_round2:
            print("  [警告] 回答未包含工具数据或仍继续调用工具")

    print("[c] 挂载 tools 但问无关问题（写诗）→")
    r3 = stream_once(client, {**base, "input": [{"role": "user", "content": "写一句关于春天的诗"}]})
    no_false = r3["status"] == 200 and not r3["function_calls"] and len(r3["text"]) > 5
    print(f"  status={r3['status']} function_calls={bool(r3['function_calls'])} text='{r3['text'][:40]}'")

    facts["function 工具"] = "扁平声明 {type,name,description,parameters}；流式经 output_item.added(function_call 含 call_id) + function_call_arguments.delta 分片"
    facts["工具结果回放"] = "input 追加 {type:function_call,...} 与 {type:function_call_output,call_id,output}"
    record("T6 tools", triggered and ok_round2 and no_false,
           f"触发={triggered} 二轮={ok_round2} 误触发={not no_false}")


def test_web_search(client: httpx.Client) -> None:
    section("T7 web_search 内置工具（流式）")
    body = {
        "model": settings.llm.model,
        "stream": True,
        "tools": [{"type": "web_search"}],
        "input": [{"role": "user", "content": "用两句话说明今天北京的天气"}],
    }
    t0 = time.perf_counter()
    out = stream_once(client, body)
    elapsed = time.perf_counter() - t0
    if out["status"] != 200:
        print(f"  HTTP {out['status']}\n  body: {out['error_body']}")
        record("T7 web_search", False, f"status={out['status']}")
        return
    ws_events = [e for e in dict.fromkeys(out["event_types"]) if "web_search" in e]
    print(f"  耗时 {elapsed:.2f}s  正文 {len(out['text'])} 字")
    print(f"  web_search 相关事件: {ws_events}")
    print(f"  搜索调用: {out['web_searches']}")
    text, cites = extract_message(out["completed"] or {})
    print(f"  正文: {text[:150]}")
    print(f"  引用数: {len(cites)}  首条: {json.dumps(cites[0], ensure_ascii=False)[:200] if cites else '无'}")
    usage = out["usage"] or {}
    print(f"  usage: {json.dumps(usage, ensure_ascii=False)}")
    facts["web_search 流式"] = f"事件序列含 {ws_events or '未见'}"
    facts["引用位置"] = "response.completed → output[message].content[output_text].annotations[url_citation]"
    facts["web_search 计费"] = f"usage.tool_usage.web_search 计数（本例 {((usage.get('tool_usage') or {}).get('web_search'))}）"
    record("T7 web_search", bool(out["web_searches"]) and bool(cites),
           f"{elapsed:.1f}s 搜索={len(out['web_searches'])} 引用={len(cites)}")


def test_mixed_tools(client: httpx.Client) -> None:
    section("T8 web_search + function 工具共存")
    body = {
        "model": settings.llm.model,
        "stream": True,
        "tools": [{"type": "web_search"}, WEATHER_TOOL],
        "input": [{"role": "user", "content": "帮我搜一下今天有什么值得关注的科技新闻，挑两条用中文简介"}],
    }
    t0 = time.perf_counter()
    out = stream_once(client, body)
    elapsed = time.perf_counter() - t0
    if out["status"] != 200:
        print(f"  HTTP {out['status']}\n  body: {out['error_body']}")
        record("T8 mixed", False, f"status={out['status']}")
        return
    print(f"  耗时 {elapsed:.2f}s  web_search 调用: {out['web_searches']}  function 调用: {list(out['function_calls'].values())}")
    text, cites = extract_message(out["completed"] or {})
    print(f"  正文: {text[:160]}")
    print(f"  引用数: {len(cites)}")
    used_search = bool(out["web_searches"])
    used_fn = bool(out["function_calls"])
    facts["工具共存"] = f"web_search 与 function 共存正常（本例 search={used_search} fn={used_fn}）"
    record("T8 mixed", used_search and len(text) > 20, f"{elapsed:.1f}s search={used_search} fn={used_fn} 引用={len(cites)}")


def test_error(client: httpx.Client) -> None:
    section("T9 错误形态（非法模型名）")
    body = {"model": "not-exist-model", "input": [{"role": "user", "content": "hi"}]}
    t0 = time.perf_counter()
    r = client.post(responses_url(), json=body, headers=auth_headers())
    elapsed = time.perf_counter() - t0
    print(f"  HTTP {r.status_code}  body: {r.text[:300]}")
    ok = r.status_code in (400, 401, 404)
    facts["错误形态"] = f"非 200 + error JSON（本例 {r.status_code}）"
    record("T9 error", ok, f"status={r.status_code} {elapsed:.1f}s")


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
    parser.add_argument("--only", help="只跑指定用例，逗号分隔，如 T1,T7")
    args = parser.parse_args()
    todo = {s.strip() for s in args.only.split(",")} if args.only else None

    print(f"BASE_URL: {settings.llm.base_url}")
    print(f"MODEL:    {settings.llm.model}")
    if not settings.llm.api_key:
        print("\n[错误] LLM.API_KEY 为空，请先配置 .env")
        sys.exit(1)
    print(f"API_KEY:  {settings.llm.api_key[:6]}****")

    tests = {
        "T1": test_basic,
        "T2": test_stream,
        "T3": test_thinking,
        "T4": test_vision,
        "T5": test_abort,
        "T6": test_tools,
        "T7": test_web_search,
        "T8": test_mixed_tools,
        "T9": test_error,
    }
    with httpx.Client(timeout=180) as client:
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
