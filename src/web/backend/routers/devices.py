"""设备注册表路由：/devices 相关 endpoint。

routers 只负责 HTTP 协议适配（解析请求 schema、调用 services、返回响应 schema），
不包含业务逻辑。全部接口要求登录，不限角色。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, IPvAnyAddress

from web.backend.routers.deps import get_current_user
from web.backend.services import device_service

router = APIRouter(prefix="/devices", tags=["devices"],
                   dependencies=[Depends(get_current_user)])


class DeviceRegisterIn(BaseModel):
    ip: IPvAnyAddress
    name: str | None = Field(default=None, max_length=64)


class DeviceRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


@router.post("/scan")
def start_discovery() -> dict:
    """创建配对嗅探任务（ping sweep），返回 scan_id 供轮询。"""
    return {"scan_id": device_service.start_discovery()}


@router.get("/scan/{scan_id}")
def get_discovery(scan_id: str) -> dict:
    """轮询嗅探任务状态与未注册主机结果。"""
    task = device_service.get_discovery(scan_id)
    if task is None:
        raise HTTPException(404, "嗅探任务不存在或已过期")
    return task


@router.get("")
def list_devices() -> list[dict]:
    """已注册设备列表（含端口，供三级展开）。"""
    return device_service.list_devices()


@router.post("", status_code=201)
def register_device(payload: DeviceRegisterIn) -> dict:
    """注册一台设备（立即返回，端口扫描在后台进行）。"""
    try:
        return device_service.register_device(str(payload.ip), payload.name)
    except device_service.ConflictError as e:
        raise HTTPException(409, str(e)) from e


@router.patch("/{device_id}")
def rename_device(device_id: int, payload: DeviceRenameIn) -> dict:
    """设备重命名。"""
    try:
        device = device_service.rename_device(device_id, payload.name)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if device is None:
        raise HTTPException(404, "设备不存在")
    return device


@router.delete("/{device_id}", status_code=204)
def remove_device(device_id: int) -> None:
    """移除注册（级联删除端口数据）。"""
    if not device_service.remove_device(device_id):
        raise HTTPException(404, "设备不存在")


@router.get("/status")
def refresh_status() -> dict:
    """并发 ping 全部已注册设备刷新在线状态，并下发轮询间隔。"""
    devices, interval = device_service.refresh_status()
    return {"devices": devices, "ping_interval": interval}
