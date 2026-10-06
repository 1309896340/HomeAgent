# HomeAgent

运行在家中服务器上的智能助手：Web 界面 + 大模型对话 + 技能（Skills）扩展 + 语音识别，目标是逐步接入家庭设备实现全屋智能。

## 功能

- **仪表盘**：家庭概况总览（当前为静态演示数据，待设备层接入后接真实数据）
- **对话**：与豆包（doubao-seed-2.1-lite，火山引擎 agent plan）流式对话
  - 多模态输入：文字、图片（选文件/粘贴/拖拽）、语音（浏览器录音 / 音频文件上传，本地 qwen3-asr 转写）
  - 流式输出：思考过程包围框（可折叠回看）、实时计时、耗时与 token 统计、可随时中断（部分内容保留）
  - 多会话管理：列表 / 重命名 / 删除，首条消息自动生成标题，历史持久化（SQLite）
  - Markdown 渲染 + 代码高亮 + 复制 / 重新生成
- **技能机制**：`skills/agent/` 下的 SKILL.md 按渐进式披露注入（清单常驻、正文经 `read_skill` 工具按需读取）；模型通过 function calling 调用白名单工具（当前设备工具为 mock 数据，真实硬件待接入）

## 目录结构

```
src/
├── web/
│   ├── backend/          # FastAPI：会话/消息/SSE 流式/转写路由，LLM/ASR/技能注册表/工具白名单
│   ├── frontend/         # Vue3 + Vite + Tailwind v4（GitHub Primer 风格）
│   └── main.py           # `uv run web` 前后端编排入口
asr/                      # qwen3-asr Docker 服务（OpenAI 兼容，GPU）
skills/
├── agent/                # 对话运行时技能（后端唯一扫描来源）
└── dev/                  # 项目开发流程技能（对话不可见）
scripts/                  # 端点/能力验证脚本（verify_llm / verify_asr / test_asr_matrix / verify_skill_flow）
db/                       # SQLite 与上传图片（gitignore）
data/                     # 语音输入缓存等调试数据（gitignore）
```

## 快速开始

依赖：Python 3.12+（uv 管理）、Node.js 18+、NVIDIA GPU（仅 ASR 需要）。

```bash
# 1. 安装依赖
uv sync

# 2. 配置环境变量（必填 LLM.API_KEY，其余有默认值）
cp .env.example .env

# 3. （可选）启动本地语音识别服务
cd asr && docker compose up -d

# 4. 一键启动前后端（后端 8100 / 前端 5173）
uv run web
```

## 技术要点

- 后端通过 SSE 推送流式事件（`thinking_delta` / `content_delta` / `tool_use` / `meta` / `done`），单条消息内最多 5 轮工具调用，token 统计跨轮累加
- LLM / ASR 均走 OpenAI 兼容协议，切换供应商只改 `.env`
- 本机服务调用显式绕过系统代理（`trust_env=False`）
- `scripts/` 下的验证脚本在接入任何外部端点前先行实测其真实行为（响应格式、流式分片、错误结构），结论固化到实现中

## License

GPL-2.0，见 [LICENSE](LICENSE)。
