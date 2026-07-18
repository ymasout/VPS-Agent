# M3 安全闭环金丝雀验证清单

> 适用范围：在生产环境用**一个服务、一台 VPS**验证 M3 只读诊断的安全闭环（控制平面不能任意指定容器/路径、双端脱敏、三重限制、证据经 Caddy 不被 401）。这不是向全部 VPS 推广 M3，手工白名单是有意走的兼容路径。
> 状态基线：M1/M2 已在生产运行（Agent `v0.2.4`，控制平面 `3cae0d5`）。M3 改了 Agent 协议，但向后兼容，可只升一台。
> 本次提交：`7ae8241`。Caddyfile 的 evidence 路由 + 1MiB body 限制已在该提交里，`git pull` 即生效。
> 定位：按新路线图，M3 在自动发现 + Web 确认完成前仍为"进行中"；本清单只验证安全边界，**不把 M3 标记为已完成**。

## 0. 范围与前提

- **M3 改了 Agent 协议**（上报新增 `evidence_sources`、新增 `evidence.docker_logs.v1` 能力、新增 evidence-requests 端点轮询）。所以部署涉及控制平面 + Agent 两端。
- **向后兼容、可分步**：先升级控制平面，`v0.2.4` 的 Agent 继续上报（`evidence_sources` 缺省为空，API 照常 200），M2 告警不受影响。金丝雀验证只需**升级目标 VPS 一台**的 Agent + 配白名单，其余 3 台保持 `v0.2.4` 不动。
- **M3 保持只读**：不含服务重启/部署/回滚（那是 M4），不含任意 Shell。
- 控制平面用 `Base.metadata.create_all` 在 API 启动时建表，M3 的 10 张新表重启后自动创建。
- 证据白名单 `AGENT_EVIDENCE_SOURCES_JSON` 只存在于各 VPS 本地（`/etc/vps-agent/agent.env`），容器名 target 不上传；钉钉/模型密钥只在控制平面。

## 1. 选定首个诊断目标（部署前先想清楚）

挑一台外部 VPS 上一个**非关键**的 Docker 服务作为首个闭环目标，记下：
- 目标 Agent（已注册的 agent_id）
- 容器名（`docker ps --format '{{.Names}}'`），作为本地白名单的 `target`
- 该服务在 Fleet 里上报的 `service_key`（一般是容器 ID）
- 给它起一个 `source_key`，例如 `payment-api-logs`

## 2. 控制平面升级（Phase 1，安全可先行）

```bash
cd /opt/vps-agent-console
export DC="docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml"

# 备份 + 记录回滚点
git rev-parse HEAD                      # 期望 3cae0d5
$DC exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > /opt/backups/vps-agent-pre-m3-$(date +%Y%m%d-%H%M).sql
ls -lh /opt/backups/vps-agent-pre-m3-*.sql

# 拉取 M3
git pull origin main
git log --oneline -1                    # 期望 7ae8241

# Caddyfile 已含 evidence 路由 + 1MB body；校验并热重载（不停机）
$DC exec caddy caddy validate --config /etc/caddy/Caddyfile
$DC exec caddy caddy reload --config /etc/caddy/Caddyfile

# 重建 api + web（M3 两个都改了；postgres/redis/caddy 不动）
$DC build api web
$DC up -d --no-deps api web
```

> `DIAGNOSTIC_*` 配置 compose 已带默认值（`deterministic` 提供者），首次部署不用改 `.env.production`。想接真实模型再加 `DIAGNOSTIC_PROVIDER=http_json` + `DIAGNOSTIC_API_URL` / `DIAGNOSTIC_API_KEY`。

验证：
```bash
curl https://你的域名/healthz
$DC logs --tail=80 api | grep -iE 'error|exception|traceback' || echo "无错误"
# M3 的 10 张新表已建
$DC exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"' | grep -E 'managed_services|service_instances|diagnostic_runs|evidence_items'
# 关键：v0.2.4 Agent 仍正常上报（last_seen_at 秒级刷新）
$DC exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT name, version, last_seen_at FROM agents ORDER BY name;"'
```

> 4 台 Agent 此时仍是 `v0.2.4`，上报必须持续 200。M2 告警照常。确认无误再进 Phase 2。

## 3. 发布并升级目标 VPS 的 Agent 到 v0.3.0（Phase 2，只升一台）

按 M1 的 Release 流程发布 `v0.3.0`（打 tag -> CI 构建 amd64/arm64 + 校验和 + 安装器 -> Release）。

**只升级金丝雀目标那一台 VPS**；其余 3 台保持 `v0.2.4`（向后兼容，M2 告警照常，等自动发现做好后再统一升级）：
```bash
# 在目标 VPS 上
sudo bash /path/to/install-agent.sh        # 或按 AGENT_INSTALLATION.md 的升级命令
sudo systemctl restart vps-agent           # 按实际服务名
journalctl -u vps-agent -f                 # 看到 "report accepted"，无报错
vps-agent --version                        # 期望 0.3.0
```

> 升级保留原 Agent 身份（`/var/lib/vps-agent/identity.json`），不会创建重复机器。安装器会保留已有的 `AGENT_EVIDENCE_SOURCES_JSON` 配置。

在控制平面验证该 Agent 已升级并开始声明证据源（此时白名单还没配，应为空）：
```bash
$DC exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT a.name, a.version FROM agents a ORDER BY a.name;"'
```

## 4. 配置证据白名单 + 建立服务映射（Phase 3）

### 4.1 在目标 VPS 配置本地白名单

```bash
sudo tee -a /etc/vps-agent/agent.env >/dev/null <<'EOF'
AGENT_EVIDENCE_SOURCES_JSON=[{"key":"payment-api-logs","kind":"docker_logs","target":"实际容器名","display_name":"payment-api-logs"}]
EOF
sudo systemctl restart vps-agent
journalctl -u vps-agent -f                 # 确认 report accepted，无 "evidence" 解析报错
```

> `target` 是本机容器名，不会上传。`key` 必须匹配 `[a-zA-Z0-9._-]+`。非法 JSON/重复键/未知类型会被静默忽略。

在控制平面确认该 Agent 已声明这个证据源：
```bash
$DC exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT agent_id, source_key, kind FROM agent_evidence_sources ORDER BY source_key;"'
```

### 4.2 建立服务映射（管理 API，需要 admin token）

先从 Fleet 拿到目标服务的 `agent_id` 和 `service_key`（容器 ID），然后：

```bash
curl -s -X POST -H "X-Admin-Token: $ADMIN_API_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "name": "payment-api",
    "environment": "production",
    "agent_id": "<agent_id>",
    "service_kind": "docker",
    "service_key": "<容器ID>",
    "deployment_directory": "/opt/apps/payment-api",
    "log_source_key": "payment-api-logs",
    "repository_full_name": "org/payment-api",
    "default_branch": "main",
    "commit_sha": "<40位SHA>",
    "image_digest": "sha256:..."
  }' \
  https://你的域名/api/v1/service-mappings | python3 -m json.tool
```

> `deployment_directory` 必须是绝对且规范化的 Linux 路径（不含 `.`/`..`），否则 422。`log_source_key` 必须是该 Agent 已声明的，否则 409。

## 5. 端到端诊断演练（Phase 4，含 Caddy 验证）

### 5.1 触发一个真实 Firing 事件

在目标 VPS 上短暂停掉那个**非关键**容器（或用一个 canary 容器演练）：
```bash
docker stop <容器名>          # 等 60-90s 进入 Firing
```
在控制平面拿到 firing 事件 id：
```bash
$DC exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT id, title, status FROM alert_events WHERE status='"'"'firing'"'"' ORDER BY last_observed_at DESC LIMIT 3;"'
```

### 5.2 手动触发诊断

```bash
EVENT_ID=<上面查到的事件id>
curl -s -X POST -H "X-Admin-Token: $ADMIN_API_TOKEN" \
  https://你的域名/api/v1/events/$EVENT_ID/diagnostics | python3 -m json.tool
```

### 5.3 验证诊断走完闭环（重点：经 Caddy 不被 401）

```bash
# 诊断状态应从 pending -> running -> completed
curl -s https://你的域名/api/v1/events/$EVENT_ID/diagnostics | python3 -m json.tool

# 关键：Agent 通过 Caddy 成功 claim/complete 证据（不是 401）
$DC logs --since 5m api | grep -iE 'evidence|diagnostic'
# 证据请求记录
$DC exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT id, status, error FROM evidence_requests ORDER BY created_at DESC LIMIT 5;"'
# 诊断结果与证据
$DC exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT id, status, provider, error_code FROM diagnostic_runs ORDER BY created_at DESC LIMIT 3;"'
$DC exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT evidence_type, redacted, truncated, length(content) FROM evidence_items ORDER BY collected_at DESC LIMIT 6;"'
```

确认：
- `evidence_requests` 至少一条 `completed`（不是长期 `pending`，更不是因 401 失败）。
- `diagnostic_runs` 状态 `completed`，`provider=deterministic`。
- `evidence_items` 有 5 项左右（告警/服务状态/指标/版本/日志），`redacted=true`，日志项 `truncated` 符合预期，且**内容里不含真实密钥**（可抽查 `content`）。
- 钉钉卡片链接现在指向 `/events/<id>` 诊断页，浏览器能打开。

### 5.4 恢复

```bash
docker start <容器名>        # 等 ~35s -> Resolved + 恢复通知
```

## 6. 验收标准

- [ ] 控制平面升级后 M3 的 10 张表已建，4 台 Agent（含仍是 v0.2.4 的）持续上报 200。
- [ ] Caddyfile validate 通过，evidence-requests 经 Caddy 不返回 401。
- [ ] 至少一台 Agent 升级到 v0.3.0 并正确声明证据源。
- [ ] 一个真实服务完成映射（目录/日志源/仓库/版本）。
- [ ] 一次真实 Firing 事件能走完诊断闭环：pending -> running -> completed，证据带来源、已脱敏、有大小限制。
- [ ] 诊断链路无任意 Shell、任意路径读取或写操作入口。
- [ ] M1/M2 监控与告警行为未受影响。

## 7. 回滚预案

**控制平面**（M3 只新增表，不改 M1/M2 既有表）：
```bash
cd /opt/vps-agent-console
git checkout 3cae0d5
$DC build api web
$DC up -d --no-deps api web
$DC exec caddy caddy reload --config /etc/caddy/Caddyfile   # 回滚 Caddyfile
```
M3 表留在库中无副作用（旧代码不读它们）。`v0.3.0` Agent 与回滚后的控制平面兼容（`evidence_sources` 缺省为空，M2 告警照常），诊断功能关闭。

**Agent**（如需）：
```bash
# 在 VPS 上用安装器指定旧版本降级回 v0.2.4（身份保留）
```

数据必要时从 Phase 2 的备份恢复。

## 8. 完成后

- 在 `docs/PROJECT_STATUS.md` 记录本次金丝雀端到端结果，但 **M3 仍保持"进行中"**：按新路线图，自动发现 + Web 确认未完成前不标记 M3 已完成。
- **下一步不是向更多 VPS 推广手工白名单**，而是做 M3 产品化：Agent 自动发现稳定服务身份 + 证据源目录、Web 发现/确认流程，让用户不用再手填容器 ID / `source_key` / JSON。
- 接真实 AI 提供者（`http_json`）前先用 `deterministic` 跑稳。
- 剩余 M3 项（Agent 失联/恢复事件、GitHub App 最小读取、更多日志源）按路线继续。

## 9. 已知限制（首版）

- **手工白名单是兼容/过渡路径**：本清单的 `AGENT_EVIDENCE_SOURCES_JSON` + 手动服务映射只为验证安全边界，终局是 Agent 自动发现 + Web 确认（见路线图 M3 产品化缺口）。
- 证据采集在每个上报周期处理一条、最多阻塞 15s（`send()` 串行）；请求堆积时上报会滞后。
- 默认 `deterministic` 提供者不做真实根因判断，只整理带引用的事实。
- Agent 失联/恢复事件、systemd journal、文件日志、GitHub App 读取均未含在本批。
