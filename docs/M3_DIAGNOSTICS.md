# M3 只读诊断协议与配置

本文记录 M3 首条纵向闭环的当前实现。它只覆盖已登记 Docker 服务的有限日志取证、控制平面上下文和结构化诊断，不提供 Shell、服务重启、部署、回滚或任意路径读取。

## 1. 身份与数据模型

- `ServiceStatus` 仍是 Agent 最近一次上报的瞬时观测，不承担业务服务身份。
- `ManagedService` 表示业务服务，`ServiceInstance` 使用 `(agent_id, service_kind, service_key)` 绑定一个实际运行实例。
- `InstanceLogSource` 只保存稳定的 `source_key`、类型和展示名；Docker 容器目标只存在于 Agent 本地配置。
- `Repository` 与 `DeploymentVersion` 保存仓库名、Commit SHA 或镜像摘要。GitHub 凭据不下发给 Agent。
- `DiagnosticRun`、`EvidenceRequest`、`EvidenceItem` 与 `DiagnosticCitation` 分别保存诊断状态、出站请求、脱敏后的原始观察证据和结论引用关系。AI 结论不写回证据内容。

## 2. Agent 本地白名单（首条闭环兼容方式）

第一版只接受 `docker_logs`，并通过 `/etc/vps-agent/agent.env` 显式配置。该方式用于验证“控制平面不能任意指定容器或路径”的安全边界，不是多台 VPS 的最终部署流程。例如：

```dotenv
AGENT_EVIDENCE_SOURCES_JSON='[{"key":"payment-api-logs","kind":"docker_logs","target":"payment-api","display_name":"payment-api-logs"}]'
```

`key` 是控制平面可引用的稳定标识；`target` 是本机 Docker 容器名或 ID，不会随报告上传。非法 JSON、重复键、未知类型、空目标或不符合 `[a-zA-Z0-9._-]+` 的键会被忽略。升级安装器会保留这项配置。

不要把这套手工配置推广为日常运维要求。产品化替代方案属于 M3 当前后续范围：

- Agent 根据已发现的 Docker Compose project/service 标签、普通容器和 systemd Unit 生成本地能力目录及稳定来源键。
- Docker 服务长期身份优先使用 Compose project/service 等稳定元数据，不依赖容器重建后会变化的容器 ID。
- 控制台展示候选服务和证据能力，用户通过 Web 批量确认或使用安装前选择的策略自动接受，不需要登录 VPS 编辑 JSON。
- 控制平面仍只能请求 Agent 已声明的来源键，并继续下发和校验时间、行数、字节数和超时上限；自动发现不等于允许任意日志、路径或命令。
- 现有环境变量在迁移期保留，用于兼容已部署 Agent、特殊服务和故障排查。

## 3. 只读出站协议

1. Agent 在常规报告中只声明证据源的 `key`、`kind` 和展示名。
2. 当前管理员通过 `POST /api/v1/service-mappings` 把已观测服务、Agent 已声明的日志源和可选仓库版本绑定为服务实例；产品化后由 Web 发现/确认流程调用同类控制面能力，不要求用户手写请求。
3. `POST /api/v1/events/{event_id}/diagnostics` 手动触发诊断。同一事件同时只允许一个 Pending/Running 诊断。
4. 控制平面先保存告警、最新服务状态、最新资源快照和部署版本证据，再创建只包含 `source_key`、时间窗口、行数、字节数和超时的请求。
5. Agent 通过 `GET /api/v1/agents/evidence-requests/next` 主动领取请求，在本地用 `source_key` 查找目标；未命中本地白名单时直接失败，不接受控制平面提供容器名或命令。
6. Agent 使用固定参数调用 `docker logs`，并在容器目标前加入 `--` 参数分隔符，没有 Shell 拼接；结果在上传前脱敏并按上限截断，再通过 `POST /api/v1/agents/evidence-requests/{id}/complete` 回传。
7. 控制平面再次执行行数、字节数和敏感信息限制，然后调用诊断提供者并验证固定结构及全部证据引用。

首个映射请求示例（`X-Admin-Token` 只由受信任管理端持有）：

```json
{
  "name": "payment-api",
  "environment": "production",
  "agent_id": "已注册 Agent ID",
  "service_kind": "docker",
  "service_key": "Agent 上报的容器 ID",
  "deployment_directory": "/opt/apps/payment-api",
  "log_source_key": "payment-api-logs",
  "repository_full_name": "example/payment-api",
  "default_branch": "main",
  "commit_sha": "0123456789abcdef0123456789abcdef01234567",
  "image_digest": "sha256:example"
}
```

默认硬上限为最近 15 分钟、200 行、64 KiB、10 秒；代码级最大值为 500 行、64 KiB、15 秒。Agent 与控制平面都会执行限制。

## 4. 诊断提供者

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

## 5. 脱敏与不可信输入

Agent 和控制平面均遮蔽 Authorization、Bearer Token、密码、Cookie、Webhook、常见 Token/Secret/API Key 字段和私钥块。数据库保存的是脱敏后但尚未被 AI 改写的观察证据；诊断结论和引用关系存放在独立表中。

日志、仓库内容、服务输出和模型响应全部是不可信输入。它们只能作为证据或文本结果，不能改变可用工具、白名单、审批规则或执行权限。

## 6. Caddy 与请求边界

生产 Caddy 将注册、报告和 `/api/v1/agents/evidence-requests/*` 统一归入 Agent Bearer API，不要求控制台 Basic Auth；FastAPI 仍使用 `current_agent` 校验独立 Agent 凭证。该路由的请求体上限为 1 MiB，合法证据完成请求仍受 Pydantic 的 128 KiB 字符上限和证据自身 64 KiB 字节上限约束。

## 7. 验证记录

2026-07-17 使用隔离 Compose 项目启动真实 Caddy、FastAPI、PostgreSQL、Redis 和 Web，并启动挂载只读采集所需 Docker Socket 的测试 Agent：

- 官方 `caddy:2-alpine` 执行 `caddy validate --config /etc/caddy/Caddyfile`，结果为 `Valid configuration`。
- 向 Agent 完成端点发送超过 1 MiB 的测试请求体，Caddy 在进入 FastAPI 前返回 413。
- Agent 仅通过 Caddy 服务名完成一次性令牌注册和连续报告，没有提供 Basic Auth 凭据。
- 停止的金丝雀容器形成真实 M2 Firing 事件；创建 `docker_logs` 白名单映射后从事件手动触发诊断。
- Agent 经 Caddy 成功 Claim 和 Complete 证据请求，日志记录 `evidence request completed`，没有出现 401。
- 确定性提供者把诊断推进到 Completed，共保存 5 项事件、状态、指标、版本和 Docker 日志证据；测试敏感值未进入持久化证据。

测试使用独立项目名、临时测试凭据和独立数据卷；结束后清理，不涉及生产环境。

## 8. 当前未包含与已知限制

- 自动生成稳定证据源目录和 Web 服务发现/确认流程；因此当前手工白名单只能用于少量金丝雀验证，不适合逐台推广。
- systemd journal 和文件日志。
- GitHub App 安装、Webhook 和仓库文件同步。
- 自动诊断调度、Agent 失联/恢复事件和独立任务队列。
- 全局聊天、页面上下文对话、向量数据库和诊断历史增强。
- 任何 M4 写操作。
- 证据领取仍在 Agent 的报告循环中串行执行：单次采集最多阻塞该循环 15 秒，每周期只处理一个证据请求。当前默认 30 秒报告间隔可接受；请求密度增加前应拆成独立、有并发上限的轮询循环。
