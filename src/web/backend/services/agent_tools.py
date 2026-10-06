"""Agent 工具白名单：read_skill + mock 设备服务。

家中硬件尚未接入，设备工具全部为 mock 数据（与 skills/home-profile 的
SKILL.md 对应，仅供联调测试）；真实设备层落地后在此替换实现并保持
工具签名不变，模型侧无感。

安全约定：模型可调用的工具仅限 TOOL_IMPLS 白名单；执行错误以 JSON
字符串回传给模型自行恢复，不向上抛异常中断对话。
"""

from __future__ import annotations

import json
from typing import Any

from web.backend.services import skill_registry

# ---------- mock 设备数据（家中无硬件，仅供测试） ----------

MOCK_DEVICES: dict[str, dict[str, Any]] = {
    "living-light": {"name": "客厅主灯", "type": "light", "online": True, "power": "off"},
    "temp-living": {
        "name": "客厅温湿度传感器", "type": "sensor", "online": True,
        "temperature": 24.6, "humidity": 58,
    },
    "door-lock": {"name": "入户门锁", "type": "lock", "online": True, "locked": True},
    "air-purifier": {"name": "空气净化器", "type": "appliance", "online": True, "pm25": 32, "mode": "auto"},
}

# ---------- OpenAI function calling 工具声明 ----------

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_skill",
            "description": "读取一个技能的完整说明（SKILL.md）。当对话涉及系统提示中某个技能的领域时，先调用本工具。",
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
                "properties": {"device_id": {"type": "string", "description": "设备 ID"}},
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
                    "device_id": {"type": "string", "description": "设备 ID"},
                    "action": {"type": "string", "description": "动作，如 on/off/lock/unlock/auto/sleep"},
                },
                "required": ["device_id", "action"],
            },
        },
    },
]


def build_tool_specs() -> list[dict[str, Any]]:
    """返回挂载给 LLM 的工具声明（拷贝，防调用方修改）。"""
    return [dict(spec) for spec in TOOL_SPECS]


# ---------- 工具实现 ----------

def _read_skill(name: str) -> str:
    return skill_registry.read_skill(name)


def _list_devices() -> str:
    return json.dumps(
        [{"device_id": k, **v} for k, v in MOCK_DEVICES.items()],
        ensure_ascii=False,
    )


def _get_device_status(device_id: str) -> str:
    dev = MOCK_DEVICES.get(device_id)
    if dev is None:
        return json.dumps(
            {"error": "device_not_found", "device_id": device_id,
             "known_devices": list(MOCK_DEVICES)},
            ensure_ascii=False,
        )
    return json.dumps({"device_id": device_id, **dev}, ensure_ascii=False)


def _control_device(device_id: str, action: str) -> str:
    dev = MOCK_DEVICES.get(device_id)
    if dev is None:
        return json.dumps(
            {"error": "device_not_found", "device_id": device_id,
             "known_devices": list(MOCK_DEVICES)},
            ensure_ascii=False,
        )
    if dev["type"] == "light" and action in ("on", "off"):
        dev["power"] = action
    elif dev["type"] == "appliance" and action in ("auto", "sleep", "off"):
        dev["mode"] = action
    else:
        return json.dumps(
            {"error": "action_not_supported", "device_id": device_id, "action": action},
            ensure_ascii=False,
        )
    return json.dumps(
        {"ok": True, "device_id": device_id, "action": action, "note": "mock 执行成功"},
        ensure_ascii=False,
    )


TOOL_IMPLS: dict[str, Any] = {
    "read_skill": _read_skill,
    "list_devices": _list_devices,
    "get_device_status": _get_device_status,
    "control_device": _control_device,
}


def execute_tool(name: str, args: dict[str, Any]) -> str:
    """按白名单执行工具，结果一律为字符串（JSON 或文本）。"""
    fn = TOOL_IMPLS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown_tool: {name}"}, ensure_ascii=False)
    try:
        return str(fn(**args))
    except (TypeError, FileNotFoundError, ValueError) as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)
