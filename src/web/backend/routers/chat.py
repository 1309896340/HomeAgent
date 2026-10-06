"""对话模块路由：会话 CRUD、消息历史、SSE 流式对话、语音转写。

SSE 事件协议（data: {json}\n\n）：
  {"type": "thinking_delta", "text": str}   思考过程增量
  {"type": "content_delta",  "text": str}   正文增量
  {"type": "tool_use", "name": str, "args": object}   工具调用（已执行）
  {"type": "error",          "message": str}
  {"type": "meta", "duration_ms": int, "prompt_tokens": int|None, ...}
  {"type": "done", "message_id": str, "status": "complete"|"error"}

agent loop：单条消息最多 MAX_AGENT_ROUNDS 轮工具调用；
meta 聚合全部轮次的 usage（T6 实测每轮各带一份，需累加）。
客户端中断（AbortController / 关闭页面 / 切走 tab）时，
服务端捕获 CancelledError，把已生成的部分内容落库并标记 interrupted。
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from web.backend.config import settings
from web.backend.db import db
from web.backend.schemas.chat import MessageCreate, SessionCreate, SessionUpdate
from web.backend.services import agent_tools, asr_service, skill_registry
from web.backend.services.llm_service import (
    ALLOWED_IMAGE_MIMES,
    LLMError,
    MAX_IMAGES,
    build_llm_messages,
    stream_chat,
)

router = APIRouter(prefix="/chat", tags=["chat"])

# agent loop 单条消息的最大工具轮数，防死循环
MAX_AGENT_ROUNDS = 5

AUDIO_EXT_MIMES = {
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    ".webm": "audio/webm", ".ogg": "audio/ogg", ".flac": "audio/flac",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _row_to_message(row) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "thinking": row["thinking"],
        "images": json.loads(row["images"]) if row["images"] else [],
        "duration_ms": row["duration_ms"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "total_tokens": row["total_tokens"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


# ---------- 会话管理 ----------

@router.get("/sessions")
def list_sessions():
    with db() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/sessions")
def create_session(body: SessionCreate):
    sid = uuid.uuid4().hex
    now = _now()
    with db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (sid, body.title.strip() or "新对话", now, now),
        )
    return {"id": sid, "title": body.title.strip() or "新对话", "created_at": now, "updated_at": now}


@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, body: SessionUpdate):
    with db() as conn:
        cur = conn.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (body.title.strip(), _now(), session_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "会话不存在")
    return {"ok": True}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    with db() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "会话不存在")
    return {"ok": True}


@router.get("/sessions/{session_id}/messages")
def list_messages(session_id: str):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
            raise HTTPException(404, "会话不存在")
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
    return [_row_to_message(r) for r in rows]


# ---------- 图片落盘 ----------

def _save_images(data_urls: list[str]) -> list[str]:
    """data URL -> db/uploads/{uuid}{ext}，返回可访问的相对 URL 列表。"""
    if len(data_urls) > MAX_IMAGES:
        raise HTTPException(400, f"每条消息最多 {MAX_IMAGES} 张图片")
    saved: list[str] = []
    upload_dir = settings.db_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    for url in data_urls:
        if not url.startswith("data:"):
            raise HTTPException(400, "图片必须以 data URL 形式提交")
        header, _, b64 = url.partition(",")
        mime = header[5:].split(";")[0].lower()
        ext = ALLOWED_IMAGE_MIMES.get(mime)
        if ext is None:
            raise HTTPException(400, f"不支持的图片类型: {mime}")
        try:
            raw = base64.b64decode(b64, validate=True)
        except ValueError as e:
            raise HTTPException(400, "图片 base64 解码失败") from e
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(400, "单张图片不能超过 5MB")
        name = f"{uuid.uuid4().hex}{ext}"
        (upload_dir / name).write_bytes(raw)
        saved.append(f"/api/chat/uploads/{name}")
    return saved


def _images_to_data_urls(urls: list[str]) -> list[str]:
    """把落盘的图片 URL 还原为 data URL（重新生成时重建上下文用）。"""
    out: list[str] = []
    for url in urls:
        name = url.rsplit("/", 1)[-1]
        path = settings.db_dir / "uploads" / name
        if not path.is_file():
            continue
        mime = next((m for m, e in ALLOWED_IMAGE_MIMES.items() if path.suffix == e), "image/png")
        out.append(f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}")
    return out


# ---------- 流式对话 ----------

async def _chat_event_stream(session_id: str, history: list[dict], content: str, images: list[str]):
    """SSE 生成器：agent loop（流式输出 + 工具调用多轮），结束时按状态落库。

    事件流：thinking_delta / content_delta / tool_use / usage（透传）/
    meta（聚合全部轮次的 usage 与总耗时）/ done。
    """
    start = time.perf_counter()
    thinking_parts: list[str] = []
    content_parts: list[str] = []
    usage_sums = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    usage_seen = False
    saved = {"done": False}

    def save(status: str) -> str:
        saved["done"] = True
        mid = uuid.uuid4().hex
        duration_ms = int((time.perf_counter() - start) * 1000)
        u = usage_sums if usage_seen else None
        with db() as conn:
            conn.execute(
                """INSERT INTO messages
                   (id, session_id, role, content, thinking, images, duration_ms,
                    prompt_tokens, completion_tokens, total_tokens, status, created_at)
                   VALUES (?, ?, 'assistant', ?, ?, NULL, ?, ?, ?, ?, ?, ?)""",
                (
                    mid, session_id, "".join(content_parts), "".join(thinking_parts) or None,
                    duration_ms,
                    u and u["prompt_tokens"], u and u["completion_tokens"], u and u["total_tokens"],
                    status, _now(),
                ),
            )
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (_now(), session_id))
        return mid

    def meta_event() -> dict:
        u = usage_sums if usage_seen else None
        return {
            "type": "meta",
            "duration_ms": int((time.perf_counter() - start) * 1000),
            "prompt_tokens": u and u["prompt_tokens"],
            "completion_tokens": u and u["completion_tokens"],
            "total_tokens": u and u["total_tokens"],
        }

    messages = build_llm_messages(history, content, images, skill_registry.list_skills())
    tools = agent_tools.build_tool_specs()
    try:
        for _round in range(MAX_AGENT_ROUNDS):
            round_content: list[str] = []
            round_calls: list[dict] = []
            async for ev in stream_chat(messages, tools):
                if ev["type"] == "thinking_delta":
                    thinking_parts.append(ev["text"])
                elif ev["type"] == "content_delta":
                    content_parts.append(ev["text"])
                    round_content.append(ev["text"])
                elif ev["type"] == "usage":
                    usage_seen = True
                    for k in usage_sums:
                        if ev.get(k):
                            usage_sums[k] += ev[k]
                elif ev["type"] == "tool_calls":
                    round_calls = ev["calls"]
                yield _sse(ev)

            if not round_calls:
                break

            # 执行本轮全部工具调用（白名单见 agent_tools），错误作为结果回传给模型自愈
            assistant_calls = []
            tool_msgs = []
            for call in round_calls:
                try:
                    args = json.loads(call["arguments"] or "{}")
                except ValueError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                result = agent_tools.execute_tool(call["name"], args)
                yield _sse({"type": "tool_use", "name": call["name"], "args": args})
                assistant_calls.append({
                    "id": call["id"], "type": "function",
                    "function": {"name": call["name"], "arguments": call["arguments"] or "{}"},
                })
                tool_msgs.append({"role": "tool", "tool_call_id": call["id"], "content": result})
            messages.append({
                "role": "assistant",
                "content": "".join(round_content) or None,
                "tool_calls": assistant_calls,
            })
            messages.extend(tool_msgs)

        mid = save("complete")
        yield _sse(meta_event())
        yield _sse({"type": "done", "message_id": mid, "status": "complete"})
    except (asyncio.CancelledError, GeneratorExit):
        # 客户端断开 / 切走 tab：保留已生成部分，标记中断
        save("interrupted")
        raise
    except LLMError as e:
        yield _sse({"type": "error", "message": str(e)})
        mid = save("error")
        yield _sse(meta_event())
        yield _sse({"type": "done", "message_id": mid, "status": "error"})


def _require_session(session_id: str) -> None:
    with db() as conn:
        if not conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
            raise HTTPException(404, "会话不存在")


@router.post("/sessions/{session_id}/messages")
async def post_message(session_id: str, body: MessageCreate):
    _require_session(session_id)
    content = body.content.strip()
    if not content and not body.images:
        raise HTTPException(400, "消息内容不能为空")
    image_urls = _save_images(body.images)

    with db() as conn:
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, images, status, created_at)"
            " VALUES (?, ?, 'user', ?, ?, 'complete', ?)",
            (uuid.uuid4().hex, session_id, content, json.dumps(image_urls) if image_urls else None, _now()),
        )
        # 首条用户消息自动作为会话标题（前 20 字），之后可手动重命名覆盖
        if content:
            row = conn.execute("SELECT title FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row and row["title"] in ("新对话", ""):
                conn.execute(
                    "UPDATE sessions SET title = ? WHERE id = ?", (content[:20], session_id)
                )
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (_now(), session_id))
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
    # 历史不含刚插入的这条（它作为当前消息单独携带）
    history = [{"role": r["role"], "content": r["content"]} for r in rows[:-1]]

    return StreamingResponse(
        _chat_event_stream(session_id, history, content, body.images),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/regenerate")
async def regenerate(session_id: str):
    """删除最后一条助手消息并重新生成（上下文止于其对应的用户消息）。"""
    _require_session(session_id)
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
    if not rows or rows[-1]["role"] != "assistant":
        raise HTTPException(400, "最后一条消息不是助手消息，无法重新生成")
    last_user = next((r for r in reversed(rows) if r["role"] == "user"), None)
    if last_user is None:
        raise HTTPException(400, "找不到对应的用户消息")

    with db() as conn:
        conn.execute("DELETE FROM messages WHERE id = ?", (rows[-1]["id"],))

    history = [{"role": r["role"], "content": r["content"]} for r in rows[:-1]]
    images = _images_to_data_urls(json.loads(last_user["images"]) if last_user["images"] else [])
    # 当前消息即最后这条用户消息：从历史里摘出，避免重复
    if history and history[-1]["role"] == "user":
        current = history.pop()
        content = current["content"]
    else:
        content = last_user["content"]

    return StreamingResponse(
        _chat_event_stream(session_id, history, content, images),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- 语音转写 ----------

@router.get("/asr/status")
async def asr_status():
    return {"ready": await asr_service.check_ready()}


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile):
    payload = await file.read()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in AUDIO_EXT_MIMES:
        mime = (file.content_type or "").split(";")[0].strip().lower()
        suffix = next((e for e, m in AUDIO_EXT_MIMES.items() if m == mime), ".bin")
    # 开发阶段缓存音频，便于重复调试（data/audio_input/，时间戳命名）
    settings.audio_input_dir.mkdir(parents=True, exist_ok=True)
    out = settings.audio_input_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{suffix}"
    out.write_bytes(payload)
    try:
        text = await asr_service.transcribe(
            file.filename or f"audio{suffix}", payload, file.content_type or "application/octet-stream"
        )
    except asr_service.ASRError as e:
        raise HTTPException(503, str(e)) from e
    return {"text": text}
