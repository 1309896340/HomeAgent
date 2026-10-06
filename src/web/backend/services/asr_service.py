"""ASR 转写服务（本机 qwen3-asr Docker）。

实测规范（scripts/verify_asr.py + test_asr_matrix.py，2026-10-07）：
- 路由：POST {base}/audio/transcriptions，multipart（file 必填，language/prompt 可选，无 model 字段）
- 成功：200 {"text": str, "language": str}
- 失败：FastAPI 风格 {"detail": ...}（400 空文件 / 422 缺字段 / 500 转写失败 / 503 未就绪）
- health 在根路径 /health（无 /v1 前缀），backend_ready 表示模型就绪
- 本机 Docker 服务必须 trust_env=False，否则会被系统代理拦截返回假 503
- 静音/噪声输入会产生固定幻觉文本，调用方应预检（前端录音音量检查）
"""

from __future__ import annotations

import httpx

from web.backend.config import settings

# ASR_TIMEOUT: 长音频按 chunk_seconds=600 切分，给足上限
ASR_TIMEOUT = httpx.Timeout(300.0, connect=5.0)

# 固定热词引导（实测 prompt 显著纠正专有名词）
TRANSCRIBE_PROMPT = "HomeAgent、豆包、qwen3-asr、FastAPI 是本项目相关词汇。"


def _root_url() -> str:
    """去掉 /v1 后缀得到服务根（health 挂在根路径）。"""
    return settings.asr.base_url.rstrip("/").removesuffix("/v1")


class ASRError(RuntimeError):
    """ASR 调用失败（未就绪/网络/上游拒绝）。"""


async def check_ready() -> bool:
    """探测模型是否就绪（供前端置灰麦克风按钮）。"""
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5.0) as client:
            r = await client.get(f"{_root_url()}/health")
            data = r.json() if r.status_code == 200 else {}
            return bool(data.get("backend_ready") or data.get("model_loaded"))
    except (httpx.HTTPError, ValueError):
        return False


async def transcribe(filename: str, payload: bytes, mime: str) -> str:
    """转写音频字节，返回文本；任何失败抛 ASRError。"""
    if not payload:
        raise ASRError("音频内容为空")
    if not await check_ready():
        raise ASRError("语音识别服务未就绪（模型加载中或未启动），请稍后重试")

    url = f"{settings.asr.base_url.rstrip('/')}/audio/transcriptions"
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=ASR_TIMEOUT) as client:
            r = await client.post(
                url,
                files={"file": (filename, payload, mime)},
                data={"language": "zh", "prompt": TRANSCRIBE_PROMPT},
            )
    except httpx.HTTPError as e:
        raise ASRError(f"语音识别服务连接失败: {type(e).__name__}") from e

    if r.status_code != 200:
        detail = _extract_detail(r.text)
        raise ASRError(f"转写失败（{r.status_code}）: {detail}")
    try:
        return (r.json().get("text") or "").strip()
    except ValueError as e:
        raise ASRError("转写服务返回了无法解析的响应") from e


def _extract_detail(body: str) -> str:
    """从 FastAPI 风格错误体中提取人类可读信息。"""
    import json

    try:
        data = json.loads(body)
    except ValueError:
        return body[:200]
    detail = data.get("detail", body)
    if isinstance(detail, list):  # 422 校验错误数组
        return "; ".join(str(item.get("msg", item)) for item in detail)[:200]
    if isinstance(detail, dict):  # 500/503 {"error": ..., "exception": ...}
        return str(detail.get("error") or detail.get("exception") or detail)[:200]
    return str(detail)[:200]
