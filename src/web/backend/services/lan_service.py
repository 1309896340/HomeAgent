"""局域网工具层：网段自动检测、并发 ping 嗅探、nmap 可用性检测。

- 网段检测在启动时同步执行，结果以固定格式打印 console 日志，
  失败回退 .env 的 LAN.NETWORK（默认 192.168.3.0/24）
- ping 一律调系统命令并以退出码判定存活，不解析输出文本
  （Windows 输出受系统语言影响，退出码跨平台稳定）；
  Windows 上不需要管理员权限
- nmap 仅在启动时检测存在性；缺失时端口扫描功能降级，不影响 ping 发现
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import platform
import shutil
import socket

import psutil

from web.backend.config import settings

logger = logging.getLogger("homeagent.lan")

# ping 并发上限：网段 254 个地址一次打满太多，限流保平稳
PING_CONCURRENCY = 64

_detected_network: str | None = None


def _ipv4_addrs() -> list[tuple[str, str]]:
    """枚举本机全部 IPv4 地址，返回 [(接口名, 地址), ...]。"""
    result: list[tuple[str, str]] = []
    for ifname, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.address:
                result.append((ifname, addr.address))
    return result


def detect_network() -> str:
    """检测本机所在局域网网段（/24）。

    取第一个私网 IPv4（排除 loopback 与链路本地地址），
    固定格式打印 console 日志；失败回退 LAN.NETWORK 配置并 warning。
    """
    global _detected_network
    fallback = settings.lan.network
    for ifname, addr in _ipv4_addrs():
        ip = ipaddress.ip_address(addr)
        if not (ip.is_private and not ip.is_loopback and not ip.is_link_local):
            continue
        network = str(ipaddress.ip_network(f"{addr}/24", strict=False).network_address) + "/24"
        _detected_network = network
        logger.info("[LAN] 已自动检测到网段: %s (本机 IP: %s, 网卡: %s)", network, addr, ifname)
        return network
    _detected_network = fallback
    logger.warning("[LAN] 网段自动检测失败（未发现私网 IPv4），回退配置值: %s", fallback)
    return fallback


def detected_network() -> str:
    """当前生效网段（未检测过时现场检测一次）。"""
    return _detected_network if _detected_network is not None else detect_network()


def local_ips() -> set[str]:
    """本机全部 IPv4 地址（嗅探结果中排除自身）。"""
    return {addr for _, addr in _ipv4_addrs()}


def find_nmap() -> str | None:
    """按 NMAP_PATH -> PATH 顺序探测 nmap 可执行文件，缺失返回 None。"""
    configured = settings.lan.nmap_path.strip()
    if configured:
        if shutil.which(configured):
            return configured
        logger.warning("[LAN] NMAP_PATH=%s 不可用，改按 PATH 查找", configured)
    found = shutil.which("nmap")
    if found is None:
        logger.warning(
            "[LAN] 未找到 nmap，端口扫描功能降级不可用"
            "（ping 发现与设备注册不受影响；可安装后用 NMAP_PATH 指定路径）"
        )
    return found


def _ping_command(ip: str, timeout_s: float) -> list[str]:
    """单次 ping 的跨平台命令行参数。"""
    if platform.system() == "Windows":
        return ["ping", "-n", "1", "-w", str(int(timeout_s * 1000)), ip]
    return ["ping", "-c", "1", "-W", str(int(timeout_s)), ip]


async def ping_host(ip: str, timeout_s: float = 1.0) -> bool:
    """并发安全地 ping 单个地址，以退出码 0 判定存活。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            *_ping_command(ip, timeout_s),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError):
        return False
    try:
        return await asyncio.wait_for(proc.wait(), timeout=timeout_s + 2) == 0
    except asyncio.TimeoutError:
        proc.kill()
        return False


async def ping_sweep(network: str, timeout_s: float = 1.0) -> list[str]:
    """并发 ping 网段内全部地址，返回存活 IP 列表（升序，排除本机地址）。"""
    hosts = [str(h) for h in ipaddress.ip_network(network, strict=False).hosts()]
    return sorted(
        (ip for ip, alive in await _ping_many(hosts, timeout_s) if alive),
        key=ipaddress.ip_address,
    )


async def ping_sweep_ips(ips: list[str], timeout_s: float = 1.0) -> list[bool]:
    """并发 ping 给定 IP 列表，按入参顺序返回存活布尔值。"""
    return [alive for _, alive in await _ping_many(ips, timeout_s, keep_order=True)]


async def _ping_many(
    ips: list[str], timeout_s: float, keep_order: bool = False
) -> list[tuple[str, bool]]:
    skip = local_ips() if not keep_order else set()
    semaphore = asyncio.Semaphore(PING_CONCURRENCY)

    async def probe(ip: str) -> tuple[str, bool]:
        if ip in skip:
            return ip, False
        async with semaphore:
            return ip, await ping_host(ip, timeout_s)

    return list(await asyncio.gather(*(probe(ip) for ip in ips)))
