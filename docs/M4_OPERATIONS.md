# M4 安全处置协议与验收

本文记录 M4 第一条纵向闭环：管理员对一个已映射、Agent 本地明确授权、控制平面标记为非关键且允许写操作的 Docker 单服务发起安全重启。当前不提供 Pull、部署、回滚、清理、systemd 写操作、任意命令、任意参数、任意路径或 Shell。

## 1. 可复用基线与边界

- M1：一次性注册、独立 Agent Bearer 凭证、新鲜心跳、Docker 状态和主动出站 HTTPS。
- M2：告警只能由真实服务观测进入 Resolved；操作成功不能直接关闭事件。
- M3：`ManagedService -> ServiceInstance -> Agent + stable service_key`、Agent 本地 target 隔离、自动发现能力目录、双端脱敏、Agent 主动领取和 Caddy Bearer 路由。
- M4 新增独立写能力目录 `AgentOperationCapability`。目录只有 `action_type + service_kind + service_key`，没有容器名、容器 ID、argv、命令或路径。
- 现有服务迁移后默认 `criticality=critical`、`restart_enabled=false`；现有和新 Agent 默认 `AGENT_OPERATION_POLICY=disabled`。

写操作必须同时满足：Agent 本地开启 `docker_restart`、Agent 当前声明具体稳定服务键、控制平面映射被明确标记为 `non_critical` 且 `restart_enabled=true`、计划预检查通过、管理员确认、Ed25519 验签通过。任一条件缺失即拒绝。

## 2. 数据模型

- `agent_operation_capabilities`：Agent 当前声明的服务级写能力，不保存 target。
- `managed_services.criticality`：当前只允许 `critical` 或 `non_critical`。
- `service_instances.restart_enabled`：控制平面对具体映射的显式授权。
- `operations`：冻结计划、来源事件/诊断、状态、签名任务字段、租约、有限执行结果、验证结果和失败原因。
- `operation_transitions`：每次状态转换、操作者、原因、时间和有限结构化细节。

`operations.active_key=<instance_id>:write` 在活动状态下非空且唯一，利用 PostgreSQL 唯一约束阻止单 API 或多 API 实例并发创建同一服务写操作；终态清空该键。

审计时间线在应用协议内只追加，当前 API 没有修改或选择性删除转换记录的端点；它不是对数据库所有者或 DBA 的密码学防篡改证明。PostgreSQL 是本阶段的可信审计事实源，具备数据库写权限的人员仍能改写数据，备份与恢复也必须纳入运维审计。若未来需要面对不可信 DBA 的合规证明，应使用外部不可变存储或带外锚定的哈希链，不能把普通表或未锚定哈希链表述为“不可篡改”。

当前控制台只有一个管理令牌身份，因此 `requested_by`/`confirmed_by=local-admin` 的含义是“持有该控制台管理凭据的操作者”，不能区分共享凭据背后的个人。引入多管理员身份、独立凭据和个人归属后再提升 actor 粒度。

## 3. 状态机

活动状态：`planned`、`prechecking`、`awaiting_confirmation`、`queued`、`claimed`、`running`、`verifying`。

终态：`succeeded`、`failed`、`canceled`、`expired`。

```text
planned -> prechecking -> awaiting_confirmation -> queued
queued -> claimed -> running -> verifying -> succeeded
                                      |             |
                                      +-----------> failed
awaiting_confirmation/queued -> canceled
活动但未开始的过期任务 -> expired
```

- 控制平面负责计划、预检查、确认后签发、验证和终态。
- Agent 只能从 `queued` Claim、把 `claimed` 标记为 Running，并回传 Completed/Failed 执行结果。
- 确认前计划不能领取。确认动作冻结展示过的目标、风险、影响、验证策略和稳定服务身份；不存在修改已签任务的 API。
- `claimed` 租约过期可领取同一个 attempt；签名任务和幂等键不变。Agent 本地账本保证响应丢失不会再次重启。
- 状态转换由显式允许表约束，非法跳转直接拒绝。租约重领会保留一条 `claimed -> claimed` 审计事件并标记 `lease_reclaimed=true`；它记录一次实际领取动作，不代表业务状态发生变化，普通成功路径仍为八条转换记录。
- `running` 租约为 Agent 固定执行超时加结果上传缓冲；超时后不会自动重放，因为控制平面无法证明 Docker 是否已收到命令，该任务进入 `failed/execution_outcome_unknown`。
- `verifying` 在 API 重启后由后续 Agent 报告继续推进；签名任务的 `expires_at` 不会截断已经开始的独立健康验证，只有验证截止时间到达才进入 Failed。
- 第一轮不自动创建第二个 attempt。需要再次处置时重新创建、预检和确认新操作，得到新 operation ID、nonce 和幂等键。

## 4. 签名与防重放

Bearer 凭证只认证 Agent 与领取/回传请求，不承担任务签名。控制平面使用独立 Ed25519 私钥签名，Agent 只保存固定公钥和 key ID。

签名输入为 UTF-8、换行连接的固定顺序字段：

```text
v1
operation_id
action_type
agent_id
service_kind
service_key
issued_at (UTC second precision)
expires_at (UTC second precision)
idempotency_key
attempt
nonce
key_id
```

任务没有 JSON 参数扩展位，不包含 target、命令、argv、Unit 或路径。Agent 验证签名、key ID、Agent ID、动作枚举、服务类型、签发时间、过期时间、nonce 和幂等键。

Agent 在 `/var/lib/vps-agent/operations.json` 以 `0600` 保存有界本地账本。执行前先持久化 Started；完成后先持久化结构化结果再上传。崩溃后遇到 Started 记录会报告 `execution_outcome_unknown` 而不是重复执行；Completed 未确认送达的结果会重试上传。账本最多保留 1024 项，空间不足时只淘汰已确认送达的旧记录；如果 1024 项全部尚未送达，则拒绝开始新执行而不丢弃待上传结果。

当前使用单个活动 key ID。轮换时应先把新公钥分发给 Agent，再切换控制平面签名 key；多公钥重叠轮换属于后续加固，不能在 Agent 尚未信任新 key 时直接替换私钥。

## 5. Agent 本地 target 解析与执行

安装时使用 `--operation-policy docker-restart`，并同时提供控制平面签名公钥和 key ID。旧安装保持 disabled。

Agent 每次执行前重新运行固定 Docker 列举程序，用与 M3 完全相同的稳定键算法匹配当前容器：Compose 使用 project/service/container-number，普通 Docker 使用容器名。必须恰好匹配一个当前容器；消失或出现歧义均拒绝。

随后只调用固定程序和固定参数：

```text
docker restart -- <仅在本地解析的 target>
```

不经过 Shell，不接收控制平面的 target 或 argv。执行超时固定为 30 秒。成功输出为固定摘要，不上传容器 target；错误只上传枚举错误码和脱敏、截断后的有限说明。

## 6. API 与数据流

1. `POST /api/v1/operations` 从 instance 或服务事件解析唯一映射并执行预检查。
2. Web 展示机器、服务、环境、风险、影响、预检结果、有效期和验证条件。
3. `POST /api/v1/operations/{id}/confirm` 重新预检、记录确认人和时间、签名并进入 Queued。
4. Agent 独立轮询 `GET /api/v1/agents/operations/next`；该循环不依赖资源报告或 M3 证据采集。
5. Agent 本地验签并先持久化幂等账本，随后调用 `/start`、执行固定 Docker restart，再调用 `/complete`。
6. 退出 0 只进入 Verifying。控制平面等待同一 stable service_key 的新报告；状态必须为 running、healthy=true，并持续满足稳定窗口。
7. 最终状态和每次转换进入审计。关联事件仍由 M2 真实观测决定是否 Resolved。

Caddy 将 `/api/v1/agents/operations/*` 与注册、报告和证据端点同样归入 Agent Bearer API，限制请求体 1 MiB；FastAPI 进一步把输出限制为默认 100 行、16 KiB，Agent 结果结构上限为 64 KiB。管理写 API 和 Web 受控制台 Basic Auth 与服务端管理令牌保护。与现有 M1–M3 读接口一致，操作详情读接口依赖“API 容器网络可信、外部流量只经 Caddy”的边界；若内部网络不可信，应给读接口增加独立管理认证并同步调整 Web 服务端调用。

任务 JSON 采用固定字段，Agent 使用严格解码拒绝未知字段；控制平面 `OperationTask` 模型也禁止额外字段。新增任务字段必须升级协议版本并协调 Agent 升级，不能静默扩展可执行载荷。

## 7. 配置

控制平面：

```dotenv
OPERATION_SIGNING_KEY_ID=m4-2026-01
OPERATION_SIGNING_PRIVATE_KEY_BASE64=
OPERATION_OBSERVATION_MAX_AGE_SECONDS=120
OPERATION_CLAIM_LEASE_SECONDS=60
OPERATION_EXECUTION_TIMEOUT_SECONDS=30
OPERATION_EXECUTION_RESULT_GRACE_SECONDS=15
OPERATION_VERIFICATION_WINDOW_SECONDS=30
OPERATION_VERIFICATION_TIMEOUT_SECONDS=180
OPERATION_MAX_OUTPUT_BYTES=16384
OPERATION_MAX_OUTPUT_LINES=100
```

Agent：

```dotenv
AGENT_OPERATION_POLICY=disabled
AGENT_OPERATION_KEY_ID=
AGENT_OPERATION_PUBLIC_KEY_BASE64=
AGENT_OPERATION_POLL_INTERVAL=5s
AGENT_OPERATION_STATE_FILE=/var/lib/vps-agent/operations.json
```

私钥只能留在控制平面；公钥可进入安装命令。Linux 上可生成一组原始 Ed25519 Base64 值：

```bash
umask 077
openssl genpkey -algorithm ED25519 -out /tmp/vps-agent-m4-ed25519.pem
openssl pkey -in /tmp/vps-agent-m4-ed25519.pem -outform DER | tail -c 32 | base64 -w0
openssl pkey -in /tmp/vps-agent-m4-ed25519.pem -pubout -outform DER | tail -c 32 | base64 -w0
rm -f /tmp/vps-agent-m4-ed25519.pem
```

第一行 Base64 输出写入控制平面的 `OPERATION_SIGNING_PRIVATE_KEY_BASE64`，第二行分发为 Agent 的 `AGENT_OPERATION_PUBLIC_KEY_BASE64`；不要把真实私钥提交到仓库。控制平面和 Agent 必须使用 NTP/chrony 保持时钟同步，当前任务验签只容忍 Agent 时钟比签发时间落后 30 秒。若签名配置缺失，确认接口返回受控 503，监控和只读诊断继续工作。

## 8. 失败与恢复语义

- 未确认、过期、签名错误、字段篡改、未知动作、Agent ID/key ID 不匹配或本地策略关闭：不执行。
- Claim 响应丢失：租约后可再次领取同一任务；幂等键和本地账本阻止重复重启。
- Agent 在执行前离线：任务保留到 Claim 租约或有效期；未进入 Running 时不会声称执行。
- Agent 在 Running 崩溃：受控失败为 outcome unknown，不自动重放。
- Docker 返回 0 但服务 unhealthy、health starting、缺失或未达到稳定窗口：操作最终 Failed。
- API 在 Claimed/Running/Verifying 重启：数据库状态保留；Claim 租约、Running 超时和后续报告恢复处理。
- 操作结果不会写入 M2 事件状态；真实 Docker 观测仍是唯一恢复依据。

## 9. 第一轮范围与验收

已实现自动化覆盖：未确认不可领取；并发唯一约束冲突返回 409；任务字段签名；篡改、过期、key ID/attempt/签名长度和本地策略关闭拒绝；未知动作拒绝；取消的合法/非法状态；确认前预检漂移；Running/Verifying/Expired 陈旧恢复；`SKIP LOCKED` Claim；本地账本崩溃防重放和未送达结果保留；退出 0 进入 Verifying；双端输出限制与脱敏；健康稳定窗口成功；Docker unhealthy 不视为健康；现有 M1/M2/M3 回归。

Agent Docker 健康语义在 `v0.4.0` 有一项有意修正：`running (unhealthy)` 现在上报 `healthy=false`，会触发此前漏掉的 M2 异常；`health: starting` 上报 `healthy=null`，不会在正常重启窗口直接触发异常，也不会被 M4 当作验证成功。升级前应检查现有带 healthcheck 的容器，避免把新增的真实 unhealthy 告警误认为升级故障。

2026-07-20 使用独立 Compose 项目完成真实隔离验收，包含 PostgreSQL、Redis、Caddy、API、Web、Agent 和非关键 Docker canary：

- Caddy 的 Agent 健康与 Bearer 路由可达，控制台管理路由在无 Basic Auth 时返回 401。
- 确认前 Agent 无法 Claim；确认后成功重启，canary 的 Docker `StartedAt` 改变，后续健康报告跨越稳定窗口后进入 Succeeded，审计保留完整八次转换且结果不包含本地 target。
- Docker 命令退出 0 但 canary 持续 unhealthy 时，操作停留 Verifying 后以 `verification_timeout` 失败。
- 重复 Complete 返回同一终态且不增加审计；同一服务已有活动操作时第二个计划返回 409；取消后可再次计划；关闭映射重启策略后预检拒绝。
- Agent 确认后离线时任务保持 Queued，Agent 恢复后成功完成。API 在 Claimed 状态重启后由租约和本地账本安全续接；在 Running 状态重启且结果未知时进入 `execution_outcome_unknown`，不自动重放；在 Verifying 状态重启后由新鲜健康报告继续并成功。
- 使用 M3 基线代码创建 `0005` 旧结构和旧数据，再由当前 Alembic 升级到 `0006_m4_safe_operations`；Agent、服务、实例和 M2 事件均保留，新增策略默认 `critical`/`restart_enabled=false`。同时修复在线迁移事务未显式提交的既有问题。

自动检查通过 API 102 项测试、Web 26 项测试、全部 Go 包测试、Ruff、ESLint、`go vet` 和 Web 生产构建。隔离项目及其测试卷在验收后删除。

### 生产发布与金丝雀（2026-07-20/21）

M4 首批通过提交前安全审计（有条件通过，全部 P2/P3 已处理），提交 `84cb4a2` 推送至 `main`，并发布 `v0.4.0` Release（标签触发 GitHub Actions：先 `go test ./...`，再构建 amd64/arm64 + 安装器 + SHA256SUMS）。

生产金丝雀在 aliyun VPS（新机、无其他业务、有 Docker）跑通端到端闭环：

- 控制平面升级到 `84cb4a2`（API/Web 重建 + 手动加列、Caddy reload，见 §10），配置 Ed25519 签名密钥；金丝雀 Agent 以 `--operation-policy docker-restart` 安装 `v0.4.0`。
- `m4-canary`（compose 服务，stable key `compose:m4canary:m4-canary:1`）映射为 `non_critical` + `restart_enabled=true`。
- 创建计划 -> 确认（Ed25519 签发）-> `queued -> claimed -> running -> verifying -> succeeded`，审计 8 次转换完整，`output` 为固定摘要、不含容器 target。
- Agent 经 Caddy Bearer 轮询领取并验签，本地按 stable service_key 重解析 target 后以固定 `docker restart --` 执行（无 Shell），退出 0 后由后续新鲜健康观测跨越 30s 稳定窗口判定 `succeeded`（非退出码判定）。

非 Docker 的 VPS（DMIT/腾讯云）无需为了首轮 M4 单独升级：`docker_restart` 只对 Docker 生效，`healthy` 语义修正只在 Docker 解析路径；旧 v0.3.x Agent 与 v0.4.0 控制平面兼容。若仍升级到 v0.4.0（策略 disabled），Agent 会初始化本地账本并以默认 5s 轮询空操作队列（无任务、不执行写操作），属可接受的额外空轮询，而非零行为变更。

## 10. 生产部署注意事项（控制平面）

M4 控制平面从 v0.3.x 升级到 v0.4.0 时，除常规 `git pull` + `docker compose build` + `up -d` 外，需注意以下三项：10.1、10.2 为本次金丝雀部署中实际遇到并处理的坑，10.3 为签名密钥配置要点。

### 10.1 迁移 0006 是首个给既有表加列的迁移

`0006_m4_safe_operations` 是项目第一个对既有表 `ALTER ADD COLUMN` 的迁移（`managed_services.criticality`、`service_instances.restart_enabled`）。此前 0001–0005 全部只建新表，生产一直靠 API 启动时的 `Base.metadata.create_all` 即可（create_all 只建缺失的表，不改既有表结构）。M4 之后 create_all 仍会建出 `operations`/`operation_transitions`/`agent_operation_capabilities` 三张新表，但**不会**给既有表加这两列；若不加列，任何加载 `ManagedService` 的查询（含 M3 服务映射候选）会因列缺失报错。升级时必须补这两列（幂等，等效 0006 的列部分）：

```bash
$DC exec -T postgres sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' <<'SQL'
ALTER TABLE managed_services   ADD COLUMN IF NOT EXISTS criticality     VARCHAR(32) NOT NULL DEFAULT 'critical';
ALTER TABLE service_instances ADD COLUMN IF NOT EXISTS restart_enabled BOOLEAN     NOT NULL DEFAULT false;
SQL
```

**执行顺序**：先 `pg_dump` 备份；在旧 API 仍运行时执行上述 ALTER（加列对旧 API 无影响，旧代码不读这两列）；用 `\d managed_services` / `\d service_instances` 确认列存在；再 `build` 并 `up -d` 启动新 API。切勿先启动新 API 再加列--新 API 的 `/healthz` 健康检查不读这两列，可能健康通过，但服务映射候选等查询会在缺列时报错。

API Dockerfile 未包含 `migrations/` 与 `alembic.ini`，故不能在容器内跑 `alembic upgrade head`；自托管环境用上述手动 ALTER 即可，0006 的 `has_column`/`has_table` 守卫保证未来引入 alembic 也不会重复执行。

### 10.2 Caddyfile 变更后必须 reload

`Caddyfile` 以只读 bind-mount 挂入 caddy 容器。`docker compose up -d` 只重建发生变化的容器；caddy 服务定义未变时容器不会重建，运行中的 caddy 不会自动读取新 Caddyfile。M4 在 `@agent_api` 路由新增了 `/api/v1/agents/operations/*`，若不重载，Agent 轮询 `operations/next` 会被旧 Caddy 当作管理 API 挡到 Basic Auth 返回 401（空响应体），而上报 `/agents/report` 因原本就在 Bearer 路由仍正常——“上报正常、操作轮询 401”是典型症状。

```bash
$DC exec caddy caddy reload --config /etc/caddy/Caddyfile
# 若 reload 不生效（单文件 bind mount 指向旧 inode），restart 仍读旧挂载、无效；需重建容器重新挂载：
# $DC up -d --no-deps --force-recreate caddy
```

> M3 的 GitHub App 金丝雀曾遇到 `caddy reload` 不生效、需 `--force-recreate caddy` 的情况（见 PROJECT_STATUS.md §5）。M4 本次 `caddy reload` 生效；若遇异常，用 `--force-recreate`（`restart` 不会重建挂载，对旧 inode 无效）。

### 10.3 Ed25519 签名密钥

控制平面生成 Ed25519 密钥对（命令见 §7）：私钥只写入 `OPERATION_SIGNING_PRIVATE_KEY_BASE64`，公钥写入 web env（`AGENT_OPERATION_PUBLIC_KEY_BASE64`，用于安装命令展示）和 Agent 安装命令。确认接口在签名配置缺失时返回 503，只读链路不受影响。
