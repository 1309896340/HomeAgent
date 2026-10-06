"""Skill 机制全流程模拟验证（不依赖后端实现）。

在脚本内模拟将来后端的 agent loop：system prompt 注入技能清单（渐进式披露），
挂载 read_skill + 一组 mock 设备服务工具，多轮流式调用真实 LLM，
验证「技能发现 → 读取技能 → 调用工具 → 引用数据回答」整条链路。

mock 设备服务：家中硬件尚未接入，数据全部为假，仅验证机制。

场景：
  S1 查询类：客厅温度多少？      → 期望 read_skill → get_device_status/list_devices → 回答含 24.6
  S2 控制类：把客厅灯打开        → 期望 read_skill → control_device(living-light, on) → 确认执行
  S3 越界类：把卧室灯打开        → 期望查证后如实说明没有该设备，不虚构执行
  S4 回归类：写一句诗            → 期望不读技能不调工具，直接回答

用法（项目根目录）：
  uv run python scripts/verify_skill_flow.py
  uv run python scripts/verify_skill_flow.py --only S1,S2
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from web.backend.config import settings

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"
MAX_ROUNDS = 5

# ---------- mock 设备服务（家中硬件未接入，数据为假） ----------

MOCK_DEVICES: dict[str, dict] = {
    "living-light": {"name": "客厅主灯", "type": "light", "online": True, "power": "off"},
    "temp-living": {
        "name": "客厅温湿度传感器", "type": "sensor", "online": True,
        "temperature": 24.6, "humidity": 58,
    },
    "door-lock": {"name": "入户门锁", "type": "lock", "online": True, "locked": True},
    "air-purifier": {"name": "空气净化器", "type": "appliance", "online": True, "pm25": 32, "mode": "auto"},
}


def op_read_skill(name: str) -> str:
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.is_file():
        avail = ", ".join(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))
        return f"技能不存在：{name}。可用技能：{avail}"
    text = path.read_text(encoding="utf-8")
    return text[:30000] + ("\n…（已截断）" if len(text) > 30000 else "")


def op_list_devices() -> str:
    return json.dumps(
        [{"device_id": k, **{kk: vv for kk, vv in v.items()}} for k, v in MOCK_DEVICES.items()],
        ensure_ascii=False,
    )


def op_get_device_status(device_id: str) -> str:
    dev = MOCK_DEVICES.get(device_id)
    if dev is None:
        return json.dumps({"error": "device_not_found", "device_id": device_id}, ensure_ascii=False)
    return json.dumps({"device_id": device_id, **dev}, ensure_ascii=False)


def op_control_device(device_id: str, action: str) -> str:
    dev = MOCK_DEVICES.get(device_id)
    if dev is None:
        return json.dumps({"error": "device_not_found", "device_id": device_id}, ensure_ascii=False)
    if dev["type"] == "light" and action in ("on", "off"):
        dev["power"] = action
    elif dev["type"] == "appliance" and action in ("auto", "sleep", "off"):
        dev["mode"] = action
    else:
        return json.dumps({"error": "action_not_supported", "device_id": device_id, "action": action}, ensure_ascii=False)
    return json.dumps({"ok": True, "device_id": device_id, "action": action, "note": "mock 执行成功"}, ensure_ascii=False)


TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "read_skill",
            "description": "读取一个技能的完整说明（SKILL.md）。当对话涉及某技能的领域时先调用它。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "技能名，见系统提示中的技能清单"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_devices",
            "description": "列出家中全部已接入设备的概览",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_device_status",
            "description": "查询单台设备的实时状态",
            "parameters": {
                "type": "object",
                "properties": {"device_id": {"type": "string"}},
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_device",
            "description": "控制一台设备执行动作",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "action": {"type": "string", "description": "动作，如 on/off/lock/unlock/auto/sleep"},
                },
                "required": ["device_id", "action"],
            },
        },
    },
]

TOOL_IMPLS = {
    "read_skill": op_read_skill,
    "list_devices": op_list_devices,
    "get_device_status": op_get_device_status,
    "control_device": op_control_device,
}

# ---------- 技能清单（渐进式披露：仅 name + description 进 system prompt） ----------


def parse_frontmatter(text: str) -> dict | None:
    """极简 frontmatter 解析（扁平 key: value，验证脚本够用；后端实现用 pyyaml）。"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return None
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out or None


def load_skill_manifest() -> list[dict]:
    skills = []
    for path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        if fm and fm.get("name") and fm.get("description"):
            skills.append({"name": fm["name"], "description": fm["description"], "path": str(path)})
        else:
            print(f"[registry] 跳过无效技能文件: {path}")
    return skills


def build_system_prompt(manifest: list[dict]) -> str:
    base = (
        "你是 HomeAgent，一个运行在用户家中的智能助手。"
        "回答用中文，简洁准确。"
    )
    if not manifest:
        return base
    lines = "\n".join(f"- {s['name']}: {s['description']}" for s in manifest)
    return (
        f"{base}\n\n## 可用技能（仅名称与简介）\n{lines}\n\n"
        "当对话涉及上述技能领域时，先调用 read_skill 工具获取完整说明，再按说明行动。"
    )

# ---------- 模拟 agent loop ----------


def stream_round(client: httpx.Client, messages: list[dict]) -> dict:
    """单轮流式请求：返回 content / tool_calls（已拼接）/ finish_reason / usage。"""
    body = {
        "model": settings.llm.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "thinking": {"type": "enabled"},
        "tools": TOOL_SPECS,
        "tool_choice": "auto",
    }
    headers = {"Authorization": f"Bearer {settings.llm.api_key}"}
    acc: dict[int, dict] = {}
    content = ""
    finish = None
    usage = None
    with client.stream(
        "POST", f"{settings.llm.base_url.rstrip('/')}/chat/completions", json=body, headers=headers,
        timeout=httpx.Timeout(120.0, connect=10.0),
    ) as r:
        if r.status_code != 200:
            raise RuntimeError(f"LLM {r.status_code}: {r.read().decode(errors='replace')[:200]}")
        for line in r.iter_lines():
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
                usage = chunk["usage"]
            for choice in chunk.get("choices", []):
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    content += delta["content"]
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    e = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        e["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        e["name"] += fn["name"]
                    if fn.get("arguments"):
                        e["arguments"] += fn["arguments"]
    return {
        "content": content,
        "tool_calls": [acc[i] for i in sorted(acc)],
        "finish_reason": finish,
        "usage": usage,
    }


def run_agent(client: httpx.Client, system_prompt: str, user_msg: str) -> dict:
    """多轮 agent loop：工具调用 → 执行 → 回填 → 继续，返回轨迹与统计。"""
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]
    trace: list[dict] = []
    total_tokens = 0
    t0 = time.perf_counter()
    for round_no in range(1, MAX_ROUNDS + 1):
        r = stream_round(client, messages)
        if r["usage"]:
            total_tokens += r["usage"].get("total_tokens") or 0
        if not r["tool_calls"]:
            trace.append({"round": round_no, "type": "final", "content_preview": r["content"][:80]})
            return {"rounds": round_no, "trace": trace, "answer": r["content"],
                    "total_tokens": total_tokens, "elapsed": time.perf_counter() - t0}
        # 执行本轮全部工具调用并回填
        calls_for_history = []
        for tc in r["tool_calls"]:
            try:
                args = json.loads(tc["arguments"] or "{}")
            except ValueError:
                args = {}
            fn = TOOL_IMPLS.get(tc["name"])
            result = fn(**args) if fn else json.dumps({"error": f"unknown_tool: {tc['name']}"})
            trace.append({"round": round_no, "type": "tool", "name": tc["name"], "args": args,
                          "result_preview": result[:80]})
            calls_for_history.append({
                "id": tc["id"], "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"] or "{}"},
            })
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
        # 注意：assistant(tool_calls) 消息必须在对应 tool 消息之前插入
        messages.insert(len(messages) - len(calls_for_history), {
            "role": "assistant", "content": r["content"] or None, "tool_calls": calls_for_history,
        })
    return {"rounds": MAX_ROUNDS, "trace": trace, "answer": "(达到轮次上限)",
            "total_tokens": total_tokens, "elapsed": time.perf_counter() - t0}

# ---------- 场景 ----------

results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, summary: str) -> None:
    results.append((name, "PASS" if ok else "FAIL", summary))


def tool_names(out: dict) -> list[str]:
    return [t["name"] for t in out["trace"] if t["type"] == "tool"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="只跑指定场景，逗号分隔，如 S1,S2")
    args = parser.parse_args()
    todo = {s.strip() for s in args.only.split(",")} if args.only else None

    if not settings.llm.api_key:
        sys.exit("LLM.API_KEY 未配置")
    manifest = load_skill_manifest()
    print("技能清单:", [(s["name"], s["description"][:20] + "…") for s in manifest])
    system_prompt = build_system_prompt(manifest)

    def check_s1(out: dict) -> tuple[bool, str]:
        tools = tool_names(out)
        read = "read_skill" in tools
        queried = bool({"get_device_status", "list_devices"} & set(tools))
        data = "24.6" in out["answer"]
        return read and queried and data, f"tools={tools} 回答含mock数据={data}"

    def check_s2(out: dict) -> tuple[bool, str]:
        tools = tool_names(out)
        ctrl = any(
            t["type"] == "tool" and t["name"] == "control_device"
            and t["args"].get("device_id") == "living-light" and t["args"].get("action") == "on"
            for t in out["trace"]
        )
        confirmed = ("已" in out["answer"] or "成功" in out["answer"] or "打开" in out["answer"])
        return ctrl and confirmed, f"control_device(on)={ctrl} 回答确认={confirmed}"

    def check_s3(out: dict) -> tuple[bool, str]:
        tools = tool_names(out)
        # 期望：没有对不存在设备的成功控制；回答说明不存在
        bad_ctrl = any(
            t["type"] == "tool" and t["name"] == "control_device"
            and t["args"].get("device_id") not in MOCK_DEVICES
            and t.get("result_preview", "").startswith('{"ok"')
            for t in out["trace"]
        )
        honest = ("没有" in out["answer"] or "不存在" in out["answer"] or "未接入" in out["answer"])
        return (not bad_ctrl) and honest, f"虚构执行={bad_ctrl} 如实说明={honest}"

    def check_s4(out: dict) -> tuple[bool, str]:
        tools = tool_names(out)
        return not tools and len(out["answer"]) > 5, f"tools={tools}"

    all_scenarios = {
        "S1": ("我家里客厅现在温度多少？湿度呢？", check_s1),
        "S2": ("帮我把客厅的灯打开。", check_s2),
        "S3": ("帮我把卧室的灯打开。", check_s3),
        "S4": ("写一句关于春天的诗。", check_s4),
    }

    with httpx.Client() as client:
        for key, (user_msg, check) in all_scenarios.items():
            if todo and key not in todo:
                continue
            print(f"\n{'=' * 60}\n{key}: {user_msg}\n{'=' * 60}")
            try:
                out = run_agent(client, system_prompt, user_msg)
            except Exception as e:  # noqa: BLE001 - 单场景失败不中断
                record(key, False, f"异常 {type(e).__name__}: {e}")
                continue
            for t in out["trace"]:
                if t["type"] == "tool":
                    print(f"  [r{t['round']}] 调用 {t['name']}({json.dumps(t['args'], ensure_ascii=False)})")
                    print(f"        → {t['result_preview']}")
                else:
                    print(f"  [r{t['round']}] 最终回答")
            print(f"  回答: {out['answer'][:160]}")
            print(f"  轮次={out['rounds']} 累计tokens={out['total_tokens']} 耗时={out['elapsed']:.1f}s")
            ok, detail = check(out)
            record(key, ok, detail)

    print(f"\n{'=' * 60}\n汇总\n{'=' * 60}")
    width = max(len(n) for n, _, _ in results) if results else 10
    for name, status, summary in results:
        print(f"{name:<{width}}  {status}  {summary}")


if __name__ == "__main__":
    main()
