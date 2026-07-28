# 生产部署

生产环境由 Caddy 对外提供 80/443，Web、API、PostgreSQL 和 Redis 仅在 Docker 内部网络通信。

## 首次启动（空数据库）

```bash
cd /opt/vps-agent-console
cp deploy/.env.production.example deploy/.env.production
chmod 600 deploy/.env.production
# 编辑真实域名、稳定实例 ID、构建版本/commit/time、密码哈希、数据库密码和管理令牌
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

`preflight` 包含 Compose 配置检查、候选 Caddy 配置校验、M6.1 原子备份包和从当前 revision 到 head 的离线 SQL 预览。`adopt` 与 `preflight` 共用同一备份实现，且前者仍在 `stamp head` 前备份旧 create_all 库。`--sql` 只生成 SQL，不执行数据库事务，因此是“预览”而不是真正的 dry-run。`postflight` 检查数据库 revision/结构、`/healthz`、Agent operation 路由以及至少一台 Agent 的服务映射候选接口；最后一项会捕获既有表缺列，operation 健康端点会捕获 Caddy 仍把 Agent 路由挡成 401 的问题。

## M6.1 备份包与隔离恢复

`adopt` 和 `preflight` 默认把原子备份包写入 `/var/backups/vps-agent-console`。也可由管理员显式创建一次备份：

```bash
BACKUP_DIR=/var/backups/vps-agent-console \
  sh deploy/control-plane-backup.sh manual
```

命令只在 `pg_dump`、`pg_restore --list`、严格 manifest 和 `SHA256SUMS` 全部通过后，将临时目录原子改名为 `control-plane-标签-UTC时间`。成品固定包含 `postgres.dump`、`manifest.json` 和 `SHA256SUMS`，目录/文件权限为 `0700`/`0600`，脚本不自动上传或删除旧包。dump 与固定关键表计数来自同一 exported snapshot；备份可能包含开始时仍在途的 Operation，因此计划内金丝雀应避开 M4 执行窗口并记录 manifest 的 `active_operation_count`。

恢复只能面向已经启动的隔离、空 PostgreSQL Compose 项目。隔离环境必须使用与备份相同的稳定实例 ID、应用版本/commit、数据库名和角色，并提供相同 PostgreSQL major 及所需 extension；不得复用生产项目名。先只读检查，再显式确认实例并恢复：

```bash
export ENV_FILE=/安全绝对路径/restore.env
export COMPOSE_PROJECT_NAME=vps-agent-restore-drill-20260726
export RESTORE_ISOLATED_TARGET=yes
PACKAGE=/安全绝对路径/control-plane-manual-UTC时间

sh deploy/control-plane-restore.sh inspect "$PACKAGE"
export RESTORE_CONFIRM_INSTANCE_ID=manifest中的实例ID
export RESTORE_AUDIT_DIR=/安全绝对路径/restore-audit
sh deploy/control-plane-restore.sh restore "$PACKAGE"
```

恢复脚本拒绝 symlink、损坏包、错误 build/实例/PG major/数据库名/角色、缺少 extension 支持和任何非空目标；不提供 `--force`、`--clean`、Web/API/Provider/Agent 入口。实际恢复使用 `--exit-on-error --single-transaction --no-owner --no-privileges`，随后执行 revision/schema 和固定关键表计数核对，只输出有限 JSON 摘要。真实生产库恢复属于单独事故授权事件，不是 M6.1 正常金丝雀。

失败时按发生阶段处理：

- `verify-adoption` 或 preflight 在迁移前失败：数据库尚未被迁移；停止发布、保留已完成的原子备份包并修复检查项。不得绕过校验执行 `stamp`。
- `migrate` 失败：不要启动新 API，也不要立即重跑或执行 `alembic downgrade`。先查看容器日志，再运行 `docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml run --rm --no-deps api python -m app.schema revisions` 确认数据库 revision；只有确认事务已完整回滚后才能修复并重试。
- API/Web 启动或 postflight 失败，但 `app.schema check` 已通过：优先把应用和 Caddy 回到上一个已知可用提交，保留当前数据库和备份；不要仅因应用问题恢复数据库。
- 只有确认数据库结构或数据已经不一致时才考虑生产恢复。恢复前停止 Caddy、Web 和 API 的写入，保留失败现场的二次备份，并取得指定恢复点和目标的单独事故授权；不得把上面的隔离演练命令直接指向在线生产库。

M4.1 的一次性接管是在结构已经与 `0006` 完全一致后才 stamp，因此单纯回退 M4.1 应用代码不需要删除 `alembic_version` 或恢复数据库。

## 检查

```bash
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml ps
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml logs -f caddy api
curl https://你的域名/healthz
curl -u 'Caddy用户名:原始密码' -H "X-Admin-Token: $ADMIN_API_TOKEN" \
  https://你的域名/api/v1/system-info
```

`system-info` 必须返回与本次构建镜像一致的 commit、版本以及实际/期望 Alembic revision；公开 `/healthz` 仍应只返回最小 `status/service`，不包含 commit、数据库名或备份路径。

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

M6.3b 的管理员测试消息默认关闭。仅在受控验证窗口中设置：

```text
NOTIFICATION_TESTS_ENABLED=true
NOTIFICATION_TEST_COOLDOWN_SECONDS=60
```

测试入口固定使用已配置的钉钉机器人和服务端模板，不接受 URL、收件人或消息正文。每条请求必须有 UUID 幂等键，数据库按固定窗口限速且最多尝试发送一次；验证后应按计划恢复 `NOTIFICATION_TESTS_ENABLED=false`。不要在命令输出或工单中打印完整 Webhook、签名 URL、access token 或 secret。
