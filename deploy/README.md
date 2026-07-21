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

项目生产库已于 2026-07-21 完成这次接管，当前生产环境**不得再次运行 `adopt`**。本节只供仍停留在无 `alembic_version`、且结构与 `0006` 完全一致的旧自托管实例使用；已经由 Alembic 管理的数据库直接进入常规发布流程。

## 常规发布

```bash
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml build
sh deploy/control-plane-release.sh preflight
sh deploy/control-plane-release.sh migrate
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml up -d api web
sh deploy/control-plane-release.sh reload-caddy
export CONTROL_PLANE_URL=https://你的域名
read -rsp 'Caddy 用户名:原始密码: ' CONTROL_PLANE_BASIC_AUTH
printf '\n'
export CONTROL_PLANE_BASIC_AUTH
sh deploy/control-plane-release.sh postflight
unset CONTROL_PLANE_BASIC_AUTH
```

`preflight` 包含 Compose 配置检查、候选 Caddy 配置校验、`pg_dump` 和从当前 revision 到 head 的离线 SQL 预览。`--sql` 只生成 SQL，不执行数据库事务，因此是“预览”而不是真正的 dry-run。`postflight` 检查数据库 revision/结构、`/healthz`、Agent operation 路由以及至少一台 Agent 的服务映射候选接口；最后一项会捕获既有表缺列，operation 健康端点会捕获 Caddy 仍把 Agent 路由挡成 401 的问题。

## 备份校验与失败恢复

`adopt` 和 `preflight` 默认把 PostgreSQL custom-format 备份写入 `/var/backups/vps-agent-console`，权限分别为目录 `0700`、文件 `0600`，并在成功输出中打印确切文件名。脚本不会自动删除备份。至少保留 pre-adoption 备份到 M4.2 生产验证完成，并保留最近三份 pre-migration 备份；清理前先确认已有更新且验证过的备份。

迁移前应使用脚本输出的确切路径检查文件非空且目录可被 `pg_restore` 读取：

```bash
BACKUP=/var/backups/vps-agent-console/脚本输出的文件名.dump
test -s "$BACKUP"
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml \
  exec -T postgres pg_restore --list < "$BACKUP" >/dev/null
```

失败时按发生阶段处理：

- `verify-adoption` 或 preflight 在迁移前失败：数据库尚未被迁移；停止发布、保留备份并修复检查项。不得绕过校验执行 `stamp`。
- `migrate` 失败：不要启动新 API，也不要立即重跑或执行 `alembic downgrade`。先查看容器日志，再运行 `docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml run --rm --no-deps api python -m app.schema revisions` 确认数据库 revision；只有确认事务已完整回滚后才能修复并重试。
- API/Web 启动或 postflight 失败，但 `app.schema check` 已通过：优先把应用和 Caddy 回到上一个已知可用提交，保留当前数据库和备份；不要仅因应用问题恢复数据库。
- 只有确认数据库结构或数据已经不一致时才考虑恢复备份。恢复前停止 Caddy、Web 和 API 的写入，保留失败现场的二次备份，并针对脚本输出的确切备份文件制定单独、复核过的 `pg_restore` 操作；不要直接对在线生产库使用通用的 `--clean` 恢复命令。

M4.1 的一次性接管是在结构已经与 `0006` 完全一致后才 stamp，因此单纯回退 M4.1 应用代码不需要删除 `alembic_version` 或恢复数据库。

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
