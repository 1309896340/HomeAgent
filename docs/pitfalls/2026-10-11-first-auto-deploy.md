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

---

## 下半场问题树：服务器构建收敛（同日晚）

上半场部署成功后，服务器端构建暴露出一串「每修一个、重跑、撞出下一个」的问题——
共同主题：**构建的每一个外网依赖（frontend 解析镜像、基础镜像、容器内包管理）都是独立卡点**。

```mermaid
flowchart TD
    R["🎯 最后一公里：让服务器构建稳定跑完"]
    R --> P1["❌ P1 构建第一跳失败：拉取 docker/dockerfile:1 前端镜像超时"]
    P1 -->|"子问题① registry 被 DNS 污染"| P1a["registry-1.docker.io 解析到 Facebook IPv6<br/>解决：dockerd systemd drop-in 配代理"]
    P1a --> P1b["❌ 子问题② 配了代理仍失败<br/>authorize DeadlineExceeded"]
    P1b -->|"定位：# syntax= 强制从 Hub 拉外部 frontend"| P1r["解决：删 syntax 指令，用 Docker 29 内置 frontend"]
    P1r --> P2["❌ P2 基础镜像元数据解析仍超时"]
    P2 -->|"根因：BuildKit 经代理解析 Docker Hub 元数据不稳"| P2r["解决：脚本加基础镜像尽力预拉<br/>+ daemon.json registry-mirrors 直连 DaoCloud"]
    P2r --> P3["❌ P3 Run Command Timeout"]
    P3 -->|"根因：drone-ssh 默认 10 分钟超时<br/>首次构建总时长超限"| P3r["解决：command_timeout 放宽到 30m"]
    P3r --> P4["⚠️ P4 容器内下载依赖慢（直连海外源）"]
    P4 -->|"npm 切 npmmirror / apt 切 TUNA；uv 不换源：--frozen 锁文件绑定 pypi"| OK["🏁 全流程通过 + 服务器端实测验证<br/>双容器 healthy / nginx 反代 / SPA 全 200"]
```

### 下半场教训

4. **构建的外网依赖要逐层消除**：`# syntax=` frontend 镜像、基础镜像、容器内的 npm/pypi/apt 是三层独立的卡点，每层都要么有镜像源、要么有缓存兜底
5. **drone-ssh 默认 `command_timeout` 只有 10 分钟**——远程脚本做完整构建时必改
6. **uv `--frozen` 锁文件绑定了 registry URL**——换镜像源会导致锁校验失败，不能想当然地把 pip 换源经验照搬过去
7. **部署机不需要 node/npm**——前端构建全部发生在构建镜像内部；在宿主机 `apt install npm` 是徒劳的

