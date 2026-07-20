# 生产部署

生产环境由 Caddy 对外提供 80/443，Web、API、PostgreSQL 和 Redis 仅在 Docker 内部网络通信。

## 首次启动（空数据库）

```bash
cd /opt/vps-agent-console
cp deploy/.env.production.example deploy/.env.production
chmod 600 deploy/.env.production
# 编辑真实域名、密码哈希、数据库密码和管理令牌
nano deploy/.env.production
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml config
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml build
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml up -d postgres redis
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml run --rm --no-deps api alembic -c /app/alembic.ini upgrade head
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml up -d
```

数据库迁移是部署中的显式一次性步骤，不在 API entrypoint 中执行。API 会在启动时核对 `alembic_version` 是否为代码 head；版本不匹配时拒绝启动，避免带着未知结构提供服务。

## 从旧版 create_all 数据库一次性接管

v0.4.0 生产金丝雀已经手动补齐 `0006` 的两列，但旧生产库没有 `alembic_version`。首次切换到 M4.1 时，在构建新 API 镜像后执行：

```bash
sh deploy/control-plane-release.sh adopt
```

脚本先确认当前代码 head 仍是 `0006_m4_safe_operations`，执行 `pg_dump`，再用当前 ORM 元数据严格核对真实结构。只有结构完全匹配才会 `alembic stamp head`，随后执行幂等的 `upgrade head` 和结构复核。校验失败时不得绕过并盲目 stamp；应先查清数据库差异。

## 常规发布

```bash
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml build
sh deploy/control-plane-release.sh preflight
sh deploy/control-plane-release.sh migrate
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml up -d api web
sh deploy/control-plane-release.sh reload-caddy
CONTROL_PLANE_URL=https://你的域名 \
CONTROL_PLANE_BASIC_AUTH='用户名:原始密码' \
sh deploy/control-plane-release.sh postflight
```

`preflight` 包含 Compose 配置检查、候选 Caddy 配置校验、`pg_dump` 和从当前 revision 到 head 的离线 SQL 预览。`--sql` 只生成 SQL，不执行数据库事务，因此是“预览”而不是真正的 dry-run。`postflight` 检查数据库 revision/结构、`/healthz`、Agent operation 路由以及至少一台 Agent 的服务映射候选接口；最后一项会捕获既有表缺列，operation 健康端点会捕获 Caddy 仍把 Agent 路由挡成 401 的问题。

## 检查

```bash
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml ps
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml logs -f caddy api
curl https://你的域名/healthz
```

浏览器访问域名时使用 `CADDY_ADMIN_USER` 和生成哈希前的原始密码登录。

首页“接入新机器”功能由 Web 服务端通过内部网络调用 API。`ADMIN_API_TOKEN` 同时注入 Web 和 API 容器，但不会出现在浏览器 JavaScript 或页面源码中；能够通过 Caddy 登录的用户视为控制平面管理员，可以创建一次性 Agent 注册令牌。

`/agent-downloads/*` 是无需登录的 Agent Release 下载中转，仅允许固定的安装器、校验文件和 amd64/arm64 二进制。它用于目标 VPS 无法稳定连接 GitHub CDN 时从控制平面同域下载公开产物。

## 钉钉告警

M2 首个通知通道使用钉钉自定义机器人。在目标群添加自定义机器人并启用加签后，将 Webhook 和加签密钥分别写入生产环境文件：

```text
DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=...
DINGTALK_SECRET=SEC...
```

Webhook 和密钥只注入 API 容器，不进入 Web 页面或 Agent。`ALERT_PENDING_OBSERVATIONS` 默认是 `2`，表示同一服务异常需要连续观察两次才从 Pending 进入 Firing 并发送通知。恢复通知只在已经进入 Firing、Acknowledged 或 Silenced 的事件明确恢复后生成。
