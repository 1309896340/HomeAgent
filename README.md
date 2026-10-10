# HomeAgent

运行在家中服务器上的智能助手：Web 界面 + 大模型对话 + 技能（Skills）扩展 + 语音识别。当前定位是**局域网设备管理 Agent**——不面向全屋智能/家电控制，而是把家庭内网（192.168.3.x/24）当作一个可管理的网络来运营：识别与登记内网设备，并借助 Agent 在内网内完成自动化办公与日常管理。

## 目标与规划

1. **设备总览控制台**：展示当前局域网（192.168.3.x/24）下所有设备的信息——IP / MAC / 主机名 / 开放服务 / 操作系统推测等。
   - 信息来源两条路：用 nmap 等工具自动扫描识别；或手工维护（在路由器上把设备 IP 固定后，人工登记到档案）。
2. **Agent 驱动的内网管理**：以自然语言驱动 Agent 在局域网内执行任务，例如设备清单盘点、端口/服务变化提醒、内网服务的例行检查等自动化办公场景。
3. **既有对话能力为基础**：多模态对话、联网搜索、语音输入等能力复用于上述场景，作为 Agent 的交互入口。

> 设备发现/登记层尚未实现，当前仓库中仅有 mock 设备工具用于技能链路联调；以上为下一步演进方向。

## 功能

- **仪表盘**：设备/内网概况总览（当前为静态演示数据，待设备发现与登记层接入后展示真实局域网数据）
- **对话**：与豆包（doubao-seed-2.1-lite，火山引擎 agent plan）流式对话
  - 多模态输入：文字、图片（选文件/粘贴/拖拽）、语音（浏览器录音 / 音频文件上传，本地 qwen3-asr 转写）
  - 联网搜索：输入区开关按消息启用；走 Responses API 内置 `web_search` 服务端工具（豆包/头条系中文源，每月 2 万次免费），展示搜索词与「参考来源」引用链接（落库持久化）
  - 流式输出：思考过程包围框（可折叠回看）、实时计时、耗时与 token 统计、可随时中断（部分内容保留）
  - 多会话管理：列表 / 重命名 / 删除，首条消息自动生成标题，历史持久化（SQLite）
  - Markdown 渲染 + 代码高亮 + 复制 / 重新生成
- **技能机制**：`skills/agent/` 下的 SKILL.md 按渐进式披露注入（清单常驻、正文经 `read_skill` 工具按需读取）；模型通过 function calling 调用白名单工具（当前设备工具为 mock 数据，内网设备发现与管理工具待实现）

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
scripts/                  # 端点/能力验证脚本（verify_llm / verify_responses / verify_asr / test_asr_matrix / verify_skill_flow）
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

- 后端通过 SSE 推送流式事件（`thinking_delta` / `content_delta` / `tool_use` / `web_search` / `web_result` / `meta` / `done`），单条消息内最多 5 轮工具调用，token 统计跨轮累加
- LLM 走火山方舟 Responses API（系统提示用 `instructions`，历史消息直接回放 `input`）；联网搜索为服务端工具，function 工具结果以 `function_call_output` 回放；ASR 走 OpenAI 兼容协议，切换供应商只改 `.env`
- 本机服务调用显式绕过系统代理（`trust_env=False`）
- `scripts/` 下的验证脚本在接入任何外部端点前先行实测其真实行为（响应格式、流式分片、错误结构），结论固化到实现中

## License

GPL-2.0，见 [LICENSE](LICENSE)。
