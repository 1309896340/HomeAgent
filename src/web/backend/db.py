"""SQLite 数据层：连接管理与建表。

- 数据库文件位于项目根目录 db/homeagent.db，目录不存在时自动创建
- WAL 模式提升并发读写表现；外键级联删除会话下的消息
- 连接按操作创建（本地 SQLite 开销极小），路由用 def（线程池）避免阻塞事件循环
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from web.backend.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
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


def init_schema() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
