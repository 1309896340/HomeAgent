"""ASR 能力矩阵测试（qwen3-asr @12301）。

在 verify_asr.py（端点行为验证）基础上，用多样素材测试真实转写能力：
  M1 格式矩阵：wav/mp3/m4a/flac/ogg/8kHz 电话音质（同一中文文本）
  M2 英文转写：language=en 与不带参数对照
  M3 长音频：60s+ 中文（耗时与 RTF）
  M4 边界输入：静音 / 纯噪声
  M5 prompt 热词引导：含专有名词句子，带 prompt 与不带对照
  M6 并发排队：同时发 3 个请求（服务 max_concurrent_transcribe=1）

素材自动生成到 data/test_audio/（gitignored），--regen 强制重建。

用法（项目根目录）：
  uv run python scripts/test_asr_matrix.py
  uv run python scripts/test_asr_matrix.py --only M1,M5
  uv run python scripts/test_asr_matrix.py --regen
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from web.backend.config import settings

# Windows 控制台默认 GBK，重配为 UTF-8；isinstance 兼作类型收窄（TextIO 无 reconfigure）
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "data" / "test_audio"
SRC_WAV = Path(__file__).parent / "assets" / "asr_test_zh.wav"
SRC_TEXT = "你好，这是家庭智能助手的语音识别测试，今天天气不错。"

LONG_TEXT = (
    "智能家居系统通过物联网技术把家中的各种设备连接起来，包括灯光、窗帘、空调、"
    "安防摄像头和音箱。用户可以用手机远程控制，也可以通过语音助手完成操作。"
    "系统还能学习用户的作息习惯，在清晨自动拉开窗帘，在夜里自动关闭所有的灯。"
    "当传感器检测到家中无人时，安防模式会自动开启，摄像头开始录像，"
    "门锁也会进入戒备状态。所有这些设备的运行数据都会汇总到家庭网关，"
    "用户可以在仪表盘上查看每个设备的状态，还可以设置自动化规则，"
    "让不同的设备协同工作，比如温度超过二十八度的时候自动开空调，"
    "pm二点五超过七十五的时候自动开启空气净化器。"
    "未来智能家居还会接入更多的人工智能能力，让家变得更懂你。"
)

EN_TEXT = "Hello, this is a voice recognition test for the home agent project. The weather is nice today."

HOTWORD_TEXT = "请帮我把 HomeAgent 的豆包模型切换到 qwen3-asr。"
HOTWORD_PROMPT = "HomeAgent 豆包 qwen3-asr 是智能助手项目里的专有名词。"

results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, summary: str) -> None:
    results.append((name, "PASS" if ok else "FAIL", summary))


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def tts(text: str, out: Path, voice_hint: str) -> bool:
    """调用 Windows System.Speech 生成 WAV（16kHz 16bit mono）。"""
    ps = f"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $s.GetInstalledVoices() | ForEach-Object {{ $_.VoiceInfo.Name }}
$pick = $voices | Where-Object {{ $_ -match '{voice_hint}' }} | Select-Object -First 1
if ($pick) {{ $null = $s.SelectVoice($pick) }} else {{ Write-Host 'no voice match, use default' }}
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile('{out.as_posix()}', $fmt)
$s.Speak('{text.replace("'", "''")}')
$s.Dispose()
"""
    r = run(["powershell", "-NoProfile", "-Command", ps])
    ok = out.exists() and out.stat().st_size > 10000
    if not ok:
        print(f"  [TTS 失败] {out.name}: {r.stderr[:200]}")
    return ok


def ffmpeg(src: Path, out: Path, *args: str) -> bool:
    r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), *args, str(out)])
    if r.returncode != 0 or not out.exists():
        print(f"  [ffmpeg 失败] {out.name}: {r.stderr[:200]}")
        return False
    return True


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def prepare_fixtures(regen: bool) -> dict[str, Path]:
    section("素材准备（data/test_audio/）")
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    fx: dict[str, Path] = {}

    def cached(name: str) -> Path | None:
        p = FIXTURE_DIR / name
        if regen and p.exists():
            p.unlink()
        return None if p.exists() else p

    # 格式矩阵：从已验证的中文 wav 转出
    conv_specs = {
        "fmt_mp3.wav.mp3": ("f_mp3.mp3", ["-c:a", "libmp3lame", "-b:a", "64k"]),
        "f_m4a.m4a": ("f_m4a.m4a", ["-c:a", "aac", "-b:a", "64k"]),
        "f_flac.flac": ("f_flac.flac", ["-c:a", "flac"]),
        "f_ogg.ogg": ("f_ogg.ogg", ["-c:a", "libvorbis", "-b:a", "64k"]),
        "f_8k.mp3": ("f_8k.mp3", ["-ar", "8000", "-c:a", "libmp3lame", "-b:a", "24k"]),
    }
    for _, (fname, fargs) in conv_specs.items():
        out = FIXTURE_DIR / fname
        if not out.exists() and not ffmpeg(SRC_WAV, out, *fargs):
            continue
        fx[fname] = out
    fx["f_wav.wav"] = SRC_WAV

    # 英文 / 长文本 / 热词句（TTS）
    tts_jobs = {
        "en.wav": (EN_TEXT, "Zira|en-US|English"),
        "long.wav": (LONG_TEXT, "Huihui|zh-CN|Chinese"),
        "hotword.wav": (HOTWORD_TEXT, "Huihui|zh-CN|Chinese"),
    }
    for fname, (text, hint) in tts_jobs.items():
        out = FIXTURE_DIR / fname
        if not out.exists() and not tts(text, out, hint):
            continue
        fx[fname] = out

    # 静音 / 噪声
    silent = FIXTURE_DIR / "silent.wav"
    if not silent.exists():
        r = run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                 "anullsrc=r=16000:cl=mono", "-t", "3", "-c:a", "pcm_s16le", str(silent)])
        if r.returncode == 0:
            fx["silent.wav"] = silent
    else:
        fx["silent.wav"] = silent
    noise = FIXTURE_DIR / "noise.wav"
    if not noise.exists():
        r = run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                 "anoisesrc=r=16000:d=3:a=0.5", "-ac", "1",
                 "-c:a", "pcm_s16le", str(noise)])
        if r.returncode == 0:
            fx["noise.wav"] = noise
    else:
        fx["noise.wav"] = noise

    for name, p in sorted(fx.items()):
        try:
            dur = wav_duration(p) if p.suffix == ".wav" else 0
            extra = f" {dur:.1f}s" if dur else ""
            print(f"  {name:<14} {p.stat().st_size:>9}B{extra}")
        except OSError:
            pass
    return fx


def client_no_proxy() -> httpx.Client:
    return httpx.Client(trust_env=False, timeout=300)


def transcribe_url() -> str:
    return f"{settings.asr.base_url.rstrip('/')}/audio/transcriptions"


def transcribe(client: httpx.Client, path: Path, mime: str,
               language: str | None = "zh", prompt: str | None = None) -> tuple[int, str]:
    data: dict[str, str] = {}
    if language:
        data["language"] = language
    if prompt:
        data["prompt"] = prompt
    r = client.post(transcribe_url(), files={"file": (path.name, path.read_bytes(), mime)},
                    data=data, timeout=300)
    text = ""
    if r.status_code == 200:
        try:
            text = r.json().get("text", "")
        except ValueError:
            text = r.text[:100]
    return r.status_code, text


def mime_of(path: Path) -> str:
    return {
        ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".flac": "audio/flac",
        ".ogg": "audio/ogg", ".wav": "audio/wav",
    }.get(path.suffix, "application/octet-stream")


def hit_rate(text: str) -> tuple[int, int]:
    hit = sum(1 for ch in set(SRC_TEXT) if ch in text)
    return hit, len(set(SRC_TEXT))


def test_formats(client: httpx.Client, fx: dict[str, Path]) -> None:
    section("M1 格式矩阵（同一中文文本）")
    for key in ("f_wav.wav", "f_mp3.mp3", "f_m4a.m4a", "f_flac.flac", "f_ogg.ogg", "f_8k.mp3"):
        p = fx.get(key)
        if not p:
            record(f"M1 {key}", False, "素材缺失")
            continue
        t0 = time.perf_counter()
        try:
            status, text = transcribe(client, p, mime_of(p))
        except httpx.HTTPError as e:
            record(f"M1 {key}", False, f"异常 {type(e).__name__}")
            continue
        elapsed = time.perf_counter() - t0
        hit, total = hit_rate(text)
        ok = status == 200 and hit >= total - 2
        print(f"  {key:<10} {status} {elapsed:5.2f}s  命中 {hit}/{total}  {text[:40]}")
        record(f"M1 {key}", ok, f"{elapsed:.1f}s 命中{hit}/{total}")


def test_english(client: httpx.Client, fx: dict[str, Path]) -> None:
    section("M2 英文转写（Zira 女声）")
    p = fx.get("en.wav")
    if not p:
        record("M2 english", False, "素材缺失")
        return
    print(f"  原文: {EN_TEXT}")
    for label, lang in (("language=en", "en"), ("不带language", None)):
        t0 = time.perf_counter()
        try:
            status, text = transcribe(client, p, "audio/wav", language=lang)
        except httpx.HTTPError as e:
            record(f"M2 {label}", False, f"异常 {type(e).__name__}")
            continue
        elapsed = time.perf_counter() - t0
        words = set(EN_TEXT.lower().replace(",", "").replace(".", "").split())
        hit = sum(1 for w in words if w in text.lower())
        print(f"  [{label}] {status} {elapsed:5.2f}s  词命中 {hit}/{len(words)}\n    {text[:120]}")
        record(f"M2 {label}", status == 200 and hit >= len(words) - 3,
               f"词命中{hit}/{len(words)}")


def test_long(client: httpx.Client, fx: dict[str, Path]) -> None:
    section("M3 长音频（60s+ 中文）")
    p = fx.get("long.wav")
    if not p:
        record("M3 long", False, "素材缺失")
        return
    dur = wav_duration(p)
    print(f"  时长 {dur:.0f}s")
    t0 = time.perf_counter()
    try:
        status, text = transcribe(client, p, "audio/wav")
    except httpx.HTTPError as e:
        record("M3 long", False, f"异常 {type(e).__name__}")
        return
    elapsed = time.perf_counter() - t0
    print(f"  {status} {elapsed:.2f}s RTF≈{elapsed / dur:.3f}  字数 {len(text)}")
    print(f"  尾部 80 字: …{text[-80:]}")
    record("M3 long", status == 200 and len(text) > 100, f"{dur:.0f}s 音频 {elapsed:.1f}s RTF≈{elapsed / dur:.2f}")


def test_edge_inputs(client: httpx.Client, fx: dict[str, Path]) -> None:
    section("M4 边界输入（静音 / 纯噪声）")
    for key in ("silent.wav", "noise.wav"):
        p = fx.get(key)
        if not p:
            record(f"M4 {key}", False, "素材缺失")
            continue
        t0 = time.perf_counter()
        try:
            status, text = transcribe(client, p, "audio/wav")
        except httpx.HTTPError as e:
            record(f"M4 {key}", False, f"异常 {type(e).__name__}")
            continue
        elapsed = time.perf_counter() - t0
        print(f"  {key:<12} {status} {elapsed:5.2f}s  text='{text[:60]}'")
        record(f"M4 {key}", status == 200, f"status={status}, text='{text[:30]}'")


def test_hotword(client: httpx.Client, fx: dict[str, Path]) -> None:
    section("M5 prompt 热词引导（专有名词句子）")
    p = fx.get("hotword.wav")
    if not p:
        record("M5 hotword", False, "素材缺失")
        return
    print(f"  原文: {HOTWORD_TEXT}")
    for label, prompt in (("无prompt", None), ("带prompt", HOTWORD_PROMPT)):
        try:
            status, text = transcribe(client, p, "audio/wav", prompt=prompt)
        except httpx.HTTPError as e:
            record(f"M5 {label}", False, f"异常 {type(e).__name__}")
            continue
        marks = [w for w in ("HomeAgent", "豆包", "qwen3-asr") if w.lower() in text.lower()]
        print(f"  [{label}] {status}  专有名词命中 {marks}\n    {text[:100]}")
        record(f"M5 {label}", status == 200, f"命中 {marks}")


def test_concurrency(client: httpx.Client, fx: dict[str, Path]) -> None:
    section("M6 并发排队（同时 3 请求，服务单并发）")
    p = fx.get("long.wav") or fx.get("f_wav.wav")
    if not p:
        record("M6 concurrent", False, "素材缺失")
        return
    dur = wav_duration(p) if p.suffix == ".wav" else 6.8
    t0 = time.perf_counter()

    def one(i: int) -> tuple[int, float, str]:
        s = time.perf_counter()
        c = client_no_proxy()
        try:
            status, text = transcribe(c, p, mime_of(p))
            return status, time.perf_counter() - s, text[:20]
        except httpx.HTTPError as e:
            return -1, time.perf_counter() - s, type(e).__name__
        finally:
            c.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        outs = list(pool.map(one, range(3)))
    total = time.perf_counter() - t0
    single = min(d for _, d, _ in outs)
    for i, (status, d, preview) in enumerate(outs):
        print(f"  请求{i + 1}: {status} {d:6.2f}s  '{preview}'")
    print(f"  总耗时 {total:.2f}s，最短 {single:.2f}s（单次基线），串行放大 ≈ {total / single:.2f}x")
    record("M6 concurrent", all(s == 200 for s, _, _ in outs),
           f"3并发 {total:.1f}s, 放大 {total / single:.1f}x")


def summarize() -> None:
    section("汇总")
    width = max(len(n) for n, _, _ in results) if results else 10
    fails = 0
    for name, status, summary in results:
        print(f"{name:<{width}}  {status}  {summary}")
        fails += status == "FAIL"
    print(f"\n通过 {len(results) - fails}/{len(results)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="只跑指定用例组，逗号分隔，如 M1,M5")
    parser.add_argument("--regen", action="store_true", help="强制重新生成素材")
    args = parser.parse_args()
    todo = {s.strip() for s in args.only.split(",")} if args.only else None

    fx = prepare_fixtures(args.regen)
    with client_no_proxy() as client:
        suites = {
            "M1": lambda: test_formats(client, fx),
            "M2": lambda: test_english(client, fx),
            "M3": lambda: test_long(client, fx),
            "M4": lambda: test_edge_inputs(client, fx),
            "M5": lambda: test_hotword(client, fx),
            "M6": lambda: test_concurrency(client, fx),
        }
        for name, fn in suites.items():
            if not todo or name in todo:
                try:
                    fn()
                except Exception as e:  # noqa: BLE001 - 单组失败不中断
                    print(f"  [未捕获异常] {type(e).__name__}: {e}")
                    record(name, False, f"异常 {type(e).__name__}")
    summarize()


if __name__ == "__main__":
    main()
