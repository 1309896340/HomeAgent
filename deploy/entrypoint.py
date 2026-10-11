"""HomeAgent 后端容器入口：环境变量校验（缺失立即失败）→ exec 启动 uvicorn。

为什么用 Python 而不是 shell 脚本：本项目的配置变量名含 "."（如 LLM.API_KEY），
POSIX shell 不会把这类变量导入自己的变量表，其子进程（printenv / uvicorn）将
拿不到它们——而 Python 进程被 runtime 直接 exec 时能看到完整原始环境。
因此入口必须是 python（ENTRYPOINT exec 形式），再由 os.execve 把
os.environ 完整传给 uvicorn，保证点分变量一路到达应用进程。
"""

import os
import sys

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = os.environ.get("PORT", "8000")

# 必需变量：缺失或仅空白即退出，绝不带病启动
REQUIRED_VARS = ["LLM.API_KEY"]

missing = [name for name in REQUIRED_VARS if not os.environ.get(name, "").strip()]
if missing:
    print("============================================================", file=sys.stderr)
    print(f"ERROR: 缺失必需的环境变量: {' '.join(missing)}", file=sys.stderr)
    print("", file=sys.stderr)
    print("请在项目根目录的 .env 中配置后重启容器：", file=sys.stderr)
    print("  cp .env.example .env   # 然后编辑 .env，至少填入 LLM.API_KEY", file=sys.stderr)
    print("  docker compose up -d", file=sys.stderr)
    print("============================================================", file=sys.stderr)
    sys.exit(1)

# 启动信息（绝不打印密钥明文）
print("[entrypoint] 配置摘要：")
print(f"[entrypoint]   LLM.MODEL    = {os.environ.get('LLM.MODEL') or 'doubao-seed-2.1-lite（默认）'}")
print(f"[entrypoint]   LLM.BASE_URL = {os.environ.get('LLM.BASE_URL') or 'https://ark.cn-beijing.volces.com/api/plan/v3（默认）'}")
print(f"[entrypoint]   ASR.BASE_URL = {os.environ.get('ASR.BASE_URL') or 'http://127.0.0.1:12301/v1（默认）'}")
print(f"[entrypoint]   LLM.API_KEY  = 已配置（长度 {len(os.environ['LLM.API_KEY'])} 字符）")
print(f"[entrypoint]   监听         = {HOST}:{PORT}")

# exec 换型为 uvicorn（保持 PID 1，正确接收停止信号）；
# 显式传 os.environ 副本，点分变量不丢失
os.execve(
    sys.executable,
    [sys.executable, "-m", "uvicorn", "web.backend.app:app", "--host", HOST, "--port", PORT],
    os.environ.copy(),
)
