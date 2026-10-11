#!/usr/bin/env bash
# ============================================================
# HomeAgent 服务器端部署脚本
# 由 .github/workflows/deploy.yml 在完成代码同步后调用：
#   bash "${DEPLOY_DIR}/deploy/remote-deploy.sh"
#
# 为什么必须是独立文件并用 bash 显式执行：脚本使用 bash 特有的
# BASH_COMMAND（ERR trap 里定位失败命令），而 drone-ssh 用服务器
# 登录 shell（可能是 zsh）执行内联命令——内联段因此刻意只用 POSIX
# 语法，bash 逻辑全部收在本文件。
#
# 失败即中断：set -Eeuo pipefail + ERR trap，任一阶段失败立即
# 打印失败命令/行号并退出，后续阶段绝不执行。
# ============================================================
set -Eeuo pipefail
trap 'echo ""; echo "✗✗ 部署失败：命令 [${BASH_COMMAND}] 在 deploy/remote-deploy.sh 第 ${LINENO} 行非零退出，已终止后续阶段"; exit 1' ERR

stage() { echo ""; echo "========== ▶ $1 =========="; }

# ---------- 阶段 1/6 环境预检 ----------
stage "1/6 环境预检"
[ -n "${REPO_URL:-}" ] && [ -n "${GIT_REF:-}" ] && [ -n "${DEPLOY_DIR:-}" ] || {
  echo "✗ 部署参数未传入（REPO_URL / GIT_REF / DEPLOY_DIR）"; exit 1; }
for cmd in git docker curl; do
  command -v "$cmd" >/dev/null || { echo "✗ 服务器未安装 $cmd"; exit 1; }
done
docker compose version >/dev/null 2>&1 || {
  echo "✗ 服务器缺少 docker compose v2 插件"; exit 1; }
echo "✓ git / docker / $(docker compose version --short) / curl 均可用"

# ---------- 阶段 2/6 校验 .env ----------
stage "2/6 校验 .env（缺失环境变量在此拦截）"
cd "${DEPLOY_DIR}"
[ -f .env ] || {
  echo "✗ 缺少 ${DEPLOY_DIR}/.env —— 请先执行："
  echo "    cp .env.example .env && vim .env   # 至少填入 LLM.API_KEY"
  exit 1; }
grep -Eq '^LLM\.API_KEY=.+' .env || {
  echo "✗ .env 中 LLM.API_KEY 为空 —— 请编辑 ${DEPLOY_DIR}/.env 填入后重试"
  exit 1; }

# 从 .env 读取端口（与 docker-compose.yml 插值规则一致）。
# 管道末尾的 || true 吞掉 grep 无匹配的退出码：pipefail 下它会让
# 整条管道变非零、被 ERR trap 误判为部署失败（PORT 未配置是常态）
BACKEND_PORT="$(grep -E '^PORT=' .env | tail -1 | cut -d= -f2- | tr -d '[:space:]"' || true)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
HTTP_PORT="$(grep -E '^HTTP_PORT=' .env | tail -1 | cut -d= -f2- | tr -d '[:space:]"' || true)"
HTTP_PORT="${HTTP_PORT:-80}"
echo "✓ .env 校验通过，端口：后端 ${BACKEND_PORT} / 网站 ${HTTP_PORT}"

# ---------- 阶段 3/6 构建镜像 ----------
stage "3/6 构建镜像（backend + frontend）"
if ! docker compose build --progress=plain; then
  echo "✗ 服务器上镜像构建失败（上方日志含失败阶段：frontend-build / python-deps / web-runtime / web-frontend）"
  exit 1
fi
echo "✓ 镜像构建完成"

# ---------- 阶段 4/6 启动服务 ----------
stage "4/6 启动服务"
if ! docker compose up -d --remove-orphans; then
  echo "✗ 服务启动失败，当前容器状态："
  docker compose ps -a || true
  exit 1
fi
echo "✓ 容器已拉起，等待健康检查"

# ---------- 阶段 5/6 健康检查 ----------
stage "5/6 健康检查"
backend_ok=""
for i in $(seq 1 30); do
  if curl -fsS --max-time 3 "http://127.0.0.1:${BACKEND_PORT}/health" 2>/dev/null | grep -q '"ok"'; then
    backend_ok=1; break
  fi
  echo "  等待后端就绪... (${i}/30)"
  sleep 2
done
if [ -z "$backend_ok" ]; then
  echo "✗ 后端健康检查超时（60s），最近日志："
  docker compose logs --tail=80 backend || true
  exit 1
fi
echo "✓ 后端健康 http://127.0.0.1:${BACKEND_PORT}/health"

frontend_ok=""
for i in $(seq 1 15); do
  if curl -fsS --max-time 3 -o /dev/null "http://127.0.0.1:${HTTP_PORT}/" 2>/dev/null; then
    frontend_ok=1; break
  fi
  echo "  等待前端就绪... (${i}/15)"
  sleep 2
done
if [ -z "$frontend_ok" ]; then
  echo "✗ 前端健康检查超时（30s），最近日志："
  docker compose logs --tail=80 frontend || true
  exit 1
fi
echo "✓ 前端健康 http://127.0.0.1:${HTTP_PORT}/"

# ---------- 阶段 6/6 收尾 ----------
stage "6/6 收尾"
docker compose ps
echo ""
echo "============================================================"
echo "✅ 部署成功：http://<服务器IP>:${HTTP_PORT}/"
echo "   部署版本：$(git rev-parse --short HEAD) (${GIT_REF:0:8})"
echo "============================================================"

# 清理悬空镜像：失败只提示，不影响本次部署结果
docker image prune -f >/dev/null 2>&1 || echo "⚠ 悬空镜像清理失败（不影响部署）"
