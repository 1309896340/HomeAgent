"""设备注册表（device-registry）后端验证脚本。

用 FastAPI TestClient 走真实 HTTP 栈验证 /devices API 全链路，
不依赖浏览器；网段检测、ping、nmap 检测等 IO 用真实环境实测。

覆盖：
  B1 启动链路：import app 时网段检测日志 + nmap 检测（缺失则降级 warning）
  B2 鉴权：未登录访问 /devices 返回 401
  B3 注册闭环：嗅探任务创建/轮询 → 注册 → 重复 IP 409 → 列表含设备
  B4 重命名/移除：PATCH / DELETE（含 404）
  B5 状态接口：/devices/status 并发 ping + ping_interval 下发（clamp ≥1）
  B6 scan_status 状态机：nmap 缺失时 unavailable（降级路径）

用法（项目根目录）：
  uv run python scripts/verify_devices.py
"""

from __future__ import annotations

import io
import sys

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient

from web.backend.app import app
from web.backend.services import auth_service, device_service

client = TestClient(app, raise_server_exceptions=False)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")


def issue_login() -> dict:
    """直签一个登录会话（与前端 Cookie 同名），返回请求用 headers。"""
    from web.backend.db import db

    with db() as conn:
        row = conn.execute("SELECT id FROM users WHERE disabled = 0 LIMIT 1").fetchone()
    if row is None:
        raise SystemExit("库中无可用用户：请先注册至少一个账号再运行本脚本")
    token, _, _ = auth_service.issue_session(row["id"], remember=False)
    return {"Cookie": f"ha_session={token}"}


def main() -> None:
    print("== B1 启动链路（网段检测日志已在 import app 时输出）==")
    from web.backend.services import lan_service

    network = lan_service.detected_network()
    check("B1 网段已检测", "/" in network and network.endswith("/24"), network)
    nmap = lan_service.find_nmap()
    print(f"  INFO  nmap 可执行: {nmap or '未找到（端口扫描降级）'}")

    headers = issue_login()

    print("== B2 鉴权 ==")
    r = client.get("/devices")
    check("B2 未登录 401", r.status_code == 401, f"status={r.status_code}")

    print("== B3 注册闭环 ==")
    r = client.post("/devices/scan", headers=headers)
    check("B3a 创建嗅探任务", r.status_code == 200 and "scan_id" in r.json(), str(r.json()))
    scan_id = r.json()["scan_id"]
    r = client.get(f"/devices/scan/{scan_id}", headers=headers)
    check("B3b 轮询任务存在", r.status_code == 200 and r.json()["status"] in ("running", "done"))
    r = client.get("/devices/scan/not-exist", headers=headers)
    check("B3c 未知任务 404", r.status_code == 404)

    # 等嗅探任务真实跑完，挑一个存活 IP 注册
    import time

    for _ in range(30):
        task = device_service.get_discovery(scan_id)
        if task["status"] == "done":
            break
        time.sleep(1)
    check("B3d 嗅探任务完成", task["status"] == "done", f"发现 {len(task['hosts'])} 台未注册")
    if task["hosts"]:
        ip = task["hosts"][0]["ip"]
        suggested = task["hosts"][0]["suggested_name"]
        print(f"  INFO  用嗅探结果注册: {ip} (建议名 {suggested})")
    else:
        ip = "192.168.3.1"  # 无可用结果时兜底（若该 IP 已注册，B3f 验证改为跳过提示）
        print(f"  INFO  嗅探无未注册主机，兜底注册 {ip}")

    r = client.post("/devices", headers=headers, json={"ip": ip, "name": "验证设备"})
    check("B3e 注册成功 201", r.status_code == 201, str(r.json()))
    device_id = r.json().get("id")
    r = client.post("/devices", headers=headers, json={"ip": ip, "name": "重复"})
    check("B3f 重复 IP 409", r.status_code == 409)
    r = client.post("/devices", headers=headers, json={"ip": "999.1.1.1"})
    check("B3g 非法 IP 422", r.status_code == 422)

    r = client.get("/devices", headers=headers)
    listed = {d["id"]: d for d in r.json()}
    check("B3h 列表含新设备", device_id in listed)
    check("B3i nmap 缺失 → scan_status=unavailable",
          listed[device_id]["scan_status"] == ("unavailable" if nmap is None else "done"),
          listed[device_id]["scan_status"])

    print("== B4 重命名/移除 ==")
    r = client.patch(f"/devices/{device_id}", headers=headers, json={"name": "改名后"})
    check("B4a 重命名", r.status_code == 200 and r.json()["name"] == "改名后")
    r = client.patch(f"/devices/{device_id}", headers=headers, json={"name": "  "})
    check("B4b 空名 422", r.status_code == 422)
    r = client.patch("/devices/999999", headers=headers, json={"name": "x"})
    check("B4c 不存在 404", r.status_code == 404)
    r = client.delete(f"/devices/{device_id}", headers=headers)
    check("B4d 移除 204", r.status_code == 204)
    r = client.delete(f"/devices/{device_id}", headers=headers)
    check("B4e 重复移除 404", r.status_code == 404)

    print("== B5 状态接口 ==")
    r = client.post("/devices", headers=headers, json={"ip": "192.168.3.1", "name": "状态设备"})
    status_id = r.json()["id"]
    r = client.get("/devices/status", headers=headers)
    body = r.json()
    ok = (r.status_code == 200 and "devices" in body
          and isinstance(body["ping_interval"], int) and body["ping_interval"] >= 1
          and any(d["id"] == status_id for d in body["devices"]))
    check("B5 状态+interval 下发", ok, f"interval={body.get('ping_interval')}, {len(body.get('devices', []))} 台")
    client.delete(f"/devices/{status_id}", headers=headers)

    print()
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"共 {len(RESULTS)} 项，失败 {len(failed)} 项" + (f": {failed}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
