# TODO

## [待处理] 目标机设备扫描 0 台——容器缺 iputils-ping（2026-10-11 深夜诊断完毕，等修复）

- **现象**：部署机（192.168.3.240）设备嗅探任务正常执行，但始终「存活 0 台」。
- **已排除**：nmap 正常（容器内 `nmap -sn 192.168.3.1` 秒探到网关）；网络未隔离（host 网络生效，
  容器内可见物理网卡 ens18，网段检测正确输出 192.168.3.0/24）。
- **根因（已实锤）**：嗅探用系统 `ping` 命令（`lan_service._ping_command` → `ping -c 1 -W 1`），
  而 web-runtime 镜像未装 `iputils-ping`（python:3.12-slim 不自带）；
  `ping_host` 捕获 `FileNotFoundError` 后静默返回 False → 全部设备判死、日志无任何报错。
  已验证：`docker exec homeagent-backend which ping` → 不存在。
- **修复方案（一句话）**：`Dockerfile` web-runtime 阶段的 `apt-get install` 列表加 `iputils-ping`，
  提交推送 main 触发自动部署即可。
- **顺带建议**（与"切忌静默"哲学一致）：
  - `ping_host` 对 `FileNotFoundError` 应记 warning 日志而非静默返回 False（探测能力缺失必须暴露）；
  - 部署机 `.env` 里若还留着 Windows 路径的 `LAN.NMAP_PATH` 行，删掉可消除启动警告；
  - 可考虑在 `deploy/remote-deploy.sh` 或启动日志中自检 `ping` / `nmap` 可用性，缺失时打 WARN。
