# M3 只读诊断协议与配置

本文记录 M3 只读诊断纵向闭环的当前实现。它覆盖已登记 Docker/systemd 服务的有限日志取证、GitHub App 授权仓库的白名单文件快照、控制平面上下文和结构化诊断，不提供 Shell、服务重启、部署、回滚或任意路径读取。

## 1. 身份与数据模型

- `ServiceStatus` 仍是 Agent 最近一次上报的瞬时观测，不承担业务服务身份。
- `ManagedService` 表示业务服务，`ServiceInstance` 使用 `(agent_id, service_kind, service_key)` 绑定一个实际运行实例。
- `InstanceLogSource` 只保存稳定的 `source_key`、类型和展示名；Docker 容器和 systemd Unit 目标只存在于 Agent 本地配置或当前进程内存。
- `AgentEvidenceSourceBinding` 保存 Agent 主动声明的来源与稳定服务键关联，不保存容器名、Unit、路径或命令。
- `Repository` 与 `DeploymentVersion` 保存仓库名、部署 Commit SHA 或镜像摘要；`GitHubRepositoryBinding`、`GitHubRepositoryFile` 和 `GitHubWebhookDelivery` 分别保存 GitHub App 安装授权、白名单文件快照和不含原始载荷的 Webhook 审计记录。安装令牌不持久化，GitHub 凭据不下发给 Agent。
- `DiagnosticRun`、`EvidenceRequest`、`EvidenceItem` 与 `DiagnosticCitation` 分别保存诊断状态、出站请求、脱敏后的原始观察证据和结论引用关系。AI 结论不写回证据内容。

## 2. Agent 自动能力目录与手工兼容方式

安装时明确选择诊断策略后，Agent 会为本机已发现的 Docker 容器和/或 systemd Unit 自动生成有限日志能力：

```dotenv
AGENT_EVIDENCE_POLICY=docker_logs
# 或 systemd_journal
# 或 docker_logs,systemd_journal
```

未配置或配置为 `disabled` 时不会自动开放日志能力，已有 Agent 升级不会静默扩大权限。安装器支持 `--evidence-policy disabled`、`docker-logs`、`systemd-journal` 和 `docker-systemd`；未知策略整体按 `disabled` 处理，不部分放行。

手工白名单继续作为兼容和特殊服务入口：

```dotenv
AGENT_EVIDENCE_SOURCES_JSON='[{"key":"payment-api-logs","kind":"docker_logs","target":"payment-api","display_name":"payment-api-logs"}]'
# systemd 示例：
# AGENT_EVIDENCE_SOURCES_JSON='[{"key":"payment-api-journal","kind":"systemd_journal","target":"payment-api.service","display_name":"payment-api-journal"}]'
```

`key` 是控制平面可引用的稳定标识；`target` 是本机 Docker 容器名/ID 或以 `.service` 结尾的 systemd Unit，不会随报告上传。systemd 目标不能以 `-` 开头且只能使用 Unit 名允许的有限字符；非法 JSON、重复键、未知类型、空目标或不符合 `[a-zA-Z0-9._-]+` 的键会被忽略。升级安装器会保留这项配置。

自动能力目录的当前规则：

- Docker Compose 实例使用 `compose:<project>:<service>:<container-number>`；普通容器使用 `docker:<container-name>`。超长键使用确定性摘要收敛。
- systemd 使用采集器已发现的 Unit 名作为稳定服务键，并由该键确定性生成 `systemd-journal-...` 来源键。
- 日志 `source_key` 根据稳定服务键生成，真实容器目标只保存在 Agent 当前进程内，不随报告上传。
- Agent 最多声明 128 个来源；手工来源优先于同键自动来源，并在目标匹配已发现容器时补充稳定服务关联。
- 控制台机器详情页展示 Agent 已授权的候选服务，用户确认业务名称、环境及可选目录/仓库即可建立映射，不需要填写容器 ID、`source_key` 或 JSON。
- 控制平面仍只能请求 Agent 已声明的来源键，并继续下发和校验时间、行数、字节数和超时上限；自动发现不等于允许任意日志、路径或命令。
- 现有环境变量在迁移期保留，用于兼容已部署 Agent、特殊服务和故障排查。

## 3. 只读出站协议

1. Agent 在常规报告中声明证据源的 `key`、`kind`、展示名和可选稳定服务关联，不声明真实容器目标。
2. `GET /api/v1/agents/{agent_id}/service-mapping-candidates` 只返回已观测且被 Agent 本地能力目录关联的 Docker/systemd 服务；机器详情页通过服务端代理调用 `POST /api/v1/service-mappings`，管理令牌不进入浏览器。
3. `POST /api/v1/events/{event_id}/diagnostics` 手动触发诊断。同一事件同时只允许一个 Pending/Running 诊断。
4. 控制平面先保存告警、最新服务状态、最新资源快照和部署版本证据，再创建只包含 `source_key`、时间窗口、行数、字节数和超时的请求。
5. Agent 通过 `GET /api/v1/agents/evidence-requests/next` 主动领取请求，在本地用 `source_key` 查找目标；未命中本地白名单时直接失败，不接受控制平面提供容器名或命令。
6. Docker 来源使用固定参数调用 `docker logs`，并在容器目标前加入 `--` 参数分隔符；systemd 来源使用固定参数调用 `journalctl --unit <本地 Unit> --since <RFC3339> --until <RFC3339> --lines <上限> --output=short-iso --no-pager`。两者都不经过 Shell，结果在上传前脱敏并按上限截断，再通过 `POST /api/v1/agents/evidence-requests/{id}/complete` 回传。
7. 控制平面再次执行行数、字节数和敏感信息限制，然后调用诊断提供者并验证固定结构及全部证据引用。

### Agent 失联、恢复与机器级诊断

- 控制平面维护循环每 `AGENT_AVAILABILITY_SCAN_INTERVAL_SECONDS` 秒检查一次 `last_seen_at`。当最后心跳早于 `AGENT_OFFLINE_AFTER_SECONDS` 阈值时，创建 `source=agent` 的机器级 Firing 事件；实际发现延迟最多再增加一个巡检周期。API 每次启动先等待一个完整失联阈值，让仍存活的 Agent 重新上报，避免把控制平面自身停机误报为整批 VPS 失联；通知重试不等待该宽限期。
- 巡检使用 Agent 行锁和 `SKIP LOCKED`；Agent 报告在更新 `last_seen_at` 前锁定同一行并解析活动失联事件。多 API 实例及巡检/恢复竞争不会生成第二个活动事件。
- 失联与恢复继续使用 M2 活动指纹、确认/静默和通知序号，重复离线巡检不重复发送；恢复投递沿用同一事件的下一个 sequence。
- 独立维护循环同时重试 Pending、Failed 和陈旧 Sending 通知，不依赖任何 Agent 后续报告，因此所有 Agent 都离线时仍能发送失联告警。
- 机器级手动诊断不等待离线 Agent，也不创建证据请求。它只保存控制平面的告警事件、最后心跳、非敏感 Agent 元数据、最后资源快照和最多 128 条最后服务状态，再交给同一结构化诊断提供者。

相关配置：

```dotenv
AGENT_OFFLINE_AFTER_SECONDS=90
AGENT_AVAILABILITY_SCAN_INTERVAL_SECONDS=30
```

巡检周期必须不大于失联阈值。两项配置分别限制在 30–3600 秒和 5–300 秒。

首个映射请求示例（`X-Admin-Token` 只由受信任管理端持有）：

```json
{
  "name": "payment-api",
  "environment": "production",
  "agent_id": "已注册 Agent ID",
  "service_kind": "docker",
  "service_key": "compose:payments:payment-api:1",
  "deployment_directory": "/opt/apps/payment-api",
  "log_source_key": "payment-api-logs",
  "repository_full_name": "example/payment-api",
  "default_branch": "main",
  "commit_sha": "0123456789abcdef0123456789abcdef01234567",
  "image_digest": "sha256:example"
}
```

默认硬上限为最近 15 分钟、200 行、64 KiB、10 秒；代码级最大值为 500 行、64 KiB、15 秒。Agent 与控制平面都会执行限制。

## 4. GitHub App 最小只读闭环

GitHub 集成只存在于控制平面。首版使用单个安装 ID，GitHub App 权限只需要 Repository contents: Read-only；Agent 不接收 App 私钥、安装令牌或仓库凭据。

```dotenv
GITHUB_APP_ID=
GITHUB_APP_PRIVATE_KEY_BASE64=
GITHUB_APP_INSTALLATION_ID=
GITHUB_APP_SLUG=
GITHUB_WEBHOOK_SECRET=
GITHUB_API_URL=https://api.github.com
GITHUB_API_VERSION=2026-03-10
GITHUB_ALLOWED_FILE_PATHS=README.md,docker-compose.yml,compose.yaml
GITHUB_MAX_FILE_BYTES=65536
GITHUB_WEBHOOK_MAX_BYTES=1048576
GITHUB_SYNC_CONCURRENCY=4
GITHUB_WEBHOOK_RATE_LIMIT_PER_MINUTE=120
```

- App ID、Base64 编码的 PEM 私钥、安装 ID 和 Webhook Secret 必须同时配置，否则 API 拒绝启动；示例配置不包含真实凭据。
- 控制平面用短期 RS256 App JWT 换取安装令牌，令牌只存在于单次同步内存中；已解析私钥在单个 API 进程内使用最多 2 项的小缓存，轮换配置后旧值不会无限保留。每次同步最多读取 1000 个安装授权仓库、最多 16 个精确白名单路径；每个文件最多 64 KiB。仓库读取默认 4 路并发，可配置为 1–8，避免完全串行或瞬时打满 GitHub。
- 文件按默认分支当前 Commit SHA 读取，脱敏后保存。仓库 HEAD 只表示诊断上下文快照，不冒充 `DeploymentVersion.commit_sha` 所表示的实际部署版本。
- `POST /api/v1/github/webhooks` 在 Caddy 中仅豁免 Basic Auth，并同时限制为 1 MiB；FastAPI 在解析 JSON 和写库前校验 `X-Hub-Signature-256`。投递 ID 去重，只保存事件、动作、安装 ID、处理状态和有限错误，不保存原始载荷。
- `push`、`installation` 和 `installation_repositories` 触发重新同步；安装删除或暂停会立即把本地绑定置为不可用并删除对应文件快照，后续诊断不会继续引用已撤销仓库数据。
- Webhook 使用 Redis 提供跨 API 实例的固定分钟窗口，默认每分钟 120 次，设置为 `0` 可关闭。超过上限返回 429；Redis 临时不可用时记录不含载荷/凭据的告警并继续执行 Caddy 请求体限制和 HMAC 验签，避免缓存故障阻断 GitHub 通知。
- Web 只展示已授权仓库并通过服务端代理触发同步；管理令牌和 GitHub 凭据不进入浏览器。配置 GitHub App 后，新服务映射不能关联安装范围外的仓库。
- 诊断最多加入 8 个仓库文件、总计 128 KiB，标记为不可信输入并再次经过控制平面脱敏。首版不做全仓库同步、代码搜索、向量索引、分支写入或 PR 创建。

## 5. 诊断提供者

默认 `DIAGNOSTIC_PROVIDER=deterministic` 用于开发和测试。它只把已有证据整理为带引用的事实，不声称完成根因判断。

配置 `DIAGNOSTIC_PROVIDER=http_json` 后，控制平面向受信任的模型网关发送模型名、不可被远程文本修改的诊断约束，以及标记为 `untrusted_content` 的证据。网关必须直接返回诊断对象，或返回 `{ "result": <诊断对象> }`：

```json
{
  "summary": "简短摘要",
  "facts": [{"statement": "可验证事实", "evidence_ids": ["evidence-id"]}],
  "inferences": [{"statement": "可能原因", "confidence": "medium", "evidence_ids": ["evidence-id"]}],
  "recommendations": [{"action": "建议操作", "risk": "low", "requires_confirmation": true, "prerequisites": []}],
  "missing_evidence": []
}
```

相关配置：

```dotenv
DIAGNOSTIC_PROVIDER=http_json
DIAGNOSTIC_API_URL=https://trusted-model-gateway.example/v1/diagnose
DIAGNOSTIC_API_KEY=
DIAGNOSTIC_MODEL=ops-diagnostic
DIAGNOSTIC_TIMEOUT_SECONDS=30
DIAGNOSTIC_RUN_STALE_SECONDS=300
```

模型响应限制为 256 KiB。超时、HTTP 错误、非法 JSON、结构错误或引用未知证据都会把诊断标记为 `failed`，不会执行任何建议。

`DIAGNOSTIC_RUN_STALE_SECONDS` 必须大于模型调用超时。Agent 领取/完成证据请求以及管理员重新触发诊断时会顺带回收陈旧任务：崩溃遗留的 Running 诊断会重新调用提供者；长期 Pending/Claimed 的证据请求会标记为 Failed，诊断继续完成并在 `missing_evidence` 中注明日志采集失败或超时。活动键最终会在 Completed/Failed 时释放。

## 6. 脱敏与不可信输入

Agent 和控制平面均遮蔽 Authorization、Bearer Token、密码、Cookie、Webhook、常见 Token/Secret/API Key 字段和私钥块。数据库保存的是脱敏后但尚未被 AI 改写的观察证据；诊断结论和引用关系存放在独立表中。

日志、仓库内容、服务输出和模型响应全部是不可信输入。它们只能作为证据或文本结果，不能改变可用工具、白名单、审批规则或执行权限。

## 7. Caddy 与请求边界

生产 Caddy 将注册、报告和 `/api/v1/agents/evidence-requests/*` 统一归入 Agent Bearer API，不要求控制台 Basic Auth；FastAPI 仍使用 `current_agent` 校验独立 Agent 凭证。该路由的请求体上限为 1 MiB，合法证据完成请求仍受 Pydantic 的 128 KiB 字符上限和证据自身 64 KiB 字节上限约束。GitHub Webhook 另用精确路径豁免 Basic Auth，并由 1 MiB Caddy 限制和应用层 HMAC 验签共同保护；其他 GitHub API 仍在控制台认证之后。

## 8. 验证记录

2026-07-17 使用隔离 Compose 项目启动真实 Caddy、FastAPI、PostgreSQL、Redis 和 Web，并启动挂载只读采集所需 Docker Socket 的测试 Agent：

- 官方 `caddy:2-alpine` 执行 `caddy validate --config /etc/caddy/Caddyfile`，结果为 `Valid configuration`。
- 向 Agent 完成端点发送超过 1 MiB 的测试请求体，Caddy 在进入 FastAPI 前返回 413。
- Agent 仅通过 Caddy 服务名完成一次性令牌注册和连续报告，没有提供 Basic Auth 凭据。
- 停止的金丝雀容器形成真实 M2 Firing 事件；创建 `docker_logs` 白名单映射后从事件手动触发诊断。
- Agent 经 Caddy 成功 Claim 和 Complete 证据请求，日志记录 `evidence request completed`，没有出现 401。
- 确定性提供者把诊断推进到 Completed，共保存 5 项事件、状态、指标、版本和 Docker 日志证据；测试敏感值未进入持久化证据。

测试使用独立项目名、临时测试凭据和独立数据卷；结束后清理，不涉及生产环境。

2026-07-19 在生产金丝雀完成同一闭环实证：停止 canary 后依次形成 Firing 和钉钉异常卡；手动触发诊断后，Agent 经 Caddy 成功 Claim/Complete，没有 401；Agent 与控制平面双重脱敏后，持久化证据中 `fake-secret` 计数为 0，`[REDACTED]` 计数为 100；诊断进入 Completed，并输出 4 条带证据引用的事实；重启 canary 后事件进入 Resolved，钉钉收到恢复卡。控制平面不能指定容器目标、固定 Docker 参数与 `--` 分隔、证据限制、只读诊断和结构化引用均得到生产实证。

同日使用隔离的真实 PostgreSQL、API、Agent 和 Docker Compose 栈验证产品化首批：Agent 自动声明 8 个 Docker 稳定身份和对应日志能力；候选 API 成功创建服务映射，请求与数据库均未包含本地容器目标；重启已映射 API 容器后稳定键和映射保持不变。另用旧容器 ID 构造真实 Firing 和既有映射，再上报稳定键与来源关联，事件正确迁移并进入 Resolved，原映射继续标记为已关联。测试使用临时凭据、独立项目和数据卷，完成后全部清理。

2026-07-19 v0.3.1 产品化金丝雀（自动发现模式）在生产 control-plane 宿主机实证同一闭环：control-plane Agent 保留身份升级到 `v0.3.1` 并以 `--evidence-policy docker-logs` 开启自动发现，全程不手工编辑证据源 JSON。Agent 自动发现 compose 栈 5 个容器，稳定 `service_key` 为 `compose:vps-agent-console:<service>:1`；`agent_evidence_sources` 与 `agent_evidence_source_bindings` 均无 target 列，控制平面只能引用 Agent 已声明的 source_key 并下发时间、行数、字节数和超时上限。浏览器在机器详情页确认 `m3-auto-canary` 候选即建立映射，无需手填 source_key、容器 ID 或 JSON，也不手敲映射 API。停止 canary 进入 Firing 后触发诊断进入 Completed，证据请求经 Caddy 无 401，docker_logs 证据中 `fake-secret` 计数为 0、`[REDACTED]` 为 97。同名重建 canary（新容器 ID）后 `service_key` 与映射不变，第二次诊断仍 Completed，稳定身份跨重建存活。控制平面每上报周期 reconcile `agent_evidence_sources` 与 `service_statuses`，Agent 停止声明的来源与状态自动清除；清理后 control-plane 回到纯自动发现，DB 孤儿清理完毕。

同日使用隔离 PostgreSQL 验证 Agent 可用性事件：并发执行两次失联巡检只生成一个活动事件和一条 Firing sequence 1；从该机器事件手动触发诊断，不创建远程证据请求，直接以告警和最后心跳等控制平面证据进入 Completed；随后通过真实 Agent 报告处理路径恢复同一事件，生成 Resolved sequence 2。临时 PostgreSQL 容器和匿名数据卷已清理。

2026-07-19 Agent 失联/恢复事件生产金丝雀在 DMIT 跑通（目标机无 docker，停 systemd `vps-agent` 即可）：控制平面维护循环主动巡检 `last_seen_at`，DMIT 停 Agent 超 90 秒后生成 `source=agent` 的机器级 Firing（钉钉“🔴 VPS 失联”，`NotificationDelivery` sequence=1/sent）；从该事件手动触发机器级诊断直接进入 Completed（deterministic），只保存控制平面的告警事件、Agent 连接状态、最后资源快照和最后服务快照 4 项证据且全部脱敏、不含 credential，`evidence_requests` 为 0（不向离线 Agent 发取证请求）；DMIT 恢复上报后同一事件经报告处理路径转 Resolved（钉钉“✅ VPS 已恢复连接”，sequence=2/sent），失联期间多次巡检只投递一次 Firing。多 API 实例 `SKIP LOCKED` 去重单实例生产未直接触发，由代码与隔离并发验证覆盖。

同日完成 GitHub App 最小只读与 systemd journal 的隔离闭环：官方 Caddy 镜像校验配置为 `Valid configuration`；真实 PostgreSQL 创建 20 张当前模型表；使用模拟 GitHub REST 传输验证短期安装令牌、授权仓库、默认分支 Commit 和精确白名单 README 快照同步，测试 secret 在持久化前被脱敏；真实 API 数据流接收 Agent 声明的 systemd journal 能力，两次失败状态形成 Firing，Web 候选模型建立 systemd 映射，Agent Claim/Complete 有限 journal 后诊断进入 Completed。最终证据包含 `alert_event`、`deployment_version`、`metrics`、`repository_file`、`service_status` 和 `systemd_journal`，测试 secret 未进入任何证据，Agent 来源/绑定及 GitHub 绑定表均无采集 target 列。该验证没有连接真实 GitHub 安装，也没有部署生产。

## 9. 当前未包含与已知限制

- 文件日志与任意路径读取。
- GitHub App 首版只支持一个安装 ID、至多 1000 个授权仓库和精确路径快照；同步采用 1–8 路受限并发，但仍在 API 后台任务或管理员请求内执行，尚无独立持久任务队列、全仓库检索和增量知识索引。
- GitHub App 与 systemd journal 尚未在真实 GitHub 安装和外部 VPS 上完成生产金丝雀；当前仅有单元测试与隔离 PostgreSQL 闭环。
- 自动诊断调度和通用独立任务队列；当前控制平面维护循环只负责 Agent 可用性巡检与通知重试。
- 全局聊天、页面上下文对话、向量数据库和诊断历史增强。
- 任何 M4 写操作。
- 证据领取仍在 Agent 的报告循环中串行执行：单次采集最多阻塞该循环 15 秒，每周期只处理一个证据请求。当前默认 30 秒报告间隔可接受；请求密度增加前应拆成独立、有并发上限的轮询循环。
