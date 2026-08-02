# 项目状态

最后同步：2026-08-02
当前阶段：**M0–M6 已完成；v0.6.1 正式发行 + digest-pinned 生产升级金丝雀通过 2026-08-01；M6 于 2026-08-02 完成收口**

## 1. 当前结论

项目已完成工程骨架、“机器可见”和“异常可通知”里程碑。生产控制平面通过 Caddy/HTTPS 运行，Agent 使用一次性令牌注册、独立凭证认证和主动出站 HTTPS 上报；服务异常、去重、钉钉通知和恢复通知已经过生产杀手路径验证。

M1 的“至少 3 台真实或测试 VPS 稳定接入”验收线已经满足。本文早期 Fleet 数量、版本和 capability 仅为对应日期的历史快照：旧 aliyun-VPS 已被释放，2026-07-31 M6.4c 金丝雀改用新 aliyun-零时 Agent `v0.4.2`，具名 M4 全链完成后已还原服务 restart 授权。当前机器、Agent 版本和 capability 必须在每次生产操作前从实时 API/Agent 上报核对，不能从本文推断。

## 2. M0：项目骨架

状态：**已完成**

### 已交付

- `apps/web`、`apps/api`、`apps/agent` Monorepo。
- Next.js + TypeScript Web、FastAPI 控制平面和 Go Agent。
- PostgreSQL、Redis 和 Docker Compose 开发环境。
- 环境配置、结构化日志、测试、Makefile 和根目录开发命令。
- Web、API、Agent 多阶段 Docker 镜像。
- 中文架构、路线图、状态和命令文档。

### 验证结果

- FastAPI pytest、Ruff 检查通过。
- Web Vitest、ESLint 和 Next.js 生产构建通过。
- Go `go test ./...` 通过。
- Web、API、Agent Docker 镜像构建通过。
- PostgreSQL、Redis 健康检查和数据卷验证通过。

M0 完成时存在的“无正式 Agent 身份、无资源持久化、无真实 VPS 页面”等限制，已在 M1 中解决。

## 3. M1：机器可见

状态：**已完成**

### 已实现

- PostgreSQL Agent、注册令牌、资源快照和服务状态模型。
- SQLAlchemy 异步数据层与 Alembic M1 基线迁移。
- 受管理令牌保护的一次性注册令牌签发接口。
- Agent 独立凭证签发、Bearer 认证和凭证摘要保存。
- Agent 身份文件以 `0600` 权限持久化，升级和重启复用同一身份。
- 安装器生成独立持久的 Agent machine-id，不修改 Linux `/etc/machine-id`。
- Linux 主机名、系统、架构、CPU、内存和磁盘采集。
- Docker 容器、systemd 服务和配置化 HTTP 健康检查采集。
- 资源快照持久化、服务当前状态更新和在线/离线计算。
- Fleet 首页真实 VPS 总览和 VPS 详情页。
- 详情页服务概览、异常优先、按类型折叠和 ACTIVE/SUB 状态语义。
- Fleet 首页生成一次性令牌和安装命令。
- GitHub Release 自动测试、Linux amd64/arm64 构建、SHA-256 校验和安装器发布。
- `/agent-downloads/` 同域 Release 中转，支持 GitHub CDN 不稳定的网络。

### 已验证

- 首次注册返回 201，后续认证报告返回 200。
- 重启 Agent 后继续使用原身份，不创建重复机器。
- 已消费、无效或过期注册令牌不能再次注册。
- 无效 Bearer 凭证不能提交报告。
- Agent 停止超过阈值后显示离线，恢复服务后重新在线。
- CPU、内存、磁盘、Docker、systemd 和 HTTP 检查可在详情页查看。
- systemd `active`、`inactive`、`failed` 及正常 `exited` 服务不会混淆。
- Caddy 提供 HTTPS 和控制台 Basic Auth，Agent 注册/上报路径无需 Basic Auth。
- `v0.2.2`、`v0.2.3`、`v0.2.4` Release 产物和双架构校验和已验证。
- 3 台外部真实 VPS 已通过 Release 安装器接入，其中包含使用控制平面下载中转的国内 VPS。
- 国内 VPS 的克隆 machine-id 冲突已通过独立 Agent machine-id 解决。
- 控制平面宿主机完成 systemd 托管、在线/离线验证及保留身份升级。

### 实机结果

| 机器 | 当前角色 | M1 结果 |
| --- | --- | --- |
| DMIT VPS | 外部被管主机 | M1 验收通过，基线 Agent `v0.2.4` |
| 腾讯云硅谷 VPS | 外部被管主机 | M1 验收通过，基线 Agent `v0.2.4` |
| Tencent-VPS-Hermes | 国内外部被管主机 | M1 验收通过，已验证同域中转安装 |
| control-plane | 控制平面宿主机自监控 | M1 验收通过，已验证保留身份升级 |

### 质量收尾

状态：**已完成首轮加固**

- Go 客户端已覆盖注册、Bearer 上报、非成功响应、非法响应和请求取消。
- 采集器已覆盖 Docker/systemd 解析、HTTP 成功/失败/重定向、非法 URL 和取消场景。
- Agent 配置已覆盖默认值、采集周期、健康检查列表和非法周期回退。
- Agent 身份文件会拒绝缺少 Agent ID 或凭证的合法但不完整 JSON，并已覆盖保存/加载测试。
- API 已覆盖管理/Agent 认证失败、过期或已消费注册令牌、资源边界和重复服务上报。
- API 测试环境初始化已集中处理，不再因测试收集顺序意外连接开发数据库。
- Web 占位测试已替换为 Fleet 汇总、API 错误、字节格式化和安装命令行为测试。
- 安装入口固定使用令牌生成时的机器名称，明确分离安装命令与一次性令牌，并对控制平面不可用返回受控错误。

本轮回归结果：Web 16 项测试、API 16 项测试和全部 Go 包测试通过；Web ESLint、生产构建、Ruff 和 `go vet` 通过。更深的真实 PostgreSQL 集成、安装器沙箱和长时间稳定性测试继续作为常规工程质量工作，不阻塞进入 M2。

## 4. M2：异常可通知

状态：**已完成**

首个通知通道由原计划中的 Telegram 调整为钉钉自定义机器人；Telegram 保留为后续通知适配器。已完成以下控制平面能力：

- 服务异常事件模型、活动事件指纹和通知投递记录。
- 默认连续两次异常观测后从 Pending 进入 Firing。
- 同一机器、服务类型和服务键的活动异常去重。
- 明确健康观测后进入 Resolved；服务从报告中消失不被误判为恢复。
- Firing 和 Resolved 分别生成一次钉钉异常/恢复通知投递。
- 钉钉自定义机器人 Webhook、可选加签、Markdown 转义和错误响应处理。
- 事件列表 API，以及受管理令牌保护的 Acknowledged/Silenced 操作。
- 通知发送与 Agent 报告响应解耦，失败投递最多重试三次。

### 已修复的审查问题

- Silenced 事件会在 `silenced_until` 到期且服务仍异常时重新进入 Firing，并且只生成一次新的异常通知；服务恢复时会清除静默截止时间。
- 通知投递使用事件内递增序号区分状态转换，允许静默过期后再次发送 Firing，同时保持每次转换的投递唯一性。
- 通知投递增加 `updated_at`；进程在 HTTP 发送期间退出后，超过默认 120 秒的陈旧 Sending 会被重新领取，不会永久丢失。
- 新鲜的 Sending 仍被视为正在发送，不会被其他上报重复领取。
- HTTP 客户端请求日志已降到 Warning，避免钉钉 Webhook 的访问令牌和签名参数出现在应用日志中。

### 本地集成验证

2026-07-15 已使用本地 Docker Compose 和保留 M1 数据的真实 PostgreSQL 卷完成预演：

- 新 API 在已有 M1 数据库上启动成功，M2 两张表和最终列、外键、唯一约束均正确创建，M1 Agent、指标和服务数据未受影响。
- 本地 Agent 以 3 秒测试间隔持续上报，API 始终返回 200；同一异常连续上报只形成一个活动事件和一次初始 Firing 投递。
- 服务恢复后事件进入 Resolved，且只生成一次恢复投递。
- Acknowledged、Silenced、静默到期再次 Firing 和再次恢复均通过真实 API 与 PostgreSQL 验证，通知序号按状态转换递增。
- 陈旧 Sending 能被重新领取并增加尝试次数；新鲜 Sending 不会被重复领取。
- 测试结束后已清理 M2 事件/投递测试数据、恢复 Agent 默认 30 秒间隔并停止本地容器；M1 数据卷保留。

随后使用启用加签的专用钉钉测试机器人完成真实链路验收：连续异常只发送一次 Firing，服务恢复只发送一次 Resolved，两条投递均由钉钉接口成功接收。

### 生产验收

2026-07-16 已在生产控制平面完成 M2 部署与杀手路径验收：

- 仅重建并重启 `api` 容器（web/caddy/postgres/redis 未动），`create_all` 在启动时自动建出 `alert_events` 与 `notification_deliveries` 两张表，列、外键与 `(event_id, sequence, channel)` 唯一约束均为最终结构。
- 4 台 Agent（3 台外部 VPS 与控制平面宿主机自监控）在 api 重启后持续上报 200，`last_seen_at` 保持秒级刷新，未出现掉线或 500。
- 在控制平面宿主机用金丝雀容器演练：停止后连续两次异常观测进入 Firing 并发出一张钉钉异常卡；持续停止期间 `observation_count` 累计至 11 仍只投递一次（去重生效）；恢复后进入 Resolved 并发出一张恢复卡。
- 两条投递（Firing `sequence=1`、Resolved `sequence=2`）均 `status=sent`、`attempt_count=1`，生产钉钉群收到对应异常与恢复卡片。
- httpx 客户端日志已降至 Warning，钉钉 Webhook 的访问令牌与签名未出现在应用日志中。

### 已知限制

- 通知失败重试目前没有指数退避，最多尝试三次，并且仍由后续 Agent 上报触发；独立调度器属于 M2 后续工作。
- `deliver_notification` 领取投递后先提交 Sending 状态，再发送 HTTP，发送完成后继续修改同一 ORM 对象；该流程明确依赖 `session_factory` 的 `expire_on_commit=False` 配置。
- Docker 上报目前没有结构化退出码或容器运行模式。Agent 会将所有 `exited` 容器标记为 `healthy=false`，因此一次性或 cron 容器正常退出 0 仍可能产生误报；在 Agent 协议增加退出码/期望状态前，不在 API 层解析非结构化详情字符串。
- `active_key` 唯一约束能够阻止重复活动事件，但并发创建同一事件时的 `IntegrityError` 尚未在报告事务内恢复。当前 Go Agent 串行上报，实际风险较低；后续应使用保存点或按 Agent 串行化评估，避免回滚整份报告。

以下工作不纳入 M2 完成门槛，已转入后续里程碑或跨里程碑质量工作：

- Agent 失联检测、恢复事件和事件诊断工作空间转入 M3。
- 安全的服务端操作代理、审批与验证转入 M4。
- Agent 对话和增强仓库知识体验转入 M5。
- 将失败通知重试从后续 Agent 报告触发扩展为独立调度（已随 M3 Agent 可用性巡检实现）。
- 为 Docker 服务上报增加退出码和期望运行模式，降低正常一次性容器的误报。
- 验证并发报告下的活动事件冲突处理。

## 5. M3：上下文与 AI 诊断

状态：**已完成**（2026-07-26）

M3 将原路线中的“服务可关联”和“问题可诊断”核心闭环前置整合：先建立服务、部署目录、有限日志来源、GitHub 仓库与部署版本映射，再收集有边界、可脱敏、可引用的故障证据，最终由 AI 输出明确区分的事实、推断和建议。M3 保持只读，不包含任意 Shell 或自动修复；安全重启和其他写操作仍由 M4 的 Runbook、审批、验证与审计承载。

### 首批实现（2026-07-17）

- 新增业务服务、服务实例、Agent 证据源目录、仓库、部署版本、诊断任务、证据请求、证据项和引用关系模型，以及兼容 M1/M2 数据的 `0003_m3_diagnostics` 增量迁移。
- `ServiceStatus` 继续只表示最新观测；服务实例用 `(agent_id, service_kind, service_key)` 与观测关联，避免用容器状态记录承担稳定业务身份。
- Agent 支持本地 `docker_logs` 白名单，只上报稳定来源键，不上报本地容器目标；控制平面通过 Agent 主动出站轮询下发来源键和时间、行数、字节数、超时上限。
- Docker 日志使用固定参数调用，没有 Shell 拼接；Agent 上传前脱敏并截断，控制平面存储前再次限制和脱敏。
- 诊断提供者已抽象为确定性测试实现和受信任 HTTP JSON 模型网关；固定校验事实、推断、建议、缺失证据和证据引用，非法响应进入受控 Failed 状态。
- 新增服务映射、手动诊断触发、Agent 证据领取/回传和诊断查询 API；Web 总览增加最近事件，事件页可触发并查看最小诊断工作区。
- 钉钉事件链接改为事件诊断页；安装器会保留 Agent 证据源白名单配置。
- Caddy 已放行 Bearer 鉴权的证据领取/完成端点并限制 Agent API 请求体为 1 MiB；陈旧 Running 诊断和长期未完成证据请求具备回收与重新调度路径。

M3 阶段检查点曾通过 API 81 项测试、Web 22 项测试、全部 Go 包测试、Ruff、ESLint、`go vet` 和 Web 生产构建；当时 Alembic head 为 `0005_m3_github_readonly`。当前开发树的合并验证记录见 M4 章节，不能用该历史检查点把 M3 标记为完成。

2026-07-26 完成 M3 最小收尾：诊断 Provider 已增加启动校验、总上下文预算与固定优先级、严格 schema、未知引用校验和受控失败码，并新增真实 PostgreSQL 仓库证据到 `DiagnosticCitation` 的门控测试；API 常规回归 206 项通过、9 项数据库门跳过，Web 67 项、Ruff、Python compile、ESLint、production build、Go 全包与 vet、开发 Compose 配置通过。新增门控已在临时 PostgreSQL 16 上单独通过，验证真实 `repository_file` 进入诊断、敏感内容脱敏、`DiagnosticCitation` 落库及 Operation 数量不变，应用 schema check 一致。两项生产金丝雀随后通过：真实仓库文件形成诊断引用，M3 `http_json` Provider 超时按 `provider_timeout` 受控失败且零 Operation 副作用；生产已恢复 deterministic，M3 标记为完成。详细证据见 [M3_CLOSEOUT.md](./M3_CLOSEOUT.md)。

2026-07-17 已使用独立本地 Compose 项目完成真实 Caddy、PostgreSQL、API 和 Agent 端到端验收：Agent 只经 Caddy 注册、报告、领取和完成 Docker 日志证据，没有收到 Basic Auth 401；真实 Firing 事件的诊断最终进入 Completed 并保存 5 项证据，测试敏感值未进入持久化内容。测试栈使用临时值和独立数据卷，不涉及生产部署。

2026-07-19 已完成生产金丝雀全闭环：停止 canary 后形成 Firing 和钉钉异常卡；Agent 经 Caddy 完成取证且无 401；双端脱敏后 `fake-secret` 持久化计数为 0、`[REDACTED]` 为 100；诊断进入 Completed 并生成 4 条带证据引用的事实；重启 canary 后进入 Resolved 并收到钉钉恢复卡。本批安全边界全部获得生产实证，M3 因产品化和剩余范围曾保持进行中；2026-07-26 两项收尾生产门通过后标记为完成。

### 产品化首批实现（2026-07-19）

- Agent Docker 身份不再依赖容器 ID：Compose 使用 project/service/副本号，普通容器使用容器名；超长值使用确定性摘要。
- 新增本地 `AGENT_EVIDENCE_POLICY`，只有安装时明确选择 `docker_logs` 才自动为已发现容器生成有限日志能力，旧 Agent 升级默认关闭。
- Agent 上报来源与稳定服务键关联但不上传真实容器目标；控制平面新增独立关联表和兼容增量迁移。
- 控制平面在身份首次切换时迁移活动 M2 事件和既有 M3 映射，保持告警、恢复通知和诊断链路连续。
- 机器详情页可查看 Agent 已授权的 Docker 诊断候选项，并通过服务端管理令牌代理确认映射；浏览器不持有管理令牌。
- 手工 `AGENT_EVIDENCE_SOURCES_JSON` 和原 `service-mappings` API 继续兼容，不影响已验证的金丝雀路径。

隔离集成验证使用真实 PostgreSQL、API、Agent 和 Docker Compose：自动发现生成 8 个稳定 Docker 身份及日志来源，Web 所需候选 API 完成映射且不暴露目标；容器重启后稳定键和映射保持不变；旧容器 ID 下的真实 Firing 与服务映射切换到稳定键后，事件正确 Resolved 且映射继续有效。临时项目、凭据和数据卷已清理。

2026-07-19 v0.3.1 产品化金丝雀（自动发现模式）在生产 control-plane 宿主机跑通全闭环：控制平面升级到 `7ce516e`；control-plane Agent 保留身份升级到 `v0.3.1` 并以 `--evidence-policy docker-logs` 开启自动发现。Agent 自动发现 compose 栈 5 个容器，稳定 `service_key` 为 `compose:vps-agent-console:<service>:1`，`agent_evidence_sources` 与 `agent_evidence_source_bindings` 均无 target 列。浏览器在机器详情页确认 `m3-auto-canary` 候选即建立映射，无需手填 source_key、容器 ID 或 JSON，也不手敲映射 API。停止 canary 进入 Firing 后触发诊断进入 Completed，证据请求经 Caddy 无 401，docker_logs 证据中 `fake-secret` 计数为 0、`[REDACTED]` 为 97，双端脱敏生效。同名重建 canary（新容器 ID）后 `service_key` 与映射不变，第二次诊断仍 Completed，稳定身份跨重建存活。清理后 control-plane 回到纯自动发现（手工白名单置空），DB 孤儿映射与事件已清，4 台 Agent 持续在线；控制平面每上报周期 reconcile `agent_evidence_sources` 与 `service_statuses`，Agent 停止声明的来源与状态自动清除。M3 因剩余生产验收与真实模型验证曾保持进行中；2026-07-26 两项收尾生产门通过后标记为完成。

### Agent 失联与恢复首批实现（2026-07-19）

- API 生命周期内新增控制平面维护循环，默认每 30 秒检查一次 `last_seen_at`；超过 90 秒未上报时创建机器级 Firing，Agent 下一次合法报告在刷新心跳前将同一事件转为 Resolved。API 启动先等待一个完整失联阈值，避免把控制平面自身停机误报成整批 VPS 失联。
- 机器事件复用 M2 `AlertEvent`、活动指纹、确认/静默、`NotificationDelivery` 和钉钉序号；失联和恢复分别为 sequence 1/2，重复巡检不重复通知。
- 巡检使用 Agent 行锁和 `SKIP LOCKED`，恢复报告也先锁定同一 Agent，避免多 API 实例或巡检/恢复竞争生成重复活动事件。
- 独立维护循环会同时扫描待发送、失败和陈旧 Sending 通知，因此机器全部失联时仍能产生告警，并补齐原先依赖后续 Agent 报告触发通知重试的可靠性缺口。
- Agent 事件可从现有事件页手动发起诊断，不要求服务映射，也不向离线 Agent 发请求；证据只包含控制平面已保存的告警、最后心跳、Agent 元数据、最后资源快照和最多 128 条服务状态。
- 新增 `AGENT_AVAILABILITY_SCAN_INTERVAL_SECONDS`，必须不大于 `AGENT_OFFLINE_AFTER_SECONDS`；不新增数据库表或迁移，兼容现有 M1/M2/M3 数据。

隔离 PostgreSQL 事务验证并发执行两次失联巡检，仅生成 1 个活动事件和 1 条 Firing 投递；机器级诊断直接进入 Completed 并保存控制平面证据；随后通过真实报告路径恢复为同一事件的 Resolved，投递序列严格为 Firing 1、Resolved 2。临时容器和数据卷已清理。

2026-07-19 Agent 失联/恢复事件生产金丝雀在 DMIT 跑通（目标机无 docker，停 systemd `vps-agent` 即可）：控制平面升级到 `a78f780` 后维护循环主动巡检 `last_seen_at`，DMIT 停 Agent 超 90 秒即生成 `source=agent` 的机器级 Firing（钉钉“🔴 VPS 失联”，投递 sequence=1/sent）；机器诊断直接 Completed（deterministic），只保存控制平面的告警/连接状态/最后指标/最后服务快照 4 项证据且全部脱敏、不含 credential，`evidence_requests` 为 0；DMIT 恢复上报后同一事件转 Resolved（钉钉“✅ VPS 已恢复连接”，sequence=2/sent），失联期间 13 次巡检只投递一次 Firing。多 API 实例去重（SKIP LOCKED）单实例生产未直接触发，由代码与隔离并发验证覆盖。

### GitHub App 只读与 systemd journal 首批实现（2026-07-19）

- 控制平面新增 GitHub App 短期 JWT/安装令牌认证、授权仓库同步、默认分支 Commit、精确白名单文件快照、HMAC-SHA256 Webhook 验签与投递去重。App 私钥和安装令牌不进入 Agent、浏览器或数据库；Webhook 不保存原始载荷。
- GitHub App 可靠性加固包括：撤权时同步删除仓库文件快照；仓库读取默认 4 路、最大 8 路受限并发；缓存单进程已解析私钥；Webhook 通过 Redis 实现跨 API 实例每分钟固定窗口限流，Redis 故障时保留请求体边界和验签。
- GitHub App 配置启用后，Web 首页显示授权状态、仓库同步与当前 HEAD，服务映射只能选择当前安装授权仓库。诊断将脱敏后的白名单文件作为带 Commit 引用的 `repository_file` 不可信证据，并与实际部署版本保持语义分离。
- Agent 新增显式 `systemd_journal` 策略和 `evidence.systemd_journal.v1` 能力；自动发现 Unit 后生成稳定来源键，本地 Unit 目标不上传。采集只调用固定 `journalctl` 参数，不经过 Shell，并复用时间、行数、字节数、超时和双端脱敏限制。
- 安装器与 Web 接入页支持 `disabled`、Docker、systemd 及 Docker+systemd 四档策略。旧配置继续保持原值，未知组合整体关闭，不静默扩大读取权限。
- 新增兼容迁移 `0005_m3_github_readonly`，只创建 GitHub 授权、文件快照和 Webhook 审计三张表，不修改现有 M1/M2/M3 表。

隔离闭环使用真实 PostgreSQL 和模拟 GitHub REST 传输：同步 1 个授权仓库与 1 个白名单 README 快照，测试 secret 在持久化前被脱敏；systemd 服务连续异常形成 Firing，候选映射、Claim/Complete journal 和确定性诊断完整走通，最终进入 Completed，证据包含事件、版本、指标、仓库文件、服务状态和 systemd journal。数据库共创建 20 张当前模型表，所有来源/绑定表均无采集 target 列。官方 Caddy 镜像验证配置为 `Valid configuration`。本轮没有连接真实 GitHub 安装、外部 VPS 或生产环境。

2026-07-20 GitHub App 最小只读生产金丝雀在控制平面宿主机跑通（真实 App `vps-agent-canary` 装到 `ymasout/MagicPDF`）：手动同步拉取授权仓库 Commit SHA + 白名单 README 脱敏快照；push 触发真实 GitHub 签名 Webhook，HMAC 验签通过并重同步新 head_sha；卸载触发 `installation` action=`deleted`，binding 置 `enabled=False` 且仓库文件快照删除、`/repositories` 清空。无令牌/原始载荷/target 落库。部署坑：Caddyfile 变动后需 `--force-recreate caddy`（单文件 bind mount 旧 inode 问题，`caddy reload` 无效）。

2026-07-20 systemd journal 生产金丝雀在 DMIT（无 docker）跑通：Agent 升级 `v0.3.3` + `--evidence-policy systemd-journal`，自动发现 101 个 systemd Unit；Web 确认 `m3-journal-canary.service` 映射；kill 进 failed -> Firing -> 诊断，journalctl 取证成功（6113 字节，`fake-journal-secret` 计数 0、`[REDACTED]` 36，双端脱敏）；恢复 -> Resolved。首次因旧版 journalctl 不认 RFC3339 `T...Z` 失败，v0.3.3 改用 `YYYY-MM-DD HH:MM:SS UTC` 成功（兼容旧版及更广范围的 systemd）。

### 当前产品化缺口与下一批顺序

- 当前 Web 流程支持逐个确认 Docker/systemd 服务；批量确认和自动推断部署目录仍未实现。现有手工配置暂时保留为兼容与故障排查入口。
- 新稳定身份和 Web 映射流程已在 control-plane 生产金丝雀实证：容器重建后稳定键与映射不断。尚未直接实证两项：旧 Agent 不带 `AGENT_EVIDENCE_POLICY` 升级仍保持 `disabled`（安装器默认值保证，DMIT/腾讯未实机升级）；容器 ID->稳定键的 M2 事件/M3 映射迁移（金丝雀用新容器名、旧孤儿容器已删无迁移目标，仅隔离验证覆盖）。向更多 VPS 推广前应补这两项实机验证。
- 自动发现不能取消权限边界：控制平面仍只能引用 Agent 已声明的受限能力，文件路径、日志窗口、字节数、持续时间和超时继续由 Agent 与控制平面双重校验。
- Agent 失联/恢复、GitHub App 只读同步和 systemd journal 生产金丝雀均已通过（2026-07-20，见上）。剩余未做：真实 AI 模型网关（`http_json` 提供者）生产验收、文件日志、自动诊断调度、完整仓库同步和诊断体验增强。向更多 VPS 推广前还应补两项实机验证：旧 Agent 不带 `AGENT_EVIDENCE_POLICY` 升级仍 `disabled`、容器 ID->稳定键迁移（见上条）。

### 已确认的终局产品方向（2026-07-19）

- 每台 VPS 通过一条安装命令完成 Agent 安装、注册和能力策略绑定；用户不需要逐台编辑证据源 JSON。
- Agent 自动发现服务和运行现场，控制台负责确认业务语义、仓库、部署方式和权限档位。
- 自然语言是最终主要操作入口，但不直接变成自由 Shell：系统生成结构化计划，按风险自动执行或请求确认，再进行验证和审计。
- 重启、拉取、部署、回滚等写操作由 M4 的签名任务、能力策略和 Runbook 承载；M5 把这些能力接入全局和上下文对话。
- 高风险通用命令仅作为后期、限时、限定机器且可审计的人工兜底能力；不存在授予模型永久无限 Root 权限的模式。
- 密钥隔离由工具和权限层强制执行。GitHub 写操作留在控制平面，通过明确授权的 GitHub App 创建分支、提交或 PR，VPS Agent 不保存长期仓库写凭据。

## 6. M4：安全处置

状态：**已完成（核心：重启+部署+回滚）**

M4 已正式开始，但没有把 M3 标记为完成。第一轮范围严格限定为“显式授权的非关键 Docker 单服务安全重启”：

- 新增 Agent 服务级写能力目录；旧 Agent、本地策略未启用、缺少验签公钥或未声明具体 stable service_key 时默认拒绝。
- 现有服务增量迁移后默认关键且禁止重启；Web 只有在 Agent 已声明能力时，才允许把具体映射标记为非关键并显式开启安全重启。
- 新增 planned、prechecking、awaiting_confirmation、queued、claimed、running、verifying、succeeded、failed、canceled、expired 状态及完整转换审计。
- 使用独立 Ed25519 任务签名，不把 Agent Bearer 鉴权直接当作任务签名；任务固定绑定 operation、Agent、动作枚举、stable service identity、有效期、幂等键、attempt、nonce 和 key ID。
- Agent 使用独立轮询，不阻塞正常资源报告或 M3 证据采集；本地重新枚举 Docker 并要求 stable service_key 恰好匹配一个当前 target。
- Docker 只通过固定 `docker restart -- <本地 target>` 执行，不经过 Shell，不接收命令、argv、容器 target、Unit 或路径。
- Agent 本地 `0600` 有界账本在执行前和结果上传前持久化，网络重试不会重复重启；Running 结果不确定时受控失败而非自动重放。
- Docker 命令退出 0 只进入 Verifying；只有后续新鲜观测满足 running、healthy 和稳定窗口才进入 Succeeded。Docker health 为 unhealthy/starting 时不再误视为健康。
- 操作可以关联 M2 事件和 M3 诊断，但不会直接修改事件状态；M2 仍只接受真实服务观测。
- Caddy 已把 `/api/v1/agents/operations/*` 纳入 Agent Bearer 路由；管理 API 与 Web 继续保留控制台认证边界。
- Web 已提供能力档位、具体映射授权、事件页创建计划、确认页、预检、状态、失败原因和审计时间线。
- 已新增兼容 M1/M2/M3 数据的 `0006_m4_safe_operations` 增量迁移；现有行使用保守默认值。
- `0006` 已冻结为显式表、外键、唯一约束和索引定义，不再从未来 ORM 模型动态建表；同时兼容 API `create_all` 已先创建当前列/表的自托管环境。
- 修复 Alembic 在线升级缺少显式事务提交的问题；使用 `v0.3.3`/`0005` 基线模型创建旧库、写入 Agent/服务映射/M2 事件后升级到 `0006`，旧行全部保留且保守默认值生效。
- 提交前安全复核补充了并发冲突、取消、确认预检漂移、Claim 锁和陈旧状态恢复测试；验证期不再被签名任务过期时间提前截断，Running 租约增加结果上传缓冲，本地账本只淘汰已送达记录。
- M4.1 将 Alembic 配置与迁移打入 API 镜像，但保持部署时显式执行一次迁移，API 启动入口不自动升级；启动 revision 门会拒绝未接管或落后于代码的数据库。
- 旧生产库接管先备份并严格验证当前结构，再一次性 `stamp head`；CI 用真实 PostgreSQL 覆盖 `create_all` 建库、保留旧数据、接管、升级和结构复核。运行时不再调用 `create_all`。
- 发布脚本分离部署前后检查：前置执行 Compose/Caddy 校验、数据库备份和 Alembic SQL 预览，后置验证 revision/结构、数据库感知健康、Agent operation 路由与服务映射候选接口。Caddy 改挂载专用配置目录，并保留强制重建兜底。
- 2026-07-21 M4.1 生产验证通过：API/Web 运行代码对应实现提交 `dbb237b`，生产宿主机当前仓库 HEAD 为文档收尾提交 `632ad10`。`adopt` 一次性接管旧 `create_all` 库（备份 + 严格结构校验 + `stamp head` 到 0006），preflight/migrate/部署/postflight 全部通过；postflight 校验 revision/schema、`/healthz`、Agent operation 路由（非 401）和映射候选接口；Caddy 切到 `deploy/caddy/` 目录挂载。M4 写闭环回归：aliyun-VPS canary `queued -> succeeded`、8 次审计转换、独立健康验证通过；canary 继续运行，保留为 M4.2 测试候选。
- 2026-07-22 M4.2a 生产金丝雀通过：控制平面升级到 `8be69ee`，走标准 `migrate` 到 `0007`（adopt 后首次，验证 M4.1 发布基础设施），postflight 全过；aliyun-VPS Agent 升级 `v0.4.1` + `--deploy-policy plan-only`，两步 RepoDigest 发现 `m4-canary` 为合格候选（`docker.io/library/alpine`）；创建同仓库不同 digest 的冻结计划，保持 `planned`、`permanently_non_executable=true`、无 `active_key`/签名，确认接口 409。
- 2026-07-22 M4.2b 本地实现与真实隔离验证通过：`0008`、独立 v2 严格任务、current/target digest 签名、Agent/控制平面双重授权、允许目录/软链接边界、Compose 双基线 config hash、固定 pull + 单服务重建和同报告 digest+健康验证已落地。真实 PostgreSQL 空库与 `0007 -> 0008` 通过 schema check；真实 Compose 完成 A -> B、B -> A、修复后 A -> B 三次成功闭环，均为 8 次转换，输出不泄露 target/路径/digest；真实不健康目标以 `verification_timeout` 失败且不自动回滚，同服务并发返回 409。隔离过程发现并修复临时 override 留在 `config_files` label、重建瞬间 stable key 重复和 `drift_rejected` 原因码契约三项问题。生产仍保持 M4.2a，不得把本条视为生产发布记录。
- 2026-07-22 M4.2c 本地实现与真实隔离验证通过：`0009` 只增加 `operations.rollback_of` 自引用；失败部署不会自动创建或执行回滚，管理员只能显式创建独立 `m4.2c-rollback-v1` 计划，目标由原计划旧 digest 冻结生成且必须再次确认。真实 `python 3.12 A (healthy) -> 3.13 B (unhealthy) -> A` 中，原部署以 `verification_timeout` 失败并保持不可变，独立 B->A 回滚经过 8 次转换、同报告 digest+健康稳定窗后成功；恢复后重复创建回滚因 current digest 漂移返回 409。生产仍保持 M4.2a。
- 2026-07-23 M4.2b/c 生产金丝雀通过：控制平面 `migrate` 到 `0009`（0008+0009）；aliyun-VPS Agent 升级 `v0.4.2` + `docker_compose_deploy` + 允许目录。alpine A(3.21)->B(3.22) 部署 `succeeded`（同报告 digest==B+健康，8 次转换）；python A(3.12)->坏B(3.13) 部署 `failed/verification_timeout`（M2 异常告警预期），显式回滚坏B->A `succeeded`（目标服务端派生、`rollback_of` 指向失败部署、`rollback_target_frozen` 确认坏镜像在跑、不健康仍可恢复，8 次转换，M2 恢复通知）。**M4 核心（重启+部署+回滚）生产验证完成。**

当时自动验证：API 128 项测试、Web 36 项测试、全部 Go 包测试、Ruff、ESLint、`go vet` 和 Web 生产构建通过。M4.2a 的只读发现/冻结计划、M4.2b 的协议 v2 受控部署与 M4.2c 的独立显式回滚已经并存；历史 plan-only 永久不可执行，旧 Agent 不受影响。真实隔离栈覆盖 PostgreSQL `0008 -> 0009`、A/B 成功往返、不健康失败、独立 B->A 回滚、并发锁、回滚漂移拒绝和部署后双基线复现。既有 M4 重启隔离测试继续覆盖确认门、重复结果幂等、策略关闭、Agent 离线和 API 在 Claimed/Running/Verifying 状态重启后的保守恢复。M4 核心已完成：首轮安全重启、M4.1、M4.2a/b/c 均生产验证，完整 A->B->A（含坏 B 回滚）金丝雀通过；剩余拉源码/构建和受限清理为后续扩展。2026-07-20/21 生产金丝雀在 aliyun VPS（新机、有 Docker）跑通：M4 首批通过提交前安全审计（有条件通过、全部 P2/P3 已处理），提交 `84cb4a2` 推送至 `main` 并发布 `v0.4.0` Release；金丝雀 Agent 以 `--operation-policy docker-restart` 安装，`m4-canary` 映射为 non_critical + restart_enabled，端到端 `queued -> claimed -> running -> verifying -> succeeded`、审计 8 次转换完整、`output` 不含容器 target、`succeeded` 由独立健康观测判定。历史部署坑（0006 加列与单文件 Caddy 挂载）及 M4.1 标准发布路径见 [M4_OPERATIONS.md §10–11](./M4_OPERATIONS.md)。2026-07-23 的 Fleet 快照为 control-plane 自监控、两台腾讯云 `v0.4.0`、旧 aliyun-VPS `v0.4.2` 和 DMIT `v0.3.3`；该旧 aliyun 节点后来已释放，本段不得用于判断当前写权限。

详细协议、安全边界、状态机和验收记录见 [M4_OPERATIONS.md](./M4_OPERATIONS.md)。

## 7. M5：诊断与操作会话体验

状态：**已完成（M5.1–M5.4 相应生产金丝雀通过；M5.5–M5.7 本地实现与验收完成，生产金丝雀通过 2026-07-26）**

2026-07-23 已完成 M5 第一轮架构兼容性和安全审计，并把首个切片冻结为 **M5.1：事件上下文的只读会话基础**。计划确认后完成本地实现、Claude 安全审计（5 P0 门关闭 + 6 P2/P3 修复）、提交 `f53eeee` 推送至 `main`，并以 deterministic 与真实 HTTP(DeepSeek 经临时适配器) Provider 通过生产只读金丝雀。

- M5.1 只使用当前事件范围内已有的 `AlertEvent`、`DiagnosticRun`、`EvidenceItem`、Agent/ServiceInstance 摘要和相关 Operation 只读摘要。
- 回答固定区分事实、推断、建议、缺失信息和真实引用；Provider 不能获得工具权限。
- P0 门已在本地实现关闭：显式事件/组织作用域、服务端引用清单与落库二次校验、M4 零副作用、严格 Provider schema 和统一上下文总预算。
- M5.1 不创建 Operation、不领取 Agent 任务、不访问 VPS、不执行重启/部署/回滚或 GitHub 写操作。
- 详细威胁模型、最小数据模型、API 协议、Web 交互、测试矩阵、实施顺序和金丝雀边界见 [M5_CONVERSATION.md](./M5_CONVERSATION.md)。

本轮新增 `ConversationSession`、`ConversationTurn`、`ConversationCitation` 与显式迁移 `0010_m5_event_conversation`；API 支持 200 空会话、提交问题和轮次轮询，Web 事件页展示历史、结构化回答、真实引用及加载/错误状态。HTTP Provider 超时、连接/HTTP 错误、超大响应、非法 JSON/schema/引用均受控失败，陈旧轮次不会自动重放。

本地验收：API 146 项通过、1 项真实 PostgreSQL 门控测试在常规运行中跳过且在独立 PostgreSQL 中单独通过；Web 41 项、全部 Go 包、Ruff、ESLint、Compose 配置和 Web 生产构建通过。真实 PostgreSQL 覆盖模拟既有 `0009 -> 0010`、`0010 -> 0009 -> 0010`、schema check、跨组织复合外键、单活动轮次、恶意证据脱敏、已有诊断/证据引用落库，以及提问前后 Operation 数量为 0。提交前加固已补齐轮询同源校验、上下文优先预算、四类 HTTP Provider 失败测试、启动期 Provider 配置校验和后台组织参数传递。生产只读金丝雀已于 2026-07-23 通过：控制平面 `df01ec1 -> f53eeee`、迁移 `0009 -> 0010`、postflight 通过；以 deterministic Provider 对事件 `f4ca0d89` 提问，轮次 `completed`（<2s），返回 2 条事实 + 1 条建议（`requires_confirmation=true`）+ 2 个真实引用（`alert_event`、`agent_summary`，均属当前事件作用域），`context_manifest` 583 字节/0 省略；金丝雀前后 `operations=7`/`operation_transitions=45` 不变（零写副作用生产实证），日志无正文/凭据泄露，Fleet Agent 版本未变。未升级 Agent、未改 Agent 策略。真实 HTTP Provider 金丝雀亦通过 2026-07-23（DeepSeek 经临时适配器；已还原 deterministic）。

2026-07-24 完成 M5.2.1 本地实现。`0011_m5_repository_citations` 为仓库引用增加 `ON DELETE SET NULL` 文件外键和无正文墓碑；纯只读 `repository_knowledge.py` 只沿事件→服务实例→最新部署版本→组织仓库→启用 Binding→当前 HEAD 快照派生范围，确定性检索白名单快照并执行 24 KiB 子预算。会话接入了 Commit `aligned/mismatch/unknown` 语义、落库前文件 ID/Commit/内容 SHA/Binding 二次校验、非 aligned 来源禁止支撑 facts、固定 GitHub 链接和 Web 墓碑展示。功能由 `CONVERSATION_REPOSITORY_KNOWLEDGE_ENABLED=false` 默认关闭。

M5.2.1 本地验收：API 157 项通过；Web 43 项、ESLint、生产构建、全部 Go 包和 Compose 配置通过。隔离 PostgreSQL 16 覆盖 `0010 -> 0011`、`0011 -> 0010 -> 0011`、schema check，以及真实事件会话的二次脱敏、跨组织隔离、同步错误 fail closed、零 Operation/GitHub 文件修改和撤权墓碑。M5.2.1 已提交推送 `54f356d`。生产只读金丝雀于 2026-07-24 通过：部署 `54f356d` + 迁移 `0010 -> 0011` + postflight 通过（功能关闭，M5.1 deterministic 无回归）；对已映射 MagicPDF 仓库的非关键服务事件开开关提问，轮次 `completed`，facts 含 `repository_file` aligned 引用（真实 file_id + 服务端构造 GitHub href），`operations=7`/`operation_transitions=45` 不变、GitHub 文件/binding 不变、日志干净；金丝雀后关开关 + 清测试数据，prod 回到 deterministic + 功能关闭。详见 [M5.2_REPOSITORY_KNOWLEDGE.md](./M5.2_REPOSITORY_KNOWLEDGE.md)。

`8c34561` 补齐仓库上下文两个预算阶段的 manifest 省略计数并同步金丝雀文档，`91d8fff` 再修正实现清单和 README；两者已在 `origin/main` 但未部署。生产已于 2026-07-24 升级到 `c382ecb`（含上述两提交 + M5.3.1，迁移 `0011 -> 0012`，postflight 通过）；`CONVERSATION_OPERATION_HANDOFF_ENABLED=false`，prod 运行 M5.1/M5.2 关闭行为。生产于 2026-07-25 升级到 `e0cf851`（M5.2.2，迁移 `0012 -> 0013`，postflight 通过）；`CONVERSATION_REPOSITORY_CHAT_ENABLED=false`，prod 继续运行 M5.1/M5.2 关闭行为。生产于 2026-07-25 升级到 `c06aa8f`（M5.3.2 回滚交接，无新迁移，postflight 通过）；`CONVERSATION_OPERATION_HANDOFF_ENABLED=false` 保持关闭。生产于 2026-07-25 升级到 `cd9531c`（M5.3.3 只读时间线，无新迁移，postflight 通过）；`CONVERSATION_OPERATION_TIMELINE_ENABLED=false` 保持关闭。生产于 2026-07-26 升级到 `58f3308`（M5.4 agent/service 上下文会话，迁移 `0013 -> 0014`，postflight 通过）；`CONVERSATION_CONTEXT_CHAT_ENABLED=false` 保持关闭。生产于 2026-07-26 升级到 `a5208e7`（M5.5-7 fleet/insights/runbook，迁移 `0014 -> 0017`，含离线守卫修复，postflight 通过）；`CONVERSATION_FLEET_CHAT_ENABLED`/`CONVERSATION_INSIGHTS_ENABLED`/`CONVERSATION_REVIEW_ENABLED=false` 保持关闭。

2026-07-24 开始 M5.3 设计与代码审计。首片只设计从已完成事件会话显式交接到现有 M4 `docker_restart` 计划：自然语言和 Provider 输出本身不产生 Operation，用户必须点击独立动作创建待确认计划，之后仍须在现有操作页独立确认。服务实例、动作类型和所有可执行字段由服务端从事件与 M4 策略派生；部署、回滚、GitHub 写操作、自动确认和自动执行均不在首片。详见 [M5.3_OPERATION_HANDOFF.md](./M5.3_OPERATION_HANDOFF.md)。

同日完成 M5.3.1 本地实现：加入 `0012`、Operation 会话来源与请求幂等，抽取并复用 M4 `build_restart_plan`，增加候选 GET、严格 restart-plan POST、默认关闭开关、同源代理、事件页显式交接和操作页来源说明。API 常规回归 164 项、Web 46 项、Ruff、ESLint、Web production build、Go 全包和 Compose 配置通过；隔离 PostgreSQL 16 完成空库升级、`0012 -> 0011 -> 0012`、两次 schema check 及 M5.1/M5.2/M5.3 三项门控测试，验证请求唯一约束、删除轮次后的 FK `SET NULL` 和来源墓碑。生产计划级金丝雀已于 2026-07-24 通过：部署 `c382ecb` + 迁移 `0011 -> 0012` + postflight；功能关闭回归（M5.1 deterministic + 候选 `feature_disabled` + ops 不变）；开启后对 m4-deploy-bad 服务事件（临时开 restart）提问 -> POST restart-plan 创建 `awaiting_confirmation` Operation `27f2b091`（`task_signature/nonce=NULL`、`source_conversation_turn_id` 链接、Agent `queued=0` 不可领取）；同 `client_request_id` 幂等返同 Operation；Operation 5min 过期（`expired` 终态）；删轮次验证 FK `SET NULL`（`source_conversation_turn_id=NULL`，`plan_snapshot` 墓碑保留）；还原（关 restart + 关开关，候选 `feature_disabled`）。执行级金丝雀亦于 2026-07-24 通过（用户明确授权）：Operation `d4779ded` 在操作页独立确认 -> M4 Ed25519 签名 -> `queued` -> aliyun-VPS Agent 领取 -> `running`（`docker restart` m4-deploy-bad）-> `verifying` -> `succeeded`（~69s，独立健康观测+稳定窗口）；8 次审计转换、`exit_code=0`、`task_signature` 非空、`output` 固定摘要不含容器 target；会话发起的计划经 M4 完整闭环真正执行，不绕过 M4。还原（关开关+关 restart，候选 `feature_disabled`）。两个金丝雀 Operation 均作为审计记录保留。

2026-07-25 完成 M5.3.1 文档复核并开始 M5.2.2 设计。首片冻结为单仓库上下文对话抽屉：会话目标由路径中的仓库 ID 经组织和当前 GitHub Binding 服务端校验，不允许问题正文选择其他仓库、Commit 或路径；只使用控制平面已有的当前脱敏快照，不实时访问 GitHub，不触发同步，不读取 VPS，也不创建 Operation。全局仓库聊天首版仅作为授权仓库选择入口，选择后复用单仓库会话；跨仓库混合上下文、向量检索和 GitHub 写操作继续后置。设计、威胁模型、迁移/API 草案、测试矩阵和金丝雀边界见 [M5.2.2_REPOSITORY_CONVERSATION.md](./M5.2.2_REPOSITORY_CONVERSATION.md)。

同日完成 M5.2.2a/b 本地实现：`0013_m5_repository_scope` 增加 event/repository 严格二选一、仓库组织复合外键和 `repository_basis=deployment|snapshot`；API 增加仓库详情、200 空会话、严格轮次 POST、scope-aware 轮询、快照上下文和落库前二次校验；Web 增加仓库详情抽屉及只选择一个授权仓库的全局入口。独立开关 `CONVERSATION_REPOSITORY_CHAT_ENABLED=false` 默认关闭。API 172 项通过、4 项数据库门控跳过；Web 49 项、ESLint、production build、Go 全包和 Compose 配置通过。临时 PostgreSQL 16 完成空库升级、`0013 -> 0012 -> 0013`、两次 schema check 和 M5.1/M5.2.1/M5.3.1/M5.2.2 四个门控测试，全部通过；验证了跨组织/非法 scope 约束、snapshot 引用、脱敏、撤权墓碑和零 Operation/GitHub 写副作用。M5.2.2 已提交 `e0cf851` 推送至 `main`。

生产只读金丝雀于 2026-07-25 通过：部署 `e0cf851` + 迁移 `0012 -> 0013` + postflight（功能关闭，M5.1 deterministic 无回归）；对 MagicPDF 仓库（`repositories.id=713c7632-3376-4f59-b8ba-170a53c47c7c`）开开关后，仓库详情 200 返回文件元数据（README.md，无正文/凭据）、空会话 200、提问 `completed`（provider=deterministic），citation `source_type=repository_file`/`repository.basis=snapshot`/`deployment_commit_sha=null`/`deployment_relation=unknown`/`available=true`，`context_manifest` 为 `m5.2.2-repository-context-v1`/`scope_type=repository`；`operations.source_conversation_turn_id` 指向本次轮次查 0 行（零写副作用生产实证），ops/trans 与 GitHub 文件/binding 不变、日志干净；金丝雀后关开关，prod 回到 deterministic + 功能关闭（`conversation_available=false`/`unavailable_reason=feature_disabled`）。

同日完成 M5.3.2 本地实现与验收：复用 `0012` 会话来源/请求幂等和 `0009` `rollback_of`，不新增迁移；候选 GET 增加固定 `docker_compose_rollback`，严格 rollback-plan POST 只从当前组织、事件派生实例及事件观测窗口内唯一匹配的原始失败部署生成计划，请求体不接受失败部署 ID、digest、实例、路径或确认字段。M4 原入口和会话入口共同复用唯一 `build_rollback_plan`，结果只到 `awaiting_confirmation`，无签名/nonce，且与 restart 交接继续通过 `active_key` 互斥。真实 PostgreSQL 门控还发现并修复 M5.3.1 活动写冲突后的 ORM 失效读取，现以冻结字符串 ID 稳定返回 409。API 176 项、Web 54 项、Go 全包、Ruff、ESLint、production build、开发/生产 Compose 配置通过；隔离 PostgreSQL 16 完成空库升级、`0013 -> 0012 -> 0013`、两次 schema check 和 M5.1/M5.2.1/M5.3.1/M5.2.2/M5.3.2 五项门控。生产金丝雀通过 2026-07-25。

随后完成 M5.3.3 本地实现与验收：独立开关 `CONVERSATION_OPERATION_TIMELINE_ENABLED=false` 默认关闭；新 GET 先按组织/事件解析，只返回最近 20 项同事件 Operation 的有限摘要、白名单验证状态及不含 details/reason/actor ID 的转换，不返回计划、digest、输出、签名、nonce 或 Agent target。事件会话增加只读操作历史、详情链接和到当前 Agent M4.2 部署候选区的可信导航；服务键仅对服务端已返回候选排序/高亮，不进入写请求，也没有会话部署端点。API 179 项、Web 57 项、Go/Ruff/ESLint/build/Compose 通过；真实 PostgreSQL 16 完成空库升级、`0013 -> 0012 -> 0013`、两次 schema check 和六项 M5 门控，验证三类关联、事件/组织隔离、20 项上限和 GET 零 Operation/Transition 副作用。生产金丝雀通过 2026-07-25。

2026-07-26 完成 M5.4 单 Agent/单服务上下文只读会话本地实现与验收：`0014_m5_context_scope` 为 Agent 与 ManagedService 增加可供组织复合引用的唯一约束，并为会话增加独立 `agent_id/service_id`、唯一约束、组织复合外键和 event/repository/agent/service 严格四选一 CHECK。Agent 页面直接提供机器上下文会话；已映射服务进入独立服务会话页，服务 ID 始终从 URL 实例和数据库关系服务端派生。上下文仅含当前 scope 的 Agent、实例状态、事件、诊断、有限证据和 Operation 只读摘要；Provider 无工具，引用落库前按当前组织与 scope 二次查询。独立开关 `CONVERSATION_CONTEXT_CHAT_ENABLED=false` 默认关闭。API 186 项、Web 63 项、Ruff、ESLint、production build 通过；隔离 PostgreSQL 16 完成空库升级、`0014 -> 0013 -> 0014`、两次 schema check 与七项 M5 门控，跨组织复合外键、混合 scope 拒绝、恶意证据脱敏和零 Operation/Transition 副作用均通过。生产金丝雀通过 2026-07-26，详见 [M5.4_CONTEXT_CONVERSATION.md](./M5.4_CONTEXT_CONVERSATION.md)。

同日完成 M5.5–M5.7 收尾统一设计，并按顺序连续完成本地实现与验收。`0015_m5_fleet_conversation` 增加第五种严格 Fleet scope、不可变组织聚合快照和快照引用墓碑；Provider 异步阶段只读取已持久化 counts/IDs，不重查 live 聚合，摘要覆盖候选 source IDs。`0016_m5_conversation_feedback` 增加一轮一反馈，事件页增加统一历史、确定性同组织相似事件与显式反馈。`0017_m5_runbook_drafts` 增加不可执行草稿、只读复盘和草稿详情；草稿重新查询 citation 行，引用或快照删除后只显示无正文墓碑，来源轮次删除后复合 FK `SET NULL` 而草稿组织审计保留。三个新开关均默认关闭，不新增 Agent/VPS/GitHub 网络或 Operation 写路径。API 199 项、Web 67 项、Ruff、Python compile、ESLint、production build、Go 全包与 vet 通过；隔离 PostgreSQL 16 完成空库升级、`0014 -> 0017 -> 0014 -> 0017`、schema check 和八项 M5 门控。生产金丝雀通过 2026-07-26；详细设计与证据见 [M5_COMPLETION_PLAN.md](./M5_COMPLETION_PLAN.md)。

## 8. M6：自托管产品化

状态：**已完成（v0.6.1 正式发行与生产升级金丝雀通过 2026-08-01；2026-08-02 文档收口）**

2026-07-26 完成 M6 第一轮发布、Compose、Alembic、备份/恢复、Agent 安装升级、版本/健康、Web 管理入口、CI 和发布资产审计。当前结论：

审计时的生产控制平面基线为 `ff4f5bc`、Alembic `0017_m5_runbook_drafts`；该次 M3 Provider 收尾镜像重建、`--no-cache` 教训与生产验证记录见 [M3_CLOSEOUT.md §10](./M3_CLOSEOUT.md#10-生产金丝雀执行记录2026-07-26)。M6.1 首片已于 2026-07-27 部署 `38b8d40` 并通过生产金丝雀（见本节末尾）；这是一条历史记录，任何后续生产动作仍须实时核对运行镜像和 revision。

- M6.1 首片已让 `adopt`/`preflight` 共用同快照原子备份包（dump、严格 manifest、SHA256SUMS、archive 校验），并加入只允许隔离项目、显式实例确认和空目标的恢复 CLI；无新迁移，head 保持 `0017`。
- API/Web Dockerfile 和生产 Compose 现要求显式 build version/40 位 commit/build time，缺失时只使用显眼假值或在生产设置校验中失败；受管理 system-info 返回实际/期望 revision，公开 `/healthz` 保持最小响应，Web 页脚不再硬编码版本。
- API 测试入口已中性化工作区 GitHub 环境污染，且保留部分 GitHub 配置拒绝断言；从仓库根目录运行 212 项通过、9 项数据库门跳过。
- Agent Release 已有双架构产物、SHA-256 和 systemd 安全配置，但升级没有 last-known-good 自动回退、发布者签名或控制平面兼容门。
- 该 2026-07-26 审计时 Web 尚无 PWA/移动审批/更多通知；此历史缺口现已由 M6.2 和 M6.3a/b/c+d 关闭主要入口，M6.3c+d 已完成。团队协作仍未实现。

M6 顺序冻结为 M6.1 可恢复性与发布基础 → M6.2 PWA/移动只读与审批 → M6.3 通知/模板/引导配置 → M6.4 协作/开源评估；Web SSH 和限时高风险会话最后单独设计。第一纵向切片“可验证的控制平面 PostgreSQL 备份与离线恢复基础”已由 codex 实现并经 Claude 审计（无 P0/P1；P2-1 symlink 经 ubuntu CI 确认；P3 非阻断）：真实 PostgreSQL 16 完成迁移、种子数据、同快照备份、测试卷清空、空库恢复、schema check 和关键记录一致性；损坏包、伪造 commit、错误实例确认与非空目标均失败关闭。Web 69 项、Go test/vet、Ruff、build、Compose、Caddy 和 Alembic head 检查通过。已提交 `38b8d40` 推送至 main，CI `Control Plane Recovery` 通过。完整边界见 [M6_PRODUCTIZATION.md](./M6_PRODUCTIZATION.md)。

M6.2a/M6.2b 已完成本地实现、验证和独立源码审计：新增 manifest、静态图标、受限 service worker、无业务数据离线页、独立 `/mobile` 只读状态页、移动安全区/只读导航，以及展示冻结目标、动作、风险、有效期和前置检查的独立审批卡。审批默认禁用，必须显式勾选且在线，仍仅调用现有同源 M4 确认代理；不新增 API、迁移、Agent 协议、后台同步或离线写。代码 `80b950f` 部署后首轮 PWA 实机金丝雀发现 `/sw.js` 返回 Next 404（standalone runtime 未复制 `apps/web/public`，源码级测试未覆盖最终镜像内容）。修复 `fa35eee` 补 `COPY .../public`、Dockerfile 回归断言和 `Control Plane Web` Ubuntu CI（真实构建/启动镜像+验证 4 资产），三个 CI 全通过；生产重新部署 `fa35eee` 后 Phase 3 PWA 实机金丝雀通过 2026-07-27（SW 注册+预缓存仅 3 静态资产、Chrome 在 Basic Auth 下安装+standalone 启动、离线无数据泄露、ops/trans 13/81 不变）。Phase 4 移动 M4 审批写路径全链路金丝雀通过 2026-07-27（m4-deploy-bad 临时 restart，op `43191ab3`，移动端核对+确认触发完整 M4 链，ops/trans +1/+8，还原）；M6.2 完成，边界与失败/通过记录见 [M6_PWA_MOBILE.md](./M6_PWA_MOBILE.md)。

M6.2 金丝雀前后生产 `CONVERSATION_REPOSITORY_KNOWLEDGE_ENABLED=true` 与 `CONVERSATION_OPERATION_TIMELINE_ENABLED=true` 均未变化；二者是既有 M5 只读能力，不是 M6.2 写副作用。当前证据尚不能证明其启用来源，保留为独立 M5 配置回溯项，不借 M6.3 改动生产开关。

2026-07-28 开始 M6.3 代码审计并完成首片本地实现。现有 M2 通知已具备钉钉 firing/resolved、事件序列去重、最多 3 次尝试和陈旧 sending 回收，但告警建单仍硬编码 `dingtalk`，配置只来自环境变量，Web 无秘密安全的就绪状态或引导入口。M6.3a 增加受管理认证保护的秘密不回显状态 API、与实际渲染共用的固定 4 类模板目录和只读引导配置页；不发送测试消息、不新增第二通道、迁移、Agent/M4/Operation 变更或外部写副作用。API 216 项、Web 84 项、Ruff、ESLint、Web production build、Go test/vet、Compose 配置和 Alembic 单 head 均通过；Claude 审计通过（无 P0/P1/P2），提交 `19e829b` 推送至 main，三个 CI（Recovery/Migrations/Web）全绿。2026-07-28 生产金丝雀通过：`/api/v1/system-info` commit=19e829b、`/api/v1/notification-configuration` 秘密不回显 ready=true（响应与页面 HTML 均不含 webhook/secret）、未带 admin token 401、ops/trans 14/89 不变。M6.3 后续 M6.3b/c+d 均已完成（见下文与 [M6_NOTIFICATIONS.md](./M6_NOTIFICATIONS.md)）。

同日完成 M6.3b 本地实现：首片冻结为默认关闭的钉钉固定测试消息，新增独立 `0018_m6_notification_tests` 审计表、严格请求 UUID 幂等、数据库固定窗口限速、最多一次发送和陈旧 sending 的未知结果终止语义。Web 只允许同源空正文请求，按钮默认需显式勾选；不接受 URL、收件人、消息正文或模型输入，不创建 AlertEvent/Operation。API 227 项、Web 87 项、Ruff、ESLint 和 Web production build 已通过；Claude 审计通过（无 P0/P1；P2-1 迁移 downgrade offline 守卫已修复），提交 `a4944fb` 推送至 main，三个 CI 全绿（含双向离线 SQL + 真实 PG 幂等/限速/零副作用门）。2026-07-28 两阶段生产金丝雀通过：Phase A 功能关闭 403 + 迁移 0018 + ops/trans 不变；Phase B 临时开启发一条测试 succeeded/attempt_count=1、幂等重放 200 不重发、同窗口新键 429、钉钉群收到 1 条；还原关闭 403，ops/trans 14/89 不变、独立审计表 4 条 succeeded（KEY5 被 429 拦截不入库）、不污染 AlertEvent/Delivery。该段记录的是 M6.3b 收尾时点，当时 M6.3c/d 尚未开始。

2026-07-29 完成 M6.3c+d 本地实现：先修复生产通知把原始 HTTP 异常（可能含签名 Webhook/token）写入 `last_error` 的 P1，统一改为稳定错误码；新增 Telegram 固定官方端点、`NOTIFICATION_CHANNELS` 内置白名单组合、飞书“已注册但未实现”拒绝位、同一逻辑 sequence 的每通道独立 Delivery、`v1` 模板 key/version 和冻结渲染上下文。通道集合在 AlertEvent 创建时冻结并贯穿 firing/resolved 生命周期；Telegram 测试复用 M6.3b 空正文、UUID 幂等、每通道数据库限速、最多一次和有限审计链，且只有显式启用并完整配置的通道才能创建测试。首次提交 `ece22d5` 后，真实 PostgreSQL Migrations/Recovery CI 发现 revision 字符串超过 Alembic `version_num VARCHAR(32)` 的 P0；已缩短 head 为 `0019_m6_multichannel_notify` 并新增全迁移 revision 长度回归门，API 本地 `238 passed, 11 skipped`。downgrade 对 Telegram 测试审计、未终结非钉钉 Delivery 和仍冻结多通道的活跃告警失败关闭；实现完成时生产仍为 `a4944fb + 0018` 且只启用钉钉。修复后提交 `1073969` 推送至 main，三个 CI 全绿（含真实 PG 多通道隔离测试 + revision 长度门）；Claude 审计通过（无 P0/P1；P0 revision 长度已修复）。2026-07-29 生产金丝雀通过：部署 `1073969` + 迁移 0019 + postflight；system-info commit=1073969/revision=0019/schema_current=true；notification-configuration 多通道视图（dingtalk impl+enabled+configured / telegram impl+!enabled / feishu !implemented）；ops/trans 14/89 不变；既有 17 deliveries + 25 alert_events 全部 backfill 模板字段+`["dingtalk"]` 通道集。Telegram 未配置、未启用、未实发；适配器与双通道隔离由真实 PG CI 覆盖，不能把本次金丝雀描述为 Telegram 生产实发证明。M6.3 完成。

同日完成 M6.4 第一轮协作/开源评估；在该审计时点代码尚未开始。当前 Caddy Basic Auth 与 `ADMIN_API_TOKEN` 均为共享管理员边界，API 没有 Principal/RBAC，Operation `requested_by` 固定为 `local-admin` 且确认 `confirmed_by` 来自请求正文，因此不能把现状描述为可信团队审计。审计时仓库没有 LICENSE、SECURITY、CONTRIBUTING、第三方许可证清单、控制平面正式发行、SBOM 或签名/provenance；Agent 只有 SHA-256，Actions 和基础镜像仍以可漂移 tag 为主。M6.4 顺序冻结为：秘密安全源码发行门 → 服务端可信 actor/只读角色 → 具名 M4 审批 → 正式发行收尾；SaaS、多租户、公开注册和 Web SSH 继续冻结。详见 [M6_COLLABORATION_OPEN_SOURCE.md](./M6_COLLABORATION_OPEN_SOURCE.md)。

2026-07-30 进入 M6.4a 本地实现阶段：新增 AGPL-3.0-only 默认范围与 Apache-2.0 Agent 范围、REUSE 3.3 目录映射、NOTICE/第三方通知、安全与贡献政策；源码候选只从 Git 索引生成，拒绝运行环境、密钥、备份、数据库、日志、缓存和 symlink，并产出 commit 绑定的 archive、manifest 与 SHA-256；依赖门清点 Python/Node/Go 并仅接受精确许可证表达式，REUSE 生成源码 SPDX。GitHub Actions 固定到 action commit，在干净 Ubuntu checkout 执行 Gitleaks、负向测试、依赖许可证、REUSE 和发行候选构建。技术来源审计仅发现 `YY Home` 的 80 个提交和 `root` 的 1 个 `.gitignore` 提交；所有者同日明确确认拥有或已获授权许可全部项目原创内容、无已知冲突权利，并接受以 `YY Home` 为权利人名称及既定双许可证范围。该阶段记录时独立审计、提交与 CI 尚未完成；后续完成证据见下文。只读核对还发现 GitHub 仓库在本次实现前已是 Public；本轮未修改可见性，先补许可证与安全门。

同日独立审计发现 M6.4a 首版 Python 许可证清单读取当前解释器全部 distributions，污染环境中的无关包会改变结果并可能令 CI 失败（P1）。修复后以 `requirements-dev.txt` 及递归引用为根，按已安装元数据的 `Requires-Dist`、extras 和 marker 计算传递闭包；非项目包不再进入清单，长许可证正文回退 classifier，常见非标准名称仅精确映射到 SPDX，未知/双重含糊条款仍失败关闭。新增闭包隔离、extra、嵌套 requirements 与许可证规范化测试；污染环境和干净 API venv 均生成 43 个 Python + 378 个 Node 依赖并通过。该处记录的是修复后的本地阶段；最终 Ubuntu CI 证据见下文。

M6.4a 随后以 `ed4e584` 提交，并按 CI 失败证据完成三轮收敛：`3d62f28` 对新增测试中的两项合成 PEM 以 commit 指纹精确抑制；`8122dc8` 审核并批准 Next.js/sharp Linux 平台包的 `LGPL-3.0-or-later`；`0a47a15` 为 clean-worktree 失败增加有限状态诊断；`714da5a` 忽略 Gitleaks Action 生成的 `results.sarif`。最终 HEAD `714da5a` 的 Control Plane Recovery、Migrations、Web、Source Distribution 四条 CI 全部成功；Source Distribution 实证 Gitleaks、283 文件源码检查、REUSE 278/278、421 包零拒绝、SPDX 与 archive build。该切片只改变源码分发/治理/CI，不含 API、数据库、Agent 或生产运行变更，因此无需生产金丝雀；M6.4a 状态收口为已完成。

同日完成 M6.4b 代码前设计。当前多数只读 GET 在 API 内没有独立认证，依赖外层 Caddy Basic Auth；Web 再经内部网络读取 API，因此不能直接信任浏览器身份 header。首片拆为 b1/b2：b1 由 Caddy 覆盖 authenticated user/header 并注入仅服务间共享 token，Web/API 常量时间验证后构造固定 `local` 的 Principal shadow；b2 只对 system/fleet/event 的明确 GET 执行有限 read capability。两个 flag 默认关闭；无迁移、不修改任何写权限、M4 actor/状态机或 Agent。完整威胁模型、测试与金丝雀边界见 [M6_PRINCIPAL_READONLY.md](./M6_PRINCIPAL_READONLY.md)。

随后连续完成 M6.4b1+b2 本地实现：Caddy 对认证后的 Web/管理 API 覆盖 Principal ID/source/proxy-token，对 Agent、GitHub webhook、下载和 `/healthz` 清除这些 header；Web 只在 server-only helper 常量时间验证 token 后向 API 转发，API 再验证唯一 header、固定 source、token、用户名格式和部署 allowlist。`/principal` 只返回有限 shadow/read-enforced 视图；`system:read`、`fleet:read`、`event:read` 只挂到冻结的 5 个 GET，开关关闭时保持旧行为，所有 POST、写代理、M4 actor/状态机和 Agent 均未修改。未新增迁移，head 保持 `0019_m6_multichannel_notify`。本地 API 定向测试、Ruff、Web 95 项、ESLint、production build、Compose config 和 diff check 已通过；真实 Caddy 覆盖/清除集成门已加入 Web CI。Claude 审计通过（无 P0/P1/P2），提交 `4c19a45`+`d847a7d` 推送至 main，四个 CI 全绿（含真实 Caddy 集成测试）。2026-07-30 两阶段只读生产金丝雀通过：Phase A flags OFF 无回归；Phase B shadow `/principal` 返回 `caddy-basic:admin`、伪造 header 被 Caddy 覆盖（生产实证）、token 不泄露、ops/trans 14/89 不变；Phase C read-enforced 5 GET 可访问（principal capability）、无 Basic Auth 401、`/healthz` 200、ops/trans 不变；Phase D 还原 403。

同日完成 M6.4c 代码前审计与设计。当前 M4 全部计划入口仍把 `requested_by`/首条 Transition actor 写死为 `local-admin`，确认端点仍接受正文 `confirmed_by`，Web 确认代理仍持共享 `ADMIN_API_TOKEN`，生产 Caddy 也只有一个 Basic Auth 用户；因此不能直接把 M6.4b read token 或单用户 Principal 升级为具名写授权。冻结方案使用独立且不注入 Web 的 write token、至少两个不同 Caddy subject 到稳定 Principal ID 的部署绑定、`operation:read/plan/approve` 精确路由矩阵、Operation/Transition 不可变 actor 快照和行锁 maker-checker；选定 M4 写请求改为浏览器同源直达 Caddy→API，feature off 保留 legacy，break-glass 默认关闭并具有独立原因/请求键/高优先级审计。计划新增 `0020_m6_named_approval`，不修改 Agent/M4 任务签名与状态机；实施拆为 c1 写上下文 shadow、c2 具名计划、c3 具名确认。完整威胁模型、迁移、测试和金丝雀边界见 [M6_NAMED_APPROVAL.md](./M6_NAMED_APPROVAL.md)。本段只完成设计，不含代码、提交、生产凭据或 Operation 变更。

随后完成 M6.4c1 本地实现：严格 JSON 角色绑定与稳定 UUID Principal、独立且不进入 Web 的 write token、admin/operator/approver 三组 Caddy 凭据、方法+路径精确匹配的 7 个 M4 POST shadow、部署配置 preflight，以及 `0020_m6_named_approval` actor snapshot schema。所有 shadow 依赖仍继续执行原 `require_admin`，只记录有限 would-allow/would-deny，不改变任何 M4 允许/拒绝结果、actor、确认正文、签名、nonce 或状态机。API `282 passed, 12 skipped`；Web `95 passed`、lint/build；Agent test/vet、Ruff、单 head、0020 双向离线 SQL、Compose config 和部署预检通过。Docker Desktop 恢复后，真实 Caddy 多用户/7 路由/header 隔离、真实 PostgreSQL 16 全迁移、备份→隔离恢复→schema check，以及具名快照 downgrade fail-closed（`1 passed`）均通过；同时修复 Windows Git Bash 测试挂载和 Recovery fixture 的新 Caddy 必填变量。当前未提交、未部署，生产仍为 `d847a7d + 0019`、flags OFF；push 后 Ubuntu CI 仍需全绿。已提交 `48263db`+`d6a9528` 推送至 main，四个 CI 全绿。2026-07-30 两阶段 shadow 生产金丝雀通过：Phase A flags OFF 部署迁移 0020 + Caddy 三组凭据 + 无回归；Phase B shadow operator/approver `/principal` 稳定 ID/角色/capability + 伪造 header 被 Caddy 覆盖 + write token 不泄露 + ops/trans 14/89 不变；Phase C 还原 403。生产现运行 `d6a9528 + 0020`，flags OFF。

2026-07-31 完成 M6.4c2 本地实现与验证：`operation:plan` 只接入冻结的六条计划 POST，operator 创建的 Operation 与首条 Transition 写入稳定 Principal 快照；`operation:read` 只接入单 Operation GET，operator/approver 可读。Web 在 enforcement 模式改为浏览器同源直达 Caddy→API，API 校验 Origin、Fetch Metadata、JSON 和独立 write token；对应 legacy Web 管理代理失败关闭。c2 阶段尚未实现 c3，因此确认 API/页面在 enforcement 模式返回 409 且不显示执行控件；启动还会拒绝带 legacy awaiting/queued Operation 的模式切换。无迁移，head 保持 0020；API `291 passed, 13 skipped`、Web `98 passed`、lint/build、Ruff、Go test/vet、Compose config、真实 Caddy 与临时 PostgreSQL 16 两项具名审计测试通过。提交前基线为 `d6a9528 + 0020`、flags OFF；随后提交 `c78ae35` 推送至 main，四个 CI 全绿。2026-07-31 生产金丝雀通过：Phase A flags OFF 部署 c78ae35 + 无回归；Phase B enforcement approver 创建 403 + 无 Origin 401 + 确认 409 + operator 创建具名计划 `requested_by=local:50afb0f6-...`/`authorization_mode=named`/快照/`task_signature=null`/`nonce=null` + approver 确认 409 + restart 还原；ops/trans 15/92（+1/+3，无签名/nonce/Agent 领取）；DB `has_snapshot=t`；Phase C 还原 403。该阶段结束时生产运行 `c78ae35 + 0020`，flags OFF。

同日完成 M6.4c3 实现与验证：`operation:approve` 只接入冻结的 confirm POST，enforcement 下正文必须为空，可信 approver 由 Caddy/API write token 链派生；API 在 `SELECT FOR UPDATE` 事务内比较稳定 creator/approver ID，同人返回 409 且不预检、不签名、不写 Transition。成功确认写入 Operation 与 queued Transition 的审批快照并继续复用原 M4 预检、Ed25519 签名、Agent claim/execute/verify 状态机；同一审批人仅在 Operation 仍为 `queued` 时幂等 200，进入后续或终态后按状态机返回 409，其他审批人冲突 409。事故 break-glass 默认关闭、无 Web 入口，只接受管理令牌、规范 UUIDv4 请求键、1–256 字符无控制字符原因和空正文，写入 `authorization_mode=break_glass`、固定 actor、有限原因与 warning 审计；Web 仅向具有 approve capability 且不是 creator 的身份显示原有显式勾选确认控件。无迁移，head 保持 0020；API `300 passed, 14 skipped`、Web `100 passed`、lint/build、Ruff、Go test/vet、Compose config、真实 Caddy 4KB 写体限制和临时 PostgreSQL 16 并发确认/单 queued Transition 门均通过。代码提交 `2673877`，Gitleaks 修复 `0d75342`，四条 CI 全绿。2026-07-31 生产金丝雀通过：operator 创建具名计划后因缺少 `operation:approve` 自确认返回 403；独立 approver 确认后 Operation 进入 `queued` 并经签名、Agent 领取、`docker restart` 和健康验证到 `succeeded`；终态回放同 approver 返回 409、operator 仍返回 403。旧 aliyun-VPS 已释放，临时新 Agent 使用下划线形式的 `docker_logs`/`docker_restart` 环境策略完成验证；服务 restart 授权与 Principal flags 随后还原关闭。生产运行 `0d75342 + 0020`。

同日完成 M6.4d 正式发行与开源分发设计审计，冻结公开坐标、统一 SemVer、Agent/控制平面制品、SBOM、checksum、Sigstore keyless 签名/provenance、digest-pinned release bundle、兼容与回退矩阵、干净主机演练和发布授权边界。随后完成本地连续实现：统一 `v0.6.1`/正式 Go module 坐标，固定 Actions 与基础镜像 digest，新增 candidate-then-promote 正式 workflow、Agent 签名验证、release bundle/兼容矩阵/CHANGELOG、digest-only release Compose 和真实临时 registry 集成门；隔离验证已完成候选镜像回拉、空库迁移至 `0020`、非 root 启动、schema/health/system-info/build identity 核对。实现中额外修复了提交者非 UTC 时区导致生产构建时间校验失败的问题。

2026-08-01 v0.6.1 正式公开发行：tag `v0.6.1` 指向 `8746182`，Formal Release workflow 四阶段（review → draft → candidate → publish）全部成功；四条 CI（Control Plane Recovery、Migrations、Web、Source Distribution）全绿；PVR 已启用并通过 create-draft 门；Release `isDraft=false`、`isPrerelease=false`、32 个资产。API 镜像 `ghcr.io/ymasout/vps-agent-api:v0.6.1`（manifest digest `sha256:7bc0fb29ffcfadc3ff8f76dff066301fa301e525ab361c5bb63a9a1a9661373c`）与 Web 镜像 `ghcr.io/ymasout/vps-agent-web:v0.6.1`（manifest digest `sha256:e05136ea7fee0a8a36155294403350f5b620d7043368982b810034834407af13`）均已公开可匿名拉取。详见 [M6_RELEASE_DISTRIBUTION.md](./M6_RELEASE_DISTRIBUTION.md)。

同日完成 v0.6.1 生产升级金丝雀：从源码构建基线 `0d75342` 切换到 digest-pinned release 镜像。Phase 0 实时核对确认 `0d75342 + 0020`、5 Agent online（aliyun-VPS 已释放 offline 符合预期）、Principal flags OFF；M6.1 原子备份包 `control-plane-pre-migration-20260801T195202Z` 生成并 inspect 通过；migrate 为 no-op（`0020` → `0020`）；postflight 全过（revision/schema/health/Agent operation route/mapping candidates）；build identity 更新为 `commit_sha=8746182`/`version=0.6.1`/`build_time=2026-08-01T13:31:01Z`（与 OCI label 一致）；Agent 状态不变、日志无错误/凭据泄露；Web 200、`/healthz` ok、PWA manifest 在 `/manifest.webmanifest` 返回 200。Postgres/Redis/Caddy 因 Docker Hub DNS 异常保持现有缓存版本运行，仅 API/Web 切换至 release digest。`deploy/.env.production` 的 `CONTROL_PLANE_COMMIT_SHA`/`CONTROL_PLANE_BUILD_TIME` 已更新为 v0.6.1 值并备份旧文件。

2026-08-02 完成 M6 文档收口：兼容矩阵中“`0d75342 + 0020` → v0.6.1”路径依据上述生产金丝雀标记为 Passed。M6 的已冻结交付范围至此完成。Agent last-known-good/失败回退、生产对已签名 release bundle 的自动验证/落地、密钥与配置的加密离机灾备及 RPO/RTO 演练、持续发行安全扫描仍是明确的后续加固项，沿用 M6.1c/d 名称但不被误写成已实现；Web SSH/实时终端继续独立设计。正式 bundle 已确定性包含非秘密 `deploy/release/images.env`，本次生产只是手工生成了宿主机副本。Docker Hub DNS 异常未影响 API/Web 精确 digest 升级，Postgres/Redis/Caddy 本次未拉取新镜像。

2026-08-02 随后开始 M6 后续批次 A：Agent 事务式 last-known-good/失败回退、精确签名升级元数据、boot-ID recovery oneshot、签名 release bundle 安全暂存，以及 Dependabot/CodeQL/OSV/Trivy 持续发行门已完成本地实现、验证和独立审计并已本地提交。该批次尚未推送或执行 GitHub CI/正式发行/生产金丝雀，因此不得改写为已发布或生产完成；M6.1d 灾备闭环仍仅有设计。详见 `POST_M6_RELIABILITY_SECURITY.md` §12。

2026-07-27 M6.1 生产金丝雀通过：部署 `38b8d40`（注入 build version/commit/build time）+ postflight；`/api/v1/system-info` 返回 `commit_sha=38b8d40e76ea1c30497bbfa0f17d2b87aaa27977`、`version=0.6.1`、`schema_current=true`、`alembic_revision=["0017_m5_runbook_drafts"]`；`preflight` 生成原子备份包 `control-plane-pre-migration-20260727T131115Z`，`inspect` + 隔离空库 `restore` 成功，审计摘要 `schema_current=true`/`key_table_counts_match=true`/`active_operation_count=0`；恢复后 `ops=13/trans=81/agents=5` 与生产一致；生产 `ops/trans` 前后不变、日志无秘密、开关未变；隔离项目已清理，首份原子备份包保留（0700/0600）。M6.1 无 feature flag，`38b8d40` 留作运行基线。

## 9. 文档维护规则

- 架构或协议发生变化时更新 `ARCHITECTURE.md`。
- 每个里程碑开始和完成时更新本文件。
- 范围、状态或验收条件变化时更新 `ROADMAP.md`。
- 原始项目计划书作为产品基线保留，不用实际进度覆盖原文。
