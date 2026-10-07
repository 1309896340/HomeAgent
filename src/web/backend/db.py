"""SQLite 数据层：连接管理、建表与迁移。

- 数据库文件位于项目根目录 db/homeagent.db，目录不存在时自动创建
- WAL 模式提升并发读写表现；外键级联删除
- 连接按操作创建（本地 SQLite 开销极小），路由用 def（线程池）避免阻塞事件循环
- 用户体系：roles/users/login_sessions 三表；对话 sessions 通过
  user_id（可空列，启动时迁移补齐）归属用户，未认领数据由第一个注册用户继承
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from web.backend.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS roles (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT,
    password_hash TEXT NOT NULL,
    role_id       INTEGER NOT NULL REFERENCES roles(id),
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS login_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_sessions_user ON login_sessions(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    user_id    TEXT REFERENCES users(id),
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id                TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role              TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content           TEXT NOT NULL DEFAULT '',
    thinking          TEXT,
    images            TEXT,
    duration_ms       INTEGER,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER,
    status            TEXT NOT NULL DEFAULT 'complete'
                      CHECK (status IN ('complete', 'interrupted', 'error')),
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
"""

SEED_ROLES = ("admin", "member", "guest")


def ensure_dirs() -> None:
    """启动时确保 db/、db/uploads/ 目录存在。"""
    (settings.db_dir / "uploads").mkdir(parents=True, exist_ok=True)


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """打开一个启用了 WAL/外键/行工厂的连接，用完即关。"""
    ensure_dirs()
    conn = sqlite3.connect(settings.db_dir / "homeagent.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """增量迁移：为已有库补齐新列/索引（幂等）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
    if "user_id" not in cols:
        # 旧库没有 user_id：可空列，历史数据保持 NULL，由第一个注册用户认领
        conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT REFERENCES users(id)")
    # user_id 可能来自本次 ALTER，索引必须在迁移之后建
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")


def init_schema() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR IGNORE INTO roles (name) VALUES (?)",
            [(r,) for r in SEED_ROLES],
        )
        _migrate(conn)
