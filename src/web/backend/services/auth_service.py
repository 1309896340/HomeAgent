"""认证服务：scrypt 密码哈希 + SQLite 登录会话令牌。

- 密码：hashlib.scrypt（随机盐），存储格式 "scrypt$n$r$p$salthex$hashhex"
- 登录会话：随机 token 放 httpOnly Cookie，库中只存 sha256(token)；
  记住我 30 天 / 默认 24 小时
- 禁用用户：login 时明确拒绝；已发会话在解析时一并拒绝并清理
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import Request

from web.backend.db import db

COOKIE_NAME = "ha_session"
REMEMBER_MAX_AGE = 30 * 24 * 3600
DEFAULT_MAX_AGE = 24 * 3600

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1

USERNAME_RE = r"[A-Za-z0-9_-]{3,32}"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p),
        )
        return hmac.compare_digest(derived, bytes.fromhex(hash_hex))
    except (ValueError, TypeError):
        return False


def _now() -> datetime:
    return datetime.now()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(user_id: str, remember: bool) -> tuple[str, int, str]:
    """签发登录会话，返回 (token, cookie_max_age, expires_at_iso)。"""
    token = secrets.token_urlsafe(32)
    max_age = REMEMBER_MAX_AGE if remember else DEFAULT_MAX_AGE
    expires_at = (_now() + timedelta(seconds=max_age)).isoformat(timespec="seconds")
    with db() as conn:
        conn.execute(
            "INSERT INTO login_sessions (token_hash, user_id, expires_at, created_at)"
            " VALUES (?, ?, ?, ?)",
            (_hash_token(token), user_id, expires_at, _now().isoformat(timespec="seconds")),
        )
    return token, max_age, expires_at


def revoke_session(token: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM login_sessions WHERE token_hash = ?", (_hash_token(token),))


def revoke_all_for_user(user_id: str) -> None:
    """吊销某用户全部登录会话（禁用账号/移除用户时调用）。"""
    with db() as conn:
        conn.execute("DELETE FROM login_sessions WHERE user_id = ?", (user_id,))


def resolve_request_user(request: Request) -> dict | None:
    """从 Cookie 解析当前登录用户；无效/过期/禁用一律返回 None 并清理残留。"""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    with db() as conn:
        row = conn.execute(
            """SELECT u.id, u.username, u.display_name, u.disabled, r.name AS role,
                      ls.token_hash, ls.expires_at
               FROM login_sessions ls
               JOIN users u ON u.id = ls.user_id
               JOIN roles r ON r.id = u.role_id
               WHERE ls.token_hash = ?""",
            (_hash_token(token),),
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] < _now().isoformat(timespec="seconds"):
            conn.execute("DELETE FROM login_sessions WHERE token_hash = ?", (row["token_hash"],))
            return None
        if row["disabled"]:
            conn.execute("DELETE FROM login_sessions WHERE user_id = ?", (row["id"],))
            return None
    return {"id": row["id"], "username": row["username"],
            "display_name": row["display_name"], "role": row["role"]}
