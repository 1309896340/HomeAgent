"""路由层公共依赖：登录用户与管理员鉴权。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from web.backend.services import auth_service


def get_current_user(request: Request) -> dict:
    """从 Cookie 解析登录用户，未登录抛 401。"""
    user = auth_service.resolve_request_user(request)
    if user is None:
        raise HTTPException(401, "未登录或会话已过期")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """管理员专属接口的守卫。"""
    if user["role"] != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
