# 首次自动部署踩坑记录（2026-10-11）

从编写 docker-compose / GitHub Actions 到首次部署成功全过程中的问题树：
每个分支记录「现象 → 定位 → 根因 → 解决 → 返回/进入下一个问题」的完整链路。

```mermaid
flowchart TD
    R["🎯 目标：HomeAgent 自动部署"]
    R --> A["📦 阶段A 本地构建验证"]
    A --> A1["❌ A1 构建假成功"]
    A1 -->|"定位：引擎未运行，管道吞退出码"| A1r["解决：pipefail 保真实退出码"]
    A1r -->|"✓ 返回"| A
    A --> A2["❌ A2 容器报缺失 LLM.API_KEY"]
    A2 -->|"对照实验：environ 有值"| A2r["根因：shell 不导入点分变量名，子进程全丢"]
    A2r -->|"解决：Python 入口 exec 传环境"| A
    A --> A3["⚠️ 兄弟A3 nginx 起不来"]
    A3 -->|"定位：非bug，依赖健康检查属预期"| OKA["🎉 A 构建与端到端全通"]
    OKA -->|"推送 main"| B["🚀 阶段B CI 自动部署"]
    B --> B1["❌ B1 缺 SSH_PRIVATE_KEY"]
    B1 -->|"子问题：Secret 叫 SSH_KEY，取用处未改"| B1r["解决：三处对齐"]
    B1r --> B2["❌ B2 SSH publickey 被拒"]
    B2 -->|"你自查"| B2r["根因：系统用户 agent 无 authorized_keys"]
    B2r -->|"解决：SSH_USER 改 wind"| B3["❌ B3 DEPLOY_DIR 静默默认值"]
    B3 -->|"解决：改必填，缺失即报错"| B4["❌ B4 服务器无 docker"]
    B4 -->|"子问题：Debian 无此包名"| B4r["解决：官方源装 docker-ce"]
    B4r --> B5["❌ B5 zsh 报 BASH_COMMAND 未定义"]
    B5 -->|"定位：双根因"| B5r["zsh 无 bash 变量 + pipefail 误伤 grep"]
    B5r -->|"解决：仓库脚本显式 bash 执行"| C["🌐 阶段C 代理 192.168.3.2:10808"]
    C --> C1["❌ C1 curl 走代理 5 秒被掐"]
    C1 -->|"v2ray 日志"| C1r["线索：出站拨向黑洞 IP 127.127.127.5"]
    C1r --> C2["❌ C2 v2ray 配置起不来"]
    C2 -->|"子问题① Xray 扁平格式"| C2a["解决：改 servers 数组"]
    C2 -->|"子问题② process 规则"| C2b["解决：删除，v2fly 不支持"]
    C2 -->|"子问题③ 粘贴缩进痛苦"| C2c["解决：本地写文件 scp"]
    C2a --> C3["❌ C3 换入口域名仍解析到黑洞 IP"]
    C2b --> C3
    C2c --> C3
    C3 -->|"dig 对照：直查正常，系统解析异常"| C3r["根因：Tailscale MagicDNS 黑洞机场域名"]
    C3r -->|"解决：hosts 写死 + accept-dns=false"| DONE["🏁 curl 200，部署全通"]
```

## 图例

- 边标注 = 排查过程：「发现 → 定位 → 解决 → 返回父问题 / 进入下一个兄弟问题」
- B2 → B3 → B4 → B5 的推进，正是「修复一个、重跑流水线、撞出下一个」的真实序列
- 三条最值得记住的教训：
  1. **shell 会静默丢弃点分环境变量**——容器入口必须用 Python exec 形式（`deploy/entrypoint.py`）
  2. **管道会吞退出码**——一切自动化脚本加 `set -Eeuo pipefail`，绝不静默继续
  3. **Tailscale MagicDNS 会接管系统 DNS**——排查解析问题时先看 `/etc/resolv.conf` 是不是被谁改了
