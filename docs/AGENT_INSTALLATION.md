# Agent 发布、安装与升级

VPS Agent 通过 GitHub Release 发布 Linux 静态二进制。v0.6.1 已于 2026-08-01 正式公开发行，Agent 与 API/Web 使用统一版本；历史 Agent-only Release（`v0.2.2`–`v0.4.2`）仍可从 GitHub 获取。旧版 Fleet 版本表不再作为当前事实：旧 aliyun-VPS 已被释放，2026-07-31 M6.4c 金丝雀改用新 aliyun-零时 Agent `v0.4.2`，完成具名 M4 全链后已关闭服务 restart 授权；其他机器的版本、身份和 capability 必须在每次生产操作前实时核对。正式发行同时提供 SHA-256、SBOM 和 Sigstore keyless 签名。

## 1. 发布新版本

M6.4d 起不再允许“推送任意 `v*` tag 就自动公开 Release”。`Agent Release Candidate` 只生成
14 天 review-only 二进制；统一 `Formal Release` 工作流按 `review → draft → candidate → publish`
显式执行，并要求：

1. `release/release.json`、Git commit、Agent `--version`、OCI label 与 Release 名完全一致。
2. `amd64`/`arm64` 二进制、源码和 API/Web OCI 均有 checksum、SBOM 和 Sigstore bundle。
3. tag/draft、GHCR package 可见性、publish 和生产升级分别取得授权。
4. 正式 tag 和 SemVer 镜像标签不存在才可创建，永不移动已有坐标。

完整操作和验证命令见 [RELEASE_PROCESS.md](./RELEASE_PROCESS.md)。不要手工推 tag 绕过发行门。

## 2. 为每台 VPS 创建一次性令牌

每台机器必须使用不同的注册令牌。令牌默认 30 分钟过期，成功注册后立即失效。

推荐登录 `https://ops.ymast.shop/`，在首页“接入新机器”区域填写机器名称并点击“生成令牌”。页面只展示本次生成的令牌和对应安装命令，不会把管理 API 令牌发送到浏览器。

首页生成的命令通过控制平面的 `/agent-downloads/` 同域下载中转获取 Release。目标 VPS 不需要直接连接 GitHub，适用于 GitHub Release/CDN 连接不稳定的网络；控制平面只允许转发固定名称的 Agent 公开产物，不接受任意 URL。

也可以通过管理 API 手动创建：

```bash
curl -u 'Caddy用户名:Caddy密码' \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: 管理API令牌' \
  -d '{"name":"dmit-vps","expires_in_minutes":30}' \
  https://ops.ymast.shop/api/v1/registration-tokens
```

只复制响应中的 `reg_...`。不要把 Caddy 密码、管理 API 令牌或注册令牌发到聊天、提交到 Git，或者写入公开脚本。

在浏览器和远程终端之间操作时，使用以下顺序，避免把令牌与安装命令拼成带换行的 Shell 参数：

1. 先点击“复制安装命令”，在目标 VPS 粘贴并执行。
2. 等终端出现 `Registration token:`。
3. 再回到网页点击“复制令牌”。
4. 回到终端直接粘贴并回车，不添加引号，不从旧的剪贴板历史选择令牌。

## 3. 首次安装

以下快速安装命令对应当前已公开的 Release，提供 checksum 和正式签名保障：

```bash
curl -fsSL --proto '=https' --tlsv1.2 \
  https://github.com/ymasout/VPS-Agent/releases/latest/download/install-agent.sh \
  | sudo bash -s -- --url https://ops.ymast.shop --name dmit-vps
```

执行后在终端中输入该机器的一次性注册令牌。若需要先审查并校验安装器本身，使用下面的推荐方式。

在目标 VPS 上下载 Release 中的安装器和校验文件：

```bash
curl -fLO https://github.com/ymasout/VPS-Agent/releases/latest/download/install-agent.sh
curl -fLO https://github.com/ymasout/VPS-Agent/releases/latest/download/SHA256SUMS
grep ' install-agent.sh$' SHA256SUMS | sha256sum --check -
less install-agent.sh
```

确认脚本后安装。正式 `v0.6.1+` 安装器默认还要求本机存在 `cosign`，下载对应
`vps-agent-linux-<arch>.sigstore.json`，并固定 GitHub workflow identity/issuer 验证发布者；
缺少 bundle 或 cosign 会失败关闭。只有安装明确的旧版 Release 时，管理员才可显式使用
`--allow-legacy-checksum-only`，该选项会输出高可见警告且不能证明发布者身份。安装器会在终端中隐藏输入注册令牌：

```bash
sudo bash install-agent.sh \
  --url https://ops.ymast.shop \
  --name dmit-vps
```

如果目标网络无法稳定访问 GitHub，使用首页生成的新命令，其中会包含：

```text
--download-base-url https://ops.ymast.shop/agent-downloads
```

可选参数：

- `--healthcheck https://example.com/healthz`：一个或多个逗号分隔的 HTTP 检查地址。
- `--interval 30s`：上报间隔。
- `--evidence-policy docker-systemd`：明确允许 Agent 为已发现 Docker 容器和 systemd Unit 生成有限日志诊断能力；也可使用 `docker-logs`、`systemd-journal` 或仅监控的 `disabled`。
- `--operation-policy docker-restart`：明确允许 Agent 为本机已发现 Docker 服务声明重启能力；默认 `disabled`。启用时必须同时提供 `--operation-key-id` 和 `--operation-public-key`。
- `--operation-key-id m4-2026-01`：控制平面 Ed25519 签名 key ID。
- `--operation-public-key BASE64`：对应 32 字节 Ed25519 公钥的 Base64。公钥可以进入安装命令；私钥只能留在控制平面。
- `--deploy-policy plan-only`：M4.2a 只读发现 Compose 部署候选并允许控制平面生成永久不可执行的冻结计划；默认 `disabled`。它不授予部署写权限，不需要签名密钥。
- `--deploy-policy docker-compose-deploy`：显式允许经确认的单服务 Compose digest 部署；必须同时提供签名 key ID、公钥和 `--deploy-allowed-root`，且宿主机已有 `docker compose`。它不会自动启用重启权限。
- `--deploy-allowed-root /opt/vps-agent-deploy`：Compose 原文件和 working directory 的本地允许根目录；只在可执行部署策略下使用，安装时必须已存在并解析为绝对路径。
- `--version 0.3.0`：安装指定版本；默认安装最新 Release。

安装器会创建：

- `/usr/local/bin/vps-agent`
- `/etc/vps-agent/agent.env`
- `/var/lib/vps-agent/identity.json`
- `/var/lib/vps-agent/machine-id`
- `/etc/systemd/system/vps-agent.service`

M3 日志自动发现默认关闭。新机器推荐在 Web 生成安装命令时选择“监控与 Docker/systemd 只读诊断”，命令会包含：

```text
--evidence-policy docker-systemd
```

安装器将其保存为 `AGENT_EVIDENCE_POLICY=docker_logs,systemd_journal`。Agent 只为本机已发现的 Docker 容器和 systemd Unit 生成受限日志能力，控制平面会收到稳定服务关联和来源键，但不会收到真实容器或 Unit 目标。旧 Agent 升级会保留已有策略；没有明确设置仍保持 `disabled`，不会因为升级自动增加 journal 读取面。

特殊服务仍可在 `/etc/vps-agent/agent.env` 中使用手工兼容白名单，然后重启 Agent：

```dotenv
AGENT_EVIDENCE_SOURCES_JSON='[{"key":"payment-api-logs","kind":"docker_logs","target":"payment-api","display_name":"payment-api-logs"}]'
# systemd 示例：
# AGENT_EVIDENCE_SOURCES_JSON='[{"key":"payment-api-journal","kind":"systemd_journal","target":"payment-api.service","display_name":"payment-api-journal"}]'
```

容器/Unit 目标只保存在 VPS 本地；控制平面只能引用 Agent 声明的 `key` 并下发有限时间、行数、字节数和超时。机器详情页可确认自动发现的诊断服务，不需要手工填写容器 ID、Unit 参数或 `source_key`。完整协议见 [M3_DIAGNOSTICS.md](./M3_DIAGNOSTICS.md)。

M4 写操作同样默认关闭。新机器在 Web 明确选择“允许经确认的 Docker 单服务重启”后，安装命令才会包含本地写策略与控制平面公钥。Agent 自动为当前 Docker 服务声明 `docker_restart + stable service_key`，不上传容器 target。控制台仍需把具体服务映射标记为非关键并显式启用重启；任务还必须经过管理员确认和 Ed25519 验签。完整协议见 [M4_OPERATIONS.md](./M4_OPERATIONS.md)。

安装器 CLI 的用户选项使用连字符（例如 `--evidence-policy docker-logs`、
`--operation-policy docker-restart`），但写入 `/etc/vps-agent/agent.env` 后必须是 Go 常量的
下划线值：`AGENT_EVIDENCE_POLICY=docker_logs`、
`AGENT_OPERATION_POLICY=docker_restart`。直接编辑 env 时不要写成 `docker-logs` 或
`docker-restart`；未知值会安全降级为 `disabled`。启用写能力后必须同时核对 Agent 报告中
实际出现 `docker_restart` capability，不能只核对配置文件文本。

升级到 `v0.4.0` 时需注意 Docker health 行为修正：`running (unhealthy)` 不再被误报为健康，因此可能首次触发 M2 告警；`health: starting` 作为未知状态，不触发异常也不满足 M4 健康验证。部署前应先检查现有容器的 healthcheck 状态，并确保控制平面与 Agent 均使用 NTP/chrony 同步时间。

旧 Agent 升级会保留已有 `AGENT_OPERATION_POLICY`；缺失时写入 `disabled`，不会因升级自动获得写权限。不要把 `OPERATION_SIGNING_PRIVATE_KEY_BASE64` 写入 Agent 配置或安装命令。

M4.2a 的 `AGENT_DEPLOY_POLICY=plan_only` 与重启写策略完全分离，只读取容器和镜像 inspect 元数据，不读取或上传 Compose 路径、容器 ID、Docker target 或 Registry 凭据。M4.2b 代码加入后 `plan_only` 仍保持只读，必须人工改成 `docker_compose_deploy`、配置签名公钥与本地允许目录，并在控制台对具体非关键服务另行启用 `deploy_enabled`，才会获得部署能力。M4.2c 回滚不增加新的 Agent 命令或权限：它是控制面生成、再次人工确认的独立协议 v2 B->A 任务，Agent 仍执行同一组严格 digest、路径、Compose 漂移和签名检查。控制平面仍不会收到 Compose 路径、容器 target 或 Registry 凭据。

注册成功后，一次性令牌会从配置文件删除，后续重启和升级使用已保存的独立 Agent 身份。

`machine-id` 由安装器为每次全新安装随机生成，仅用于控制平面识别 Agent。不要复制到其他 VPS；安装器不会修改操作系统的 `/etc/machine-id`。

## 4. 验证

```bash
/usr/local/bin/vps-agent --version
sudo systemctl status vps-agent --no-pager
sudo journalctl -u vps-agent -n 30 --no-pager
```

日志出现 `report accepted` 后，在 Fleet 页面确认机器名称、系统、CPU、内存、磁盘和服务状态。

## 5. 升级

重新下载最新安装脚本并执行即可。已有身份的机器不需要注册令牌，现有控制平面地址、名称、健康检查和上报间隔会自动保留：

```bash
sudo bash install-agent.sh --url https://ops.ymast.shop
```

指定版本回滚：

```bash
sudo bash install-agent.sh --url https://ops.ymast.shop --version 0.2.4
```

升级已有机器时必须保留以下文件：

- `/var/lib/vps-agent/identity.json`
- `/var/lib/vps-agent/machine-id`

不要为正常升级生成新的注册令牌，也不要删除身份文件。否则可能创建重复机器，或者触发在线机器的重新绑定保护。

### 控制平面宿主机升级

控制平面宿主机已经注册为 `control-plane`。先确认身份文件存在；若检查失败，应停止并排查，不要继续安装：

```bash
test -s /var/lib/vps-agent/identity.json \
  && echo "identity exists，可以升级" \
  || { echo "identity missing，请停止"; exit 1; }
```

建议先备份 Agent 配置和身份，再使用控制平面同域中转升级到 `v0.2.4`：

```bash
backup_suffix="$(date +%Y%m%d-%H%M%S)"
cp -a /etc/vps-agent "/etc/vps-agent.backup-${backup_suffix}"
cp -a /var/lib/vps-agent "/var/lib/vps-agent.backup-${backup_suffix}"

curl -fsSL --proto '=https' --tlsv1.2 \
  https://ops.ymast.shop/agent-downloads/v0.2.4/install-agent.sh \
  | bash -s -- \
      --url https://ops.ymast.shop \
      --download-base-url https://ops.ymast.shop/agent-downloads \
      --version 0.2.4
```

安装器会读取已有 `AGENT_NAME` 和身份，不会要求注册令牌。完成后验证：

```bash
/usr/local/bin/vps-agent --version
systemctl status vps-agent --no-pager
journalctl -u vps-agent -n 30 --no-pager
```

预期版本为 `vps-agent 0.2.4`，日志出现 `report accepted`，Fleet 中原有 `control-plane` 记录恢复在线且不会新增重复记录。

### 身份文件丢失

若已注册机器的 `identity.json` 丢失，不要删除 `machine-id`。应先停止 Agent，等待控制台将该机器判断为离线，再生成新的短期令牌进行重新绑定。只有从未成功注册的新机器，才可以在排除克隆冲突时重新生成 Agent machine-id。

## 6. M1 实机验收

至少三台 VPS 均应满足：

- Agent 使用不同的一次性令牌注册，Fleet 中不存在重复机器。
- 连续上报 CPU、内存、磁盘、Docker/systemd 和配置的 HTTP 检查。
- 重启 Agent 后恢复同一身份。
- 停止 Agent 超过离线阈值后显示离线，重新启动后恢复在线。
- systemd 能区分 `active`、`inactive` 和 `failed`，正常待命服务不计入异常。

2026-07-14 已完成 3 台外部 VPS 的实机验收；连同控制平面宿主机，Fleet 共 4 条真实机器记录。4 台 Agent 均已升级到 `v0.2.4` 并保持在线，M1 已完成。
