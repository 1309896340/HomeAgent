"""认证与用户管理路由。

/auth/*：注册、登录、登出、当前用户、修改密码
/admin/users*：管理员用户管理（require_admin），含保护规则：
  - 不能禁用/移除自己
  - 不能禁用/移除/降级最后一个启用的 admin
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from web.backend.db import db
from web.backend.routers.deps import get_current_user, require_admin
from web.backend.services import auth_service

router = APIRouter(tags=["auth"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        key=auth_service.COOKIE_NAME, value=token, max_age=max_age,
        httponly=True, samesite="lax", path="/",
    )


def _user_out(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
    }


def _fetch_user_by_id(user_id: str):
    with db() as conn:
        return conn.execute(
            """SELECT u.*, r.name AS role FROM users u
               JOIN roles r ON r.id = u.role_id WHERE u.id = ?""",
            (user_id,),
        ).fetchone()


# ---------- 请求模型 ----------

class RegisterBody(BaseModel):
    username: str
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=32)


class LoginBody(BaseModel):
    username: str
    password: str
    remember: bool = False


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


class AdminCreateUserBody(BaseModel):
    username: str
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=32)
    role: str = "member"


class AdminPatchUserBody(BaseModel):
    role: str | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=32)
    disabled: bool | None = None


# ---------- 认证 ----------

@router.post("/auth/register")
def register(body: RegisterBody, response: Response):
    if not re.fullmatch(auth_service.USERNAME_RE, body.username):
        raise HTTPException(400, "用户名需为 3~32 位字母、数字、下划线或连字符")
    username = body.username
    display_name = body.display_name.strip()
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise HTTPException(400, "用户名已被占用")
        role_id = conn.execute(
            "SELECT id FROM roles WHERE name = ?", ("admin" if count == 0 else "member",)
        ).fetchone()["id"]
        uid = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO users (id, username, display_name, password_hash, role_id, disabled, created_at)"
            " VALUES (?, ?, ?, ?, ?, 0, ?)",
            (uid, username, display_name or username, auth_service.hash_password(body.password), role_id, _now()),
        )
        if count == 0:
            # 首个用户（admin）认领历史遗留的公共对话数据
            conn.execute("UPDATE sessions SET user_id = ? WHERE user_id IS NULL", (uid,))

    user = _fetch_user_by_id(uid)
    token, max_age, _ = auth_service.issue_session(uid, remember=True)  # 注册即登录，长会话
    _set_session_cookie(response, token, max_age)
    return _user_out(user)


@router.post("/auth/login")
def login(body: LoginBody, response: Response):
    with db() as conn:
        row = conn.execute(
            """SELECT u.id, u.password_hash, u.disabled, u.username, u.display_name, r.name AS role
               FROM users u JOIN roles r ON r.id = u.role_id WHERE u.username = ?""",
            (body.username,),
        ).fetchone()
    if row is None or not auth_service.verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "用户名或密码错误")
    if row["disabled"]:
        raise HTTPException(403, "该账号已被禁用，请联系管理员")
    with db() as conn:
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_now(), row["id"]))
    token, max_age, _ = auth_service.issue_session(row["id"], body.remember)
    _set_session_cookie(response, token, max_age)
    return {"id": row["id"], "username": row["username"],
            "display_name": row["display_name"], "role": row["role"]}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth_service.COOKIE_NAME)
    if token:
        auth_service.revoke_session(token)
    response.delete_cookie(auth_service.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict = Depends(get_current_user)):
    return user


@router.post("/auth/change-password")
def change_password(body: ChangePasswordBody, user: dict = Depends(get_current_user)):
    row = _fetch_user_by_id(user["id"])
    if not auth_service.verify_password(body.old_password, row["password_hash"]):
        raise HTTPException(400, "旧密码不正确")
    with db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (auth_service.hash_password(body.new_password), user["id"]),
        )
    return {"ok": True}


# ---------- 管理员：用户管理 ----------

def _is_last_enabled_admin(conn, user_id: str) -> bool:
    """user_id 是否为最后一个启用状态的 admin（排除自身后统计）。"""
    target_role = conn.execute(
        """SELECT r.name AS role, u.disabled FROM users u
           JOIN roles r ON r.id = u.role_id WHERE u.id = ?""",
        (user_id,),
    ).fetchone()
    if target_role is None or target_role["role"] != "admin":
        return False
    others = conn.execute(
        """SELECT COUNT(*) AS c FROM users u JOIN roles r ON r.id = u.role_id
           WHERE r.name = 'admin' AND u.id != ? AND u.disabled = 0""",
        (user_id,),
    ).fetchone()["c"]
    return others == 0


def _validate_role(conn, role: str) -> None:
    if not conn.execute("SELECT 1 FROM roles WHERE name = ?", (role,)).fetchone():
        raise HTTPException(400, f"未知角色: {role}")


@admin_router.get("/users")
def list_users(_: dict = Depends(require_admin)):
    with db() as conn:
        rows = conn.execute(
            """SELECT u.id, u.username, u.display_name, u.disabled,
                      u.created_at, u.last_login_at, r.name AS role
               FROM users u JOIN roles r ON r.id = u.role_id
               ORDER BY u.created_at"""
        ).fetchall()
    return [dict(r) for r in rows]


@admin_router.post("/users")
def create_user(body: AdminCreateUserBody, _: dict = Depends(require_admin)):
    if not re.fullmatch(auth_service.USERNAME_RE, body.username):
        raise HTTPException(400, "用户名需为 3~32 位字母、数字、下划线或连字符")
    role = body.role if body.role else "member"
    with db() as conn:
        _validate_role(conn, role)
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (body.username,)).fetchone():
            raise HTTPException(400, "用户名已被占用")
        role_id = conn.execute("SELECT id FROM roles WHERE name = ?", (role,)).fetchone()["id"]
        uid = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO users (id, username, display_name, password_hash, role_id, disabled, created_at)"
            " VALUES (?, ?, ?, ?, ?, 0, ?)",
            (uid, body.username, body.display_name.strip() or body.username,
             auth_service.hash_password(body.password), role_id, _now()),
        )
    return {"id": uid}


@admin_router.patch("/users/{user_id}")
def patch_user(user_id: str, body: AdminPatchUserBody, admin: dict = Depends(require_admin)):
    with db() as conn:
        row = conn.execute(
            "SELECT u.*, r.name AS role FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "用户不存在")

        if body.disabled is not None:
            if user_id == admin["id"]:
                raise HTTPException(400, "不能禁用自己")
            if body.disabled and _is_last_enabled_admin(conn, user_id):
                raise HTTPException(400, "不能禁用最后一个管理员")
            conn.execute("UPDATE users SET disabled = ? WHERE id = ?",
                         (1 if body.disabled else 0, user_id))
            if body.disabled:
                conn.execute("DELETE FROM login_sessions WHERE user_id = ?", (user_id,))

        if body.role is not None and body.role != row["role"]:
            _validate_role(conn, body.role)
            if row["role"] == "admin" and _is_last_enabled_admin(conn, user_id) and not row["disabled"]:
                raise HTTPException(400, "不能降级最后一个管理员")
            role_id = conn.execute("SELECT id FROM roles WHERE name = ?", (body.role,)).fetchone()["id"]
            conn.execute("UPDATE users SET role_id = ? WHERE id = ?", (role_id, user_id))

        if body.display_name is not None:
            conn.execute("UPDATE users SET display_name = ? WHERE id = ?",
                         (body.display_name.strip() or row["username"], user_id))

        if body.password is not None:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                         (auth_service.hash_password(body.password), user_id))
            if user_id != admin["id"]:
                # 管理员重置他人密码后吊销其登录会话
                conn.execute("DELETE FROM login_sessions WHERE user_id = ?", (user_id,))

        updated = conn.execute(
            """SELECT u.id, u.username, u.display_name, u.disabled,
                      u.created_at, u.last_login_at, r.name AS role
               FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = ?""",
            (user_id,),
        ).fetchone()
    return dict(updated)


@admin_router.delete("/users/{user_id}")
def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    with db() as conn:
        row = conn.execute(
            "SELECT u.*, r.name AS role FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "用户不存在")
        if user_id == admin["id"]:
            raise HTTPException(400, "不能移除自己")
        if _is_last_enabled_admin(conn, user_id):
            raise HTTPException(400, "不能移除最后一个管理员")
        # 先删对话（messages 经外键级联），再删用户（login_sessions 经外键级联）
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {"ok": True}
