"""ASR 服务（qwen3-asr Docker @12301）验证脚本。

实测路由（源码 /app/app.py，镜像 README 的 chat/completions 示例与实际不符）：
  GET  /health                     健康检查（含模型加载状态）
  POST /v1/audio/transcriptions    OpenAI 风格 multipart 上传转写
       form 字段: file(必填) / language / prompt / response_format / timestamp_granularities[]
       （无 model 字段，服务固定使用加载好的 Qwen3-ASR-1.7B）
  错误格式: HTTPException {"detail": ...}（400 空文件或非法输入 / 503 未就绪 / 500 / 507 OOM）

验证目标：
  P0  服务探测：/health 状态与字段
  T1  WAV 转写（multipart 上传，后端转发录音的标准路径）
  T2  webm/opus 转写（浏览器 MediaRecorder 录音格式）
  T3  language="zh" 参数对照（是否提升中文效果）
  T4  异常请求探测：缺 file / 空文件 / 垃圾二进制 / 未就绪时行为推断

用法（项目根目录执行）：
  uv run python scripts/verify_asr.py
  uv run python scripts/verify_asr.py --only P0,T1
  uv run python scripts/verify_asr.py --wait 900   # 最长等待模型加载秒数

注意：本机 Docker 服务请求必须绕过系统代理（trust_env=False），
否则 HTTP_PROXY 会拦截 127.0.0.1 请求返回 503。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import httpx

from web.backend.config import settings

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ASSET_WAV = Path(__file__).parent / "assets" / "asr_test_zh.wav"
ASSET_TEXT = "你好，这是家庭智能助手的语音识别测试，今天天气不错。"

results: list[tuple[str, str, str]] = []  # (用例, 状态, 摘要)


def record(name: str, ok: bool, summary: str) -> None:
    results.append((name, "PASS" if ok else "FAIL", summary))


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def client_no_proxy() -> httpx.Client:
    """本机服务直连：显式禁用环境代理。"""
    return httpx.Client(trust_env=False, timeout=300)


def transcribe_url() -> str:
    return f"{settings.asr.base_url.rstrip('/')}/audio/transcriptions"


def call_transcribe(client: httpx.Client, *, filename: str, payload: bytes,
                    mime: str, extra: dict | None = None, timeout: float = 300) -> httpx.Response:
    data = {"language": "zh"} if extra is None else extra
    return client.post(
        transcribe_url(),
        files={"file": (filename, payload, mime)},
        data=data,
        timeout=timeout,
    )


def get_health(client: httpx.Client) -> dict:
    """health 挂在根路径（/health），不带 /v1 前缀。"""
    url = f"{settings.asr.base_url.rstrip('/').removesuffix('/v1')}/health"
    try:
        r = client.get(url, timeout=10)
        return r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {}


def wait_model_ready(client: httpx.Client, max_wait: int) -> bool:
    """轮询 /health 直到 backend_ready / model_loaded，返回是否就绪。"""
    deadline = time.monotonic() + max_wait
    last_line = ""
    while time.monotonic() < deadline:
        h = get_health(client)
        if not h:
            print("[health] 响应异常，5s 后重试")
            time.sleep(5)
            continue
        ready = h.get("backend_ready") or h.get("model_loaded")
        line = f"status={h.get('status')} state={h.get('backend_state')} model={h.get('model_id')}"
        if line != last_line:
            print(f"[health] {line}")
            last_line = line
        if ready:
            print("[health] 模型就绪")
            return True
        time.sleep(5)
    print(f"[health] 等待 {max_wait}s 超时，模型仍未就绪")
    return False


def show_response(r: httpx.Response, elapsed: float) -> str:
    """打印响应并提取转写文本。"""
    print(f"  HTTP {r.status_code} {r.headers.get('content-type', '')} 耗时 {elapsed:.2f}s")
    print(f"  body[:400]: {r.text[:400]}")
    if r.status_code != 200:
        return ""
    try:
        data = r.json()
    except ValueError:
        return r.text.strip()
    if not isinstance(data, dict):
        return str(data)
    text = data.get("text", "")
    extra = {k: v for k, v in data.items() if k != "text"}
    if extra:
        print(f"  text 之外的额外字段: {list(extra)}")
    return text or ""


def test_wav(client: httpx.Client) -> None:
    section("T1 WAV 转写（multipart + language=zh）")
    dur = wav_duration_seconds(ASSET_WAV)
    payload = ASSET_WAV.read_bytes()
    print(f"素材: {ASSET_WAV.name} 时长 {dur:.1f}s 大小 {len(payload)}B，内容: {ASSET_TEXT}")
    t0 = time.perf_counter()
    try:
        r = call_transcribe(client, filename="asr_test_zh.wav", payload=payload, mime="audio/wav")
    except httpx.HTTPError as e:
        record("T1 wav", False, f"请求异常 {type(e).__name__}: {e}")
        return
    elapsed = time.perf_counter() - t0
    text = show_response(r, elapsed)
    if r.status_code == 200 and text:
        hit = sum(1 for ch in set(ASSET_TEXT) if ch in text)
        print(f"  转写结果: {text}")
        print(f"  字符命中率(粗略): {hit}/{len(set(ASSET_TEXT))}")
        record("T1 wav", True, f"{elapsed:.1f}s, RTF≈{elapsed / dur:.2f}")
    else:
        record("T1 wav", False, f"status={r.status_code}")


def test_webm(client: httpx.Client) -> None:
    section("T2 webm/opus 转写（浏览器 MediaRecorder 录音格式）")
    with tempfile.TemporaryDirectory() as td:
        webm = Path(td) / "test.webm"
        conv = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(ASSET_WAV),
             "-c:a", "libopus", "-b:a", "32k", str(webm)],
            capture_output=True, text=True,
        )
        if conv.returncode != 0 or not webm.exists():
            print(f"  ffmpeg 转换失败(跳过): {conv.stderr[:200]}")
            record("T2 webm", False, "ffmpeg 转换失败")
            return
        print(f"  已生成 webm 副本 {webm.stat().st_size} bytes")
        t0 = time.perf_counter()
        try:
            r = call_transcribe(client, filename="record.webm",
                                payload=webm.read_bytes(), mime="audio/webm")
        except httpx.HTTPError as e:
            record("T2 webm", False, f"请求异常 {type(e).__name__}: {e}")
            return
        elapsed = time.perf_counter() - t0
        text = show_response(r, elapsed)
        ok = r.status_code == 200 and len(text) >= 5
        print(f"  转写结果: {text or '(空)'}")
        record("T2 webm", ok, f"status={r.status_code}, text='{text[:30]}'")


def test_no_language(client: httpx.Client) -> None:
    section("T3 不带 language 参数对照")
    t0 = time.perf_counter()
    try:
        r = call_transcribe(client, filename="asr_test_zh.wav",
                            payload=ASSET_WAV.read_bytes(), mime="audio/wav", extra={})
    except httpx.HTTPError as e:
        record("T3 no-lang", False, f"请求异常 {type(e).__name__}: {e}")
        return
    elapsed = time.perf_counter() - t0
    text = show_response(r, elapsed)
    print(f"  转写结果: {text or '(空)'}")
    record("T3 no-lang", r.status_code == 200, f"status={r.status_code}, text='{text[:30]}'")


def test_errors(client: httpx.Client) -> None:
    section("T4 异常请求探测（摸清错误格式）")
    try:
        r = client.post(transcribe_url(), data={"language": "zh"}, timeout=60)
        print(f"a) 缺 file 字段 -> {r.status_code}\n   {r.text[:300]}")
        r = call_transcribe(client, filename="empty.wav", payload=b"", mime="audio/wav", timeout=60)
        print(f"b) 空文件       -> {r.status_code}\n   {r.text[:300]}")
        r = call_transcribe(client, filename="garbage.wav", payload=b"\x00" * 2048,
                            mime="audio/wav", timeout=120)
        print(f"c) 垃圾二进制   -> {r.status_code}\n   {r.text[:300]}")
        r = call_transcribe(client, filename="note.txt", payload=b"hello not audio",
                            mime="text/plain", timeout=120)
        print(f"d) 文本文件     -> {r.status_code}\n   {r.text[:300]}")
        record("T4 errors", True, "错误格式已采集（见上方输出）")
    except httpx.HTTPError as e:
        record("T4 errors", False, f"请求异常 {type(e).__name__}: {e}")


def summarize() -> None:
    section("汇总")
    width = max(len(n) for n, _, _ in results) if results else 10
    for name, status, summary in results:
        print(f"{name:<{width}}  {status}  {summary}")
    print(
        f"\n[规范化结论模板]（依据实测结果在后端落地确认）\n"
        f"  请求: POST {transcribe_url()}  multipart: file=(name, bytes, mime)，form 附 language=zh\n"
        "  成功: 200 + JSON {'text': <str>}（额外字段以实测为准）\n"
        "  失败: FastAPI 风格 {{'detail': ...}}，统一解析出错误消息抛业务异常\n"
        "  后端要点: ① httpx 必须 trust_env=False（本机服务绕过系统代理）\n"
        "            ② 转写前查 /health 的 backend_ready，未就绪返回友好错误\n"
        "            ③ 服务无 model 字段，固定 Qwen3-ASR-1.7B，并发=1（health.max_concurrent_transcribe）"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="只跑指定用例，逗号分隔，如 P0,T1")
    parser.add_argument("--wait", type=int, default=600, help="等待模型加载的最长秒数")
    args = parser.parse_args()
    todo = {s.strip() for s in args.only.split(",")} if args.only else None

    print(f"ASR 端点: {transcribe_url()}")

    with client_no_proxy() as client:
        section("P0 服务探测")
        h = get_health(client)
        keys = ("status", "backend_ready", "backend_state", "model_id",
                "max_concurrent_transcribe", "chunk_seconds")
        print(f"/health 关键字段: {{{', '.join(f'{k}: {h.get(k)!r}' for k in keys)}}}")

        if not wait_model_ready(client, args.wait):
            print("模型未就绪，仅执行异常探测用例")
        if not todo or "T1" in todo:
            test_wav(client)
        if not todo or "T2" in todo:
            test_webm(client)
        if not todo or "T3" in todo:
            test_no_language(client)
        if not todo or "T4" in todo:
            test_errors(client)
    summarize()


if __name__ == "__main__":
    main()
