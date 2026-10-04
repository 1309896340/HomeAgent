"""启动编排参考实现（来自 src/web/main.py，已通过联调验证）。

新模块初始化时把 `web` 替换为实际模块名即可。
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "src" / "web" / "frontend"

BACKEND_PORT = os.getenv("BACKEND_PORT", "8100")
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
FRONTEND_URL = f"http://localhost:{os.getenv('VITE_DEV_PORT', '5173')}"


def _kill_tree(proc: subprocess.Popen) -> None:
    """终止进程及其全部子进程（Windows 上 node 会派生子进程，必须按树杀）。"""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
        )
    else:
        proc.terminate()


def main() -> None:
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("未找到 npm，请确认 Node.js 已安装并在 PATH 中")
    backend = None
    frontend = None
    try:
        backend = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "web.backend.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                BACKEND_PORT,
            ],
        )
        frontend = subprocess.Popen(
            [npm, "run", "dev"],
            cwd=FRONTEND_DIR,
            env={**os.environ, "VITE_API_PROXY_TARGET": BACKEND_URL},
        )
        print(f"后端: {BACKEND_URL}/health")
        print(f"前端: {FRONTEND_URL}（Ctrl+C 退出）")

        # 任一子进程退出就结束编排，避免留下半套服务
        while backend.poll() is None and frontend.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在停止服务...")
    finally:
        if frontend is not None:
            _kill_tree(frontend)
        if backend is not None:
            _kill_tree(backend)


if __name__ == "__main__":
    main()
