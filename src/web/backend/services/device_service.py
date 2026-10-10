"""设备注册表服务：注册/列表/重命名/移除、配对嗅探任务、异步端口扫描。

- 注册以 IP 为粒度，重复 IP 拒绝（409 由路由层转换）
- 嗅探任务（ping sweep）在 daemon 线程跑独立事件循环，
  结果存内存 dict 供前端轮询；进程重启任务丢失可接受（重扫即可）
- 端口扫描在注册动作返回后的 daemon 线程执行 nmap top 1000，
  以 XML 输出解析落库；scan_status 状态机 pending→running→done/failed，
  nmap 缺失直接标记 unavailable（降级路径）
- 路由为 def（线程池）时，async 工具用 asyncio.run 现场起循环即可
"""

from __future__ import annotations

import asyncio
import logging
import socket
import sqlite3
import threading
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime

from web.backend.config import settings
from web.backend.db import db
from web.backend.services import lan_service

logger = logging.getLogger("homeagent.devices")

# 内存中的嗅探任务表：{scan_id: {"status": ..., "hosts": [{"ip", "suggested_name"}]}}
_scan_tasks: dict[str, dict] = {}
_scan_tasks_lock = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------- 注册表 CRUD ----------

def _ports_of(conn: sqlite3.Connection, device_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT port, protocol, service, version FROM device_ports"
        " WHERE device_id = ? ORDER BY port",
        (device_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_devices() -> list[dict]:
    """全部已注册设备（含端口列表，供三级展开）。"""
    with db() as conn:
        rows = conn.execute(
            "SELECT id, name, ip, mac, hostname, vendor, status, scan_status,"
            " registered_at, last_seen FROM devices ORDER BY ip"
        ).fetchall()
        devices = []
        for r in rows:
            d = dict(r)
            d["ports"] = _ports_of(conn, r["id"])
            devices.append(d)
    return devices


def register_device(ip: str, name: str | None) -> dict:
    """注册一台设备，立即返回；端口扫描转后台线程。重复 IP 抛 ConflictError。"""
    name = (name or "").strip() or ip  # 预填名称为空时以 IP 兜底
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO devices (name, ip, registered_at) VALUES (?, ?, ?)",
                (name, ip, _now()),
            )
            device_id = cur.lastrowid
    except sqlite3.IntegrityError as e:
        raise ConflictError(f"IP {ip} 已注册") from e
    logger.info("[LAN] 设备已注册: %s (%s) id=%s", name, ip, device_id)
    _start_port_scan(device_id, ip)
    return get_device(device_id)


def get_device(device_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT id, name, ip, mac, hostname, vendor, status, scan_status,"
            " registered_at, last_seen FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["ports"] = _ports_of(conn, device_id)
    return d


def rename_device(device_id: int, name: str) -> dict | None:
    name = (name or "").strip()
    if not name:
        raise ValueError("设备名称不能为空")
    with db() as conn:
        cur = conn.execute("UPDATE devices SET name = ? WHERE id = ?", (name, device_id))
        if cur.rowcount == 0:
            return None
    return get_device(device_id)


def remove_device(device_id: int) -> bool:
    """移除注册（device_ports 级联删除）。"""
    with db() as conn:
        return conn.execute("DELETE FROM devices WHERE id = ?", (device_id,)).rowcount > 0


# ---------- 在线状态 ----------

def refresh_status() -> tuple[list[dict], int]:
    """并发 ping 全部已注册设备，更新并返回状态与生效轮询间隔。"""
    with db() as conn:
        rows = conn.execute("SELECT id, ip, status FROM devices").fetchall()
    if not rows:
        return [], settings.lan.effective_ping_interval

    results = asyncio.run(
        lan_service.ping_sweep_ips([r["ip"] for r in rows])
    )
    now = _now()
    with db() as conn:
        for r, online in zip(rows, results):
            conn.execute(
                "UPDATE devices SET status = ?, last_seen = CASE WHEN ? THEN ? ELSE last_seen END"
                " WHERE id = ?",
                ("online" if online else "offline", online, now, r["id"]),
            )
    devices = [
        {"id": r["id"], "ip": r["ip"], "status": "online" if online else "offline",
         "changed": online != (r["status"] == "online")}
        for r, online in zip(rows, results)
    ]
    return devices, settings.lan.effective_ping_interval


# ---------- 配对嗅探任务 ----------

def start_discovery() -> str:
    """创建嗅探任务并立即返回 scan_id；ping sweep 在后台线程执行。"""
    scan_id = uuid.uuid4().hex[:12]
    with _scan_tasks_lock:
        _scan_tasks[scan_id] = {"status": "running", "hosts": []}

    def run() -> None:
        network = lan_service.detected_network()
        alive = asyncio.run(lan_service.ping_sweep(network))
        registered = {d["ip"] for d in list_devices_ips()}
        hosts = [
            {"ip": ip, "suggested_name": _suggest_name(ip)}
            for ip in alive
            if ip not in registered
        ]
        with _scan_tasks_lock:
            _scan_tasks[scan_id] = {"status": "done", "hosts": hosts}
        logger.info("[LAN] 嗅探任务 %s 完成: 网段 %s 存活 %d 台, 未注册 %d 台",
                    scan_id, network, len(alive), len(hosts))

    threading.Thread(target=run, name=f"discovery-{scan_id}", daemon=True).start()
    return scan_id


def get_discovery(scan_id: str) -> dict | None:
    with _scan_tasks_lock:
        task = _scan_tasks.get(scan_id)
        return dict(task) if task else None


def list_devices_ips() -> list[dict]:
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT id, ip FROM devices")]


def _suggest_name(ip: str) -> str:
    """建议名称：系统可解析的主机名，失败用 IP。"""
    try:
        return socket.gethostbyaddr(ip)[0].split(".")[0]
    except (socket.herror, socket.gaierror, OSError):
        return ip


# ---------- 异步端口扫描（daemon 线程） ----------

def _start_port_scan(device_id: int, ip: str) -> None:
    nmap = lan_service.find_nmap()
    if nmap is None:
        _set_scan_status(device_id, "unavailable")
        return

    def run() -> None:
        _set_scan_status(device_id, "running")
        try:
            ports, info = _nmap_top_ports(nmap, ip)
            with db() as conn:
                conn.execute("DELETE FROM device_ports WHERE device_id = ?", (device_id,))
                conn.executemany(
                    "INSERT OR IGNORE INTO device_ports (device_id, port, protocol, service, version)"
                    " VALUES (?, ?, ?, ?, ?)",
                    [(device_id, p["port"], p["protocol"], p["service"], p["version"]) for p in ports],
                )
                conn.execute(
                    "UPDATE devices SET scan_status = 'done', mac = ?, hostname = ?, vendor = ?"
                    " WHERE id = ?",
                    (info.get("mac"), info.get("hostname"), info.get("vendor"), device_id),
                )
            logger.info("[LAN] 设备 %s 端口扫描完成: %d 个端口", ip, len(ports))
        except Exception:
            _set_scan_status(device_id, "failed")
            logger.exception("[LAN] 设备 %s 端口扫描失败", ip)

    threading.Thread(target=run, name=f"nmap-{ip}", daemon=True).start()


def _set_scan_status(device_id: int, status: str) -> None:
    with db() as conn:
        conn.execute("UPDATE devices SET scan_status = ? WHERE id = ?", (status, device_id))


def _nmap_top_ports(nmap: str, ip: str, timeout_s: int = 600) -> tuple[list[dict], dict]:
    """nmap top 1000 端口 + 服务版本探测（-sV，XML 输出），返回 (端口列表, 主机信息)。"""
    returncode, stdout, stderr = asyncio.run(_run_nmap(nmap, ip, timeout_s))
    if returncode != 0:
        raise RuntimeError(f"nmap 退出码 {returncode}")
    if stderr.strip():
        logger.warning("[LAN] nmap stderr: %s", stderr.strip()[:200])
    root = ET.fromstring(stdout)
    host = root.find("host")
    if host is None:
        return [], {}

    info: dict = {}
    address = host.find("address[@addrtype='mac']")
    if address is not None:
        info["mac"] = (address.get("addr") or "").upper() or None
        vendor = address.get("vendor") or None
        if vendor:
            info["vendor"] = vendor
    hostname = host.find("hostnames/hostname")
    if hostname is not None and hostname.get("name"):
        info["hostname"] = hostname.get("name")

    ports = []
    for p in host.findall("ports/port"):
        state = p.find("state")
        if state is None or state.get("state") != "open":
            continue
        svc = p.find("service")
        version = None
        if svc is not None:
            version = " ".join(v for v in (svc.get("product"), svc.get("version")) if v)
            extra = svc.get("extrainfo")
            if extra:
                version = f"{version} ({extra})" if version else extra
        ports.append({
            "port": int(p.get("portid")),
            "protocol": p.get("protocol") or "tcp",
            "service": (svc.get("name") if svc is not None else None) or None,
            "version": version or None,
        })
    return ports, info


async def _run_nmap(nmap: str, ip: str, timeout_s: int) -> tuple[int, str, str]:
    """异步执行 nmap，返回 (退出码, stdout 文本, stderr 文本)。"""
    proc = await asyncio.create_subprocess_exec(
        nmap, "-sV", "-T4", "--top-ports", "1000", "-oX", "-", ip,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


class ConflictError(Exception):
    """业务冲突（如重复注册同一 IP），路由层转 409。"""
