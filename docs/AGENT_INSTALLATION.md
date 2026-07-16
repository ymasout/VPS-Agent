# Agent 发布、安装与升级

VPS Agent 通过 GitHub Release 发布 Linux 静态二进制，当前稳定版本为 `v0.2.4`，支持 `amd64` 和 `arm64`。每个 Release 同时包含安装脚本和 `SHA256SUMS`，安装器会在替换程序前自动校验二进制。

## 1. 发布新版本

Agent 版本由 Git 标签决定。发布前先保证 `main` 的检查全部通过，然后创建并推送标签：

```bash
git tag -a v0.2.5 -m "VPS Agent v0.2.5"
git push origin v0.2.5
```

GitHub Actions 将自动：

1. 运行 Go 测试。
2. 构建 Linux `amd64` 和 `arm64` 二进制。
3. 生成 SHA-256 校验文件。
4. 创建 GitHub Release 并上传所有产物。

版本号示例仅表示下一次发布；实际发布时应使用尚未存在的新标签。

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

快速安装方式（安装器仍会校验 Agent 二进制）：

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

确认脚本后安装。安装器会在终端中隐藏输入注册令牌：

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
- `--version 0.2.4`：安装指定版本；默认安装最新 Release。

安装器会创建：

- `/usr/local/bin/vps-agent`
- `/etc/vps-agent/agent.env`
- `/var/lib/vps-agent/identity.json`
- `/var/lib/vps-agent/machine-id`
- `/etc/systemd/system/vps-agent.service`

M3 Docker 日志取证默认关闭。需要时在 `/etc/vps-agent/agent.env` 中显式配置本地白名单，然后重启 Agent：

```dotenv
AGENT_EVIDENCE_SOURCES_JSON='[{"key":"payment-api-logs","kind":"docker_logs","target":"payment-api","display_name":"payment-api-logs"}]'
```

容器目标只保存在 VPS 本地；控制平面只能引用 `key` 并下发有限时间、行数、字节数和超时。完整协议见 [M3_DIAGNOSTICS.md](./M3_DIAGNOSTICS.md)。

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
