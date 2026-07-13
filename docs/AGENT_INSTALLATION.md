# Agent 发布、安装与升级

VPS Agent 通过 GitHub Release 发布 Linux 静态二进制，当前支持 `amd64` 和 `arm64`。每个 Release 同时包含安装脚本和 `SHA256SUMS`，安装器会在替换程序前自动校验二进制。

## 1. 发布新版本

Agent 版本由 Git 标签决定。发布前先保证 `main` 的检查全部通过，然后创建并推送标签：

```bash
git tag -a v0.2.2 -m "VPS Agent v0.2.2"
git push origin v0.2.2
```

GitHub Actions 将自动：

1. 运行 Go 测试。
2. 构建 Linux `amd64` 和 `arm64` 二进制。
3. 生成 SHA-256 校验文件。
4. 创建 GitHub Release 并上传所有产物。

版本号示例仅表示下一次发布；实际发布时应使用尚未存在的新标签。

## 2. 为每台 VPS 创建一次性令牌

每台机器必须使用不同的注册令牌。令牌默认 30 分钟过期，成功注册后立即失效。

```bash
curl -u 'Caddy用户名:Caddy密码' \
  -H 'Content-Type: application/json' \
  -H 'X-Admin-Token: 管理API令牌' \
  -d '{"name":"dmit-vps","expires_in_minutes":30}' \
  https://ops.ymast.shop/api/v1/registration-tokens
```

只复制响应中的 `reg_...`。不要把 Caddy 密码、管理 API 令牌或注册令牌发到聊天、提交到 Git，或者写入公开脚本。

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

可选参数：

- `--healthcheck https://example.com/healthz`：一个或多个逗号分隔的 HTTP 检查地址。
- `--interval 30s`：上报间隔。
- `--version 0.2.2`：安装指定版本；默认安装最新 Release。

安装器会创建：

- `/usr/local/bin/vps-agent`
- `/etc/vps-agent/agent.env`
- `/var/lib/vps-agent/identity.json`
- `/etc/systemd/system/vps-agent.service`

注册成功后，一次性令牌会从配置文件删除，后续重启和升级使用已保存的独立 Agent 身份。

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
sudo bash install-agent.sh --url https://ops.ymast.shop --version 0.2.2
```

## 6. M1 实机验收

三台 VPS 均应满足：

- Agent 使用不同的一次性令牌注册，Fleet 中不存在重复机器。
- 连续上报 CPU、内存、磁盘、Docker/systemd 和配置的 HTTP 检查。
- 重启 Agent 后恢复同一身份。
- 停止 Agent 超过离线阈值后显示离线，重新启动后恢复在线。
- systemd 能区分 `active`、`inactive` 和 `failed`，正常待命服务不计入异常。

全部通过并同步 `PROJECT_STATUS.md` 与 `ROADMAP.md` 后，M1 才标记为完成。
