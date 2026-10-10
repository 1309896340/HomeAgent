# Tasks: add-lan-device-registry

实施顺序遵循依赖关系：配置/检测 → 存储与工具 → API → 前端 → 端到端验证。对应 design.md 的决策编号标注在各任务后。

## 1. 后端基础

- [ ] 1.1 网段自动检测模块：枚举网卡取私网 IPv4 推导 /24，启动 lifespan 早期执行，console 输出 `[LAN] 已自动检测到网段: ...` 固定格式；失败回退 `.env` `LAN.NETWORK`（默认 192.168.3.0/24）并 warning（D1）
- [ ] 1.2 `.env` / 配置层新增 `LAN.NETWORK`、`LAN.PING_INTERVAL`（默认 5，后端 clamp 最小 1）、`NMAP_PATH`（D1/D3/D4）
- [ ] 1.3 SQLite 新增 `devices` / `device_ports` 表与存储层（建表语句、唯一约束、级联删除）（D5）
- [ ] 1.4 ping 工具封装：并发异步子进程调系统 ping，退出码判定存活，单台超时 1s，Windows/Linux 参数分支（D2）
- [ ] 1.5 nmap 可用性检测：启动时按 `NMAP_PATH` → PATH 顺序探测，缺失打 warning 供后续降级（D3）

## 2. 后端 API（挂现有登录中间件，不限角色）

- [ ] 2.1 `POST /api/devices/scan` + `GET /api/devices/scan/{scan_id}`：ping sweep 任务创建与结果轮询，返回未注册主机（IP + suggested_name）（D2/D6）
- [ ] 2.2 设备 CRUD：`POST /api/devices`（注册，IP 唯一冲突处理）、`GET /api/devices`（含端口与 scan_status）、`PATCH /api/devices/{id}`（重命名）、`DELETE /api/devices/{id}`（级联删端口）（D5/D6）
- [ ] 2.3 注册后异步端口扫描：daemon 线程执行 `nmap -T4 --top-ports 1000 -oX -`，XML 解析落库 device_ports，维护 scan_status 状态机 pending→running→done/failed；nmap 缺失时标记降级提示（D3）
- [ ] 2.4 `GET /api/devices/status`：并发 ping 全部已注册设备，更新 status/last_seen，响应携带 `ping_interval`（D4/D6）

## 3. 前端

- [ ] 3.1 删除「设备」tab 与 `/devices` 占位路由（含 PlaceholderView 相应引用清理）（D7）
- [ ] 3.2 DashboardView 整页重写：问候语 + 「添加设备」入口 + 已注册设备列表（在线/离线徽标、名称、IP；三级展开：设备 → 端口（service 摘要）→ 服务详情（version 等））；删除全部智能家居假数据组件（D7）
- [ ] 3.3 在线状态轮询：进入仪表盘立即静默刷新一次，`setInterval` 按 `ping_interval`（后端下发）轮询，`onUnmounted` 清除定时器（D4）
- [ ] 3.4 新增 `/discover` 配对页：进入自动触发嗅探 + 手动重扫按钮 → 进度反馈 → 结果勾选 + 名称行内编辑（预填 suggested_name）→ 注册成功提示"端口扫描进行中"并返回仪表盘（D7）
- [ ] 3.5 设备管理操作：重命名（行内编辑）与移除注册（confirm 确认）（D7）

## 4. 验证

- [ ] 4.1 `scripts/` 新增验证脚本：网段检测日志格式、ping 工具存活判定、嗅探任务生命周期（创建→轮询→结果）、注册闭环（注册→scan_status 流转→端口落库）、status 接口与 ping_interval clamp（D1–D4）
- [ ] 4.2 浏览器端到端：登录 → 仪表盘（空列表）→ 添加设备进入配对页 → 嗅探 → 勾选注册 → 返回仪表盘看端口扫描状态流转与三级展开 → 重命名/移除 → 离开页面后轮询停止（DevTools Network 确认）（D7）
- [ ] 4.3 降级路径验证：模拟 nmap 缺失时配对→注册→列表展示"端口扫描不可用"不阻塞（D3）
