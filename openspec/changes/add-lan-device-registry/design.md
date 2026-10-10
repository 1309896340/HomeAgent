# Design: add-lan-device-registry

## Context

项目当前没有任何设备层的真实实现：前端仪表盘为静态假数据，「设备」tab 为占位页；后端无设备表、无网络发现代码。本次变更从零建立 device-registry 能力。

关键决策来源：2026-10-10 需求澄清（grilling 会话 8 问），用户已逐条确认；用户要求本次仅产出提案文档，不实施。

## Goals / Non-Goals

- Goals：内网设备以"蓝牙配对式"人工确认流程进入注册表；仪表盘成为已注册设备的唯一展示入口；网段自动检测 + 启动日志；在线状态低负担刷新。
- Non-Goals：设备控制、自动化任务编排、定时后台扫描、跨网段漫游、设备分组/标签。

## Decisions

### D1. 网段自动检测（启动时）

- 启动流程（`uv run web` 的后端编排入口）在 FastAPI lifespan 早期执行：枚举本机网卡 IPv4 地址，过滤掉 loopback（127.0.0.0/8）与链路本地（169.254.0.0/16），取第一个私网地址（10/8、172.16/12、192.168/16），推导其所在 /24 网段。
- console 日志固定格式，一行明确输出，例如：
  `[LAN] 已自动检测到网段: 192.168.3.0/24 (本机 IP: 192.168.3.7, 网卡: Ethernet)`
- 检测失败（无私网地址/多网卡歧义无法确定时）回退 `.env` 显式配置 `LAN.NETWORK`（默认 `192.168.3.0/24`），并以 warning 级别说明走了回退。
- 实现选型：标准库 `socket` + `psutil`（枚举网卡地址与名称，比 `netifaces` 维护更活跃；如引入依赖需在 pyproject 增加）。备选"仅解析 `ipconfig`/`ip addr` 文本"被否决——解析输出受系统语言影响，脆弱。

### D2. 发现 = ping sweep，注册以 IP 为单位

- 配对嗅探第一步只做并发 ping（不扫端口），保证秒级出结果。实现用系统 `ping` 命令异步子进程（`asyncio.create_subprocess_exec`），**以退出码 0 判定存活，不解析输出文本**（Windows 中文输出与格式差异大，退出码跨平台稳定）；Windows 下 `-n 1 -w 1000`，Linux 下 `-c 1 -W 1`。
- 网段内地址并发 ping，超时 1s/台，全部完成后返回存活 IP 列表，减去已注册 IP → "未注册主机"。
- 以 IP 为注册粒度：同一 IP 重复发现不重复注册（注册接口对已存在 IP 返回 409 或幂等提示，见 spec）；设备换 IP 后视为新设备（后续变更可加 MAC 绑定优化，本次不做）。

### D3. 端口扫描 = 注册后异步线程，nmap top 1000

- 注册动作立即返回（不阻塞等待扫描）；后端起一个 daemon 线程对该设备执行 `nmap -T4 --top-ports 1000 <ip> -oX -`（XML 输出解析，避免解析文本表格）。
- 设备表带 `scan_status` 状态机：`pending → running → done / failed`。前端仪表盘与配对完成页据此显示"端口扫描中…"占位，扫描完成后端口数据落库展示。
- nmap 可执行检测在启动时进行：优先 `NMAP_PATH`（.env），否则查 PATH。缺失时启动打 warning，配对流程不受影响（仍可 ping 发现与注册），设备详情显示"端口扫描不可用（未安装 nmap）"。
- 当前开发机未装 nmap（已实测 `nmap` 不在 PATH），故"缺失降级"是必经路径而非边缘 case。

### D4. 在线状态刷新（进入一轮 + 前端定时轮询）

- `GET /api/devices/status`：后端对全部已注册设备并发 ping（同 D2 实现），更新 `status`（online/offline）与 `last_seen` 落库，并返回各设备状态。
- 前端：进入仪表盘时立即静默调一次；页面停留期间 `setInterval` 每 N 秒轮询一次，N 来自后端下发的配置（见 D6），`.env` `LAN.PING_INTERVAL` 默认 5、低于 1 时按 1 处理；离开仪表盘（路由离开守卫/组件卸载）清除定时器。
- 后端每次响应都携带当前生效的 `ping_interval`，前端以后端为准，避免 .env 与前端各存一份。

### D5. 数据模型（SQLite，纯新增）

```
devices
  id          INTEGER PK
  name        TEXT NOT NULL            -- 用户可改的显示名
  ip          TEXT NOT NULL UNIQUE     -- 注册粒度
  mac         TEXT                     -- nmap 扫描附带，可空
  hostname    TEXT                     -- nmap 解析结果，可空
  vendor      TEXT                     -- MAC 厂商（nmap OUI），可空
  status      TEXT NOT NULL DEFAULT 'offline'   -- online / offline
  scan_status TEXT NOT NULL DEFAULT 'pending'   -- pending / running / done / failed
  registered_at DATETIME NOT NULL
  last_seen     DATETIME

device_ports
  id          INTEGER PK
  device_id   INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE
  port        INTEGER NOT NULL
  protocol    TEXT NOT NULL DEFAULT 'tcp'
  service     TEXT                     -- nmap service name，如 ssh/http
  version     TEXT                     -- 服务版本/详情，可空
  UNIQUE(device_id, port, protocol)
```

- 三级展开映射：设备行 → 端口行（`port/protocol` + `service` 作摘要）→ 展开显示 `version` 等服务详情。

### D6. API 设计（全部挂现有登录中间件，不限角色）

```
POST /api/devices/scan            # 创建配对嗅探任务（ping sweep），返回 {scan_id}
GET  /api/devices/scan/{scan_id}  # 轮询任务状态与结果：未注册主机列表 [{ip, suggested_name, ...}]
POST /api/devices                 # 注册 {ip, name?}，立即返回；触发后台端口扫描
GET  /api/devices                 # 已注册设备列表（含端口与 scan_status）
PATCH /api/devices/{id}           # 重命名 {name}
DELETE /api/devices/{id}          # 移除注册（级联删端口）
GET  /api/devices/status          # 并发 ping 刷新并返回在线状态（含 ping_interval 下发）
```

- 嗅探任务用"任务 id + 轮询"而非 SSE：ping sweep 总耗时可控（约 5–10s），轮询实现简单且与现有前端轮询习惯一致；SSE 已有但留给对话流。
- `suggested_name` 生成顺序：nmap/系统可解析的主机名 → IP（无更优信息时）；MAC 厂商名在注册后的扫描结果里补全展示，不用于预填（ping 阶段拿不到 MAC）。配对页允许用户改名后提交。

### D7. 前端结构

- 路由表：删除 `/devices` 路由与顶栏 tab；`/dashboard` 重写；新增 `/discover`（meta 标题"设备配对"）。
- 仪表盘页：问候语 + 「添加设备」按钮（跳 `/discover`）+ 已注册设备列表（卡片式行，在线徽标；行内三级展开端口/服务）。轮询定时器在 `onMounted` 建立、`onUnmounted` 清除。
- 配对页：进入即自动触发嗅探（也可手动重扫）→ 进度提示 → 结果列表（勾选 + 名称行内编辑，预填 `suggested_name`）→「加入已注册列表」→ 成功后提示"端口扫描进行中，可返回仪表盘查看"并跳转回仪表盘。
- 移除注册走原生 confirm（与现有设置页交互一致）；重命名用行内编辑。
- 图标风格沿用 tab 定义中的 24x24 stroke path 约定。

## Risks / Trade-offs

- **ping 靠系统命令**：跨平台参数差异集中在一个工具函数里处理（退出码判定），风险可控；不引 icmplib 之类的 raw socket 库（Windows 需管理员）。
- **top-1000 扫描对个别设备可能触发安全告警/设备异常**：家用内网可接受；扫描仅发生在人工注册时（一次性），不做周期扫描。
- **5s 轮询 ping 风暴**：设备量为家庭内网量级（数十台），并发 ping 单轮秒级完成，负担可接受；间隔下限 1s 由后端 clamp，防止误配为 0 造成死循环。
- **设备换 IP**：以 IP 为注册粒度的代价，设备 DHCP 换地址后会"消失"并出现在新 IP 上需重新注册；用户已在路由器上固定 IP（README 规划），此代价可接受，MAC 绑定留给后续变更。

## Migration Plan

新增两张表，无存量数据迁移；删除的仪表盘假数据组件无持久化依赖，可直接删。

## Open Questions

无——需求歧义已在 grilling 会话中全部关闭（8 项决策用户均已确认）。
