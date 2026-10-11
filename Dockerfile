# syntax=docker/dockerfile:1
# ============================================================
# HomeAgent 多阶段构建（docker compose 会按 target 分别取用）：
#   frontend-build : Vue3 + Vite 产出静态文件
#   python-deps    : uv 按 uv.lock 精确安装后端依赖（仅依赖层，缓存友好）
#   web-runtime    → 后端镜像（compose service: backend）
#   web-frontend   → nginx 镜像（compose service: frontend，静态 + /api 反代）
# ============================================================

# ---------- 阶段 1：前端构建 ----------
FROM node:22-alpine AS frontend-build
WORKDIR /build

# 先只拷贝依赖清单再 npm ci：package.json 不变时该层直接命中缓存
COPY src/web/frontend/package.json src/web/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY src/web/frontend/ ./
RUN npm run build \
    && test -f dist/index.html || { echo "ERROR: vite build 未产出 dist/index.html"; exit 1; }

# ---------- 阶段 2：后端依赖安装（uv + uv.lock 冻结安装） ----------
FROM python:3.12-slim AS python-deps
# uv 官方镜像拷贝二进制，避免动 pip；--frozen 严格按锁文件安装，锁不一致即报错
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /deps
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project \
    && test -x .venv/bin/uvicorn || { echo "ERROR: 依赖安装后未找到 uvicorn"; exit 1; }

# ---------- 阶段 3：后端运行时（compose target: web-runtime） ----------
FROM python:3.12-slim AS web-runtime

# nmap 供端口扫描技能使用（缺失会降级为不可用，这里直接装齐）
RUN apt-get update \
    && apt-get install -y --no-install-recommends nmap ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 保持仓库目录结构：config.py 用 parents[3] 定位项目根，必须落在 /app/src/... 下
WORKDIR /app/src
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 入口脚本：环境变量缺失即失败（见 deploy/entrypoint.py）。
# 必须是 python exec 形式——shell 会丢弃名字含 "." 的环境变量（如 LLM.API_KEY）
COPY --chmod=644 deploy/entrypoint.py /app/deploy/entrypoint.py

COPY --from=python-deps /deps/.venv /app/.venv
COPY src/ /app/src/
COPY skills/ /app/skills/
COPY pyproject.toml uv.lock .python-version .env.example README.md /app/

# db/ data/ 不打进镜像，由 compose 挂载卷持久化
EXPOSE 8000
ENTRYPOINT ["/app/.venv/bin/python", "/app/deploy/entrypoint.py"]

# ---------- 阶段 4：前端运行时（compose target: web-frontend） ----------
FROM nginx:1.27-alpine AS web-frontend

COPY --from=frontend-build /build/dist /usr/share/nginx/html
# templates 目录会被 nginx 官方入口自动 envsubst 成 conf.d/default.conf
COPY deploy/nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 80
