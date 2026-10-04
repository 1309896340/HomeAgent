# Skill: web-module-init

---
name: web-module-init
description: 在 src/ 下初始化一个带前后端的 Web 功能模块（FastAPI 后端 + Vue3/Vite/Tailwind 前端 + uv run 编排入口）。当用户要求"新增一个模块""初始化 web 模块""给 xx 建前后端骨架""按 HomeAgent 的模式加一个功能模块"时使用，即使用户只说了模块名（如"建一个 agent 模块"）。
---

# Web 模块初始化（HomeAgent 模式）

本 skill 固化 HomeAgent 项目验证过的模块初始化流程。目标产出：`src/<模块名>/` 下可独立运行、可联调的前后端骨架，并接入根目录统一的启动入口和类型检查。

先确认两个信息，缺了就问用户（或从 README 推断）：模块名；该模块是否需要前后端都有。

## 全局约束

- Python 依赖一律在**项目根目录**用 `uv add` 管理，模块目录内禁止出现独立 pyproject/venv。
- 外部配置参数（端口、地址、开关）一律走环境变量，便于 docker 部署。
- 模块必须是可导入包：检查根 `pyproject.toml` 的 `[tool.hatch.build.targets.wheel] packages = ["src/<模块名>"]` 已登记（模块根下有 `__init__.py`）。
- 完成后运行 `uv run pyright`，必须 0 errors 才算完成。

## 后端（src/<模块名>/backend/）

依赖：`uv add "fastapi[standard]"`（pydantic-settings 已随附，无需单独装）。

分层结构，每层一个目录 + 空 `__init__.py`：

```
backend/
├── __init__.py
├── app.py          # FastAPI 实例 + include_router + /health 健康检查
├── config.py       # pydantic-settings 读环境变量（HOST/PORT/DEBUG，支持 .env）
├── models/         # 数据库 ORM（未接 DB 前放注释占位，说明接 SQLAlchemy 后的形态）
├── schemas/        # Pydantic 请求体/响应体
├── services/       # 业务逻辑（无 DB 时可用内存假数据）
└── routers/        # APIRouter，只做协议适配，调 service 层
```

示例分层调用链（写骨架时就按此结构）：`routers/items.py` 定义 `GET/POST /items` → 调 `services/item_service.py` 的 `list_items()/create_item()` → 返回 `schemas/item.py` 的 `ItemOut/ItemCreate`。

`app.py` 必须包含 `/health` 路由返回 `{"message": "ok"}`——前端代理探测和运维健康检查都依赖它。

## 前端（src/<模块名>/frontend/）

用官方模板在临时目录生成骨架后移入（保留目录里已有的 README.md）：

```bash
cd <临时目录> && npm create vite@latest <名字> -- --template vue
```

技术栈与硬性约束：

- Tailwind v4 用 `@tailwindcss/vite` 插件接入，`style.css` 仅 `@import "tailwindcss"`；**不引入其他第三方 UI/工具库**。
- API 模块 `src/api/client.js`：原生 fetch 封装（get/post/put/del），统一 base url（`import.meta.env.VITE_API_BASE_URL || '/api'`）、JSON 序列化、query 拼接、错误抛出、204 返回 null。
- 所有请求走相对路径 `/api/xxx`，避免 CORS。dev 由 vite 代理，生产由反向代理。
- `vite.config.js`：代理 `/api` 到后端并**剥离前缀**（少了这步，`/api/items` 会打到后端 `/api/items` 而 404），代理目标和端口从 `loadEnv` 读环境变量：

```js
proxy: {
  '/api': {
    target: backendTarget,            // env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8100'
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, ''),
  },
},
```

- 生成 `.env.example` 说明 `VITE_API_PROXY_TARGET` / `VITE_DEV_PORT` / `VITE_API_BASE_URL`。
- 验证：`npm run build` 必须成功；`npm run dev` 起后页面返回 200。

## 启动编排（src/<模块名>/main.py）

模块的 `main()` 负责一键起前后端，并在退出时干净收尾。完整参考实现：[references/orchestrator.py](references/orchestrator.py)。要点：

- `uv run <脚本名>` → `[project.scripts]` 里配 `<脚本名> = "<模块名>.main:main"`。
- 后端用 `sys.executable -m uvicorn <模块名>.backend.app:app` 拉起；前端 `shutil.which("npm")` 定位 npm（**判空**，找不到时 `sys.exit` 中文提示），`cwd` 指向 frontend 目录，并把后端地址通过 `VITE_API_PROXY_TARGET` 传入前端进程环境，保证两边端口一致。
- **任一子进程退出即整体退出**（while 轮询两个 `poll()`），避免留半套服务。
- Ctrl+C 和正常退出都走 finally 清理，Windows 上必须 `taskkill /F /T /PID` 按树杀（node 会派生子进程）。
- 路径计算：`main.py` 在 `src/<模块名>/` 下，项目根是 `Path(__file__).resolve().parents[2]`——写错层级是本流程最常见的 bug，写完先在联调时验证 `cwd` 存在。

## 验收清单（全过才算完成）

1. `uv run python -c "import <模块名>.backend.app"` 导入成功。
2. `uv run <脚本名>` 后：后端 `/health` 返回 ok；`http://localhost:5173/` 页面 200；经 vite 代理的 `/api/health` 返回 ok（三项都验，缺一不可）。
3. Ctrl+C 后 `curl /health` 连接被拒（进程树已清干净）。
4. `npm run build` 成功。
5. `uv run pyright` 0 errors。

## 已知坑位

- vite 8 dev server 默认只绑 IPv6 loopback：验证用 `curl http://localhost:5173`，不要用 `127.0.0.1`。
- Windows 上 `subprocess.Popen(["npm", ...])` 会失败，必须用 `shutil.which("npm")` 解析出的完整路径（npm.cmd）。
- 前端 Popen 失败不能殃及已启动的后端：两个 Popen 都放进 try/finally 的保护范围，finally 里逐个按树清理。

## 完成后

按项目的 git-commit 约定分组提交（依赖 → 后端 → 前端 → 编排脚本），一次提交对应一个逻辑变更。
