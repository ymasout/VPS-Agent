# 项目状态

最后同步：2026-07-19
当前阶段：**M0、M1、M2 已完成；M3 进行中**

## 1. 当前结论

项目已完成工程骨架、“机器可见”和“异常可通知”里程碑。生产控制平面通过 Caddy/HTTPS 运行，Agent 使用一次性令牌注册、独立凭证认证和主动出站 HTTPS 上报；服务异常、去重、钉钉通知和恢复通知已经过生产杀手路径验证。

当前共有 4 条真实 VPS 机器记录。M1 验收时，3 台外部 VPS 和控制平面宿主机均通过 Release 安装器运行 Agent `v0.2.4`；M3 生产验证已将一台金丝雀升级到 `v0.3.0` 并保留原身份，其余机器未要求同步升级。M1 的“至少 3 台真实或测试 VPS 稳定接入”验收线已经满足。

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

状态：**进行中**

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

当前自动验证：API 66 项测试、Web 20 项测试、全部 Go 包测试、Ruff、ESLint、`go vet` 和 Web 生产构建通过。PostgreSQL DDL 已按 PostgreSQL 方言编译全部 17 张表，Alembic head 为 `0004_m3_service_discovery`；Caddyfile 本轮未修改，生产 Compose 配置继续可解析。

2026-07-17 已使用独立本地 Compose 项目完成真实 Caddy、PostgreSQL、API 和 Agent 端到端验收：Agent 只经 Caddy 注册、报告、领取和完成 Docker 日志证据，没有收到 Basic Auth 401；真实 Firing 事件的诊断最终进入 Completed 并保存 5 项证据，测试敏感值未进入持久化内容。测试栈使用临时值和独立数据卷，不涉及生产部署。

2026-07-19 已完成生产金丝雀全闭环：停止 canary 后形成 Firing 和钉钉异常卡；Agent 经 Caddy 完成取证且无 401；双端脱敏后 `fake-secret` 持久化计数为 0、`[REDACTED]` 为 100；诊断进入 Completed 并生成 4 条带证据引用的事实；重启 canary 后进入 Resolved 并收到钉钉恢复卡。本批安全边界全部获得生产实证，M3 因产品化和剩余范围仍保持进行中。

### 产品化首批实现（2026-07-19）

- Agent Docker 身份不再依赖容器 ID：Compose 使用 project/service/副本号，普通容器使用容器名；超长值使用确定性摘要。
- 新增本地 `AGENT_EVIDENCE_POLICY`，只有安装时明确选择 `docker_logs` 才自动为已发现容器生成有限日志能力，旧 Agent 升级默认关闭。
- Agent 上报来源与稳定服务键关联但不上传真实容器目标；控制平面新增独立关联表和兼容增量迁移。
- 控制平面在身份首次切换时迁移活动 M2 事件和既有 M3 映射，保持告警、恢复通知和诊断链路连续。
- 机器详情页可查看 Agent 已授权的 Docker 诊断候选项，并通过服务端管理令牌代理确认映射；浏览器不持有管理令牌。
- 手工 `AGENT_EVIDENCE_SOURCES_JSON` 和原 `service-mappings` API 继续兼容，不影响已验证的金丝雀路径。

隔离集成验证使用真实 PostgreSQL、API、Agent 和 Docker Compose：自动发现生成 8 个稳定 Docker 身份及日志来源，Web 所需候选 API 完成映射且不暴露目标；容器重启后稳定键和映射保持不变；旧容器 ID 下的真实 Firing 与服务映射切换到稳定键后，事件正确 Resolved 且映射继续有效。临时项目、凭据和数据卷已清理。

2026-07-19 v0.3.1 产品化金丝雀（自动发现模式）在生产 control-plane 宿主机跑通全闭环：控制平面升级到 `7ce516e`；control-plane Agent 保留身份升级到 `v0.3.1` 并以 `--evidence-policy docker-logs` 开启自动发现。Agent 自动发现 compose 栈 5 个容器，稳定 `service_key` 为 `compose:vps-agent-console:<service>:1`，`agent_evidence_sources` 与 `agent_evidence_source_bindings` 均无 target 列。浏览器在机器详情页确认 `m3-auto-canary` 候选即建立映射，无需手填 source_key、容器 ID 或 JSON，也不手敲映射 API。停止 canary 进入 Firing 后触发诊断进入 Completed，证据请求经 Caddy 无 401，docker_logs 证据中 `fake-secret` 计数为 0、`[REDACTED]` 为 97，双端脱敏生效。同名重建 canary（新容器 ID）后 `service_key` 与映射不变，第二次诊断仍 Completed，稳定身份跨重建存活。清理后 control-plane 回到纯自动发现（手工白名单置空），DB 孤儿映射与事件已清，4 台 Agent 持续在线；控制平面每上报周期 reconcile `agent_evidence_sources` 与 `service_statuses`，Agent 停止声明的来源与状态自动清除。M3 因 GitHub App、systemd journal 和新可用性事件生产验收未做仍保持进行中。

### Agent 失联与恢复首批实现（2026-07-19）

- API 生命周期内新增控制平面维护循环，默认每 30 秒检查一次 `last_seen_at`；超过 90 秒未上报时创建机器级 Firing，Agent 下一次合法报告在刷新心跳前将同一事件转为 Resolved。API 启动先等待一个完整失联阈值，避免把控制平面自身停机误报成整批 VPS 失联。
- 机器事件复用 M2 `AlertEvent`、活动指纹、确认/静默、`NotificationDelivery` 和钉钉序号；失联和恢复分别为 sequence 1/2，重复巡检不重复通知。
- 巡检使用 Agent 行锁和 `SKIP LOCKED`，恢复报告也先锁定同一 Agent，避免多 API 实例或巡检/恢复竞争生成重复活动事件。
- 独立维护循环会同时扫描待发送、失败和陈旧 Sending 通知，因此机器全部失联时仍能产生告警，并补齐原先依赖后续 Agent 报告触发通知重试的可靠性缺口。
- Agent 事件可从现有事件页手动发起诊断，不要求服务映射，也不向离线 Agent 发请求；证据只包含控制平面已保存的告警、最后心跳、Agent 元数据、最后资源快照和最多 128 条服务状态。
- 新增 `AGENT_AVAILABILITY_SCAN_INTERVAL_SECONDS`，必须不大于 `AGENT_OFFLINE_AFTER_SECONDS`；不新增数据库表或迁移，兼容现有 M1/M2/M3 数据。

隔离 PostgreSQL 事务验证并发执行两次失联巡检，仅生成 1 个活动事件和 1 条 Firing 投递；机器级诊断直接进入 Completed 并保存控制平面证据；随后通过真实报告路径恢复为同一事件的 Resolved，投递序列严格为 Firing 1、Resolved 2。临时容器和数据卷已清理，尚未部署或生产验收。

### 当前产品化缺口与下一批顺序

- 当前 Web 流程只支持逐个确认 Docker 服务；批量确认、自动推断部署目录/仓库和 systemd 日志仍未实现。现有手工配置暂时保留为兼容与故障排查入口。
- 新稳定身份和 Web 映射流程已在 control-plane 生产金丝雀实证：容器重建后稳定键与映射不断。尚未直接实证两项：旧 Agent 不带 `AGENT_EVIDENCE_POLICY` 升级仍保持 `disabled`（安装器默认值保证，DMIT/腾讯未实机升级）；容器 ID->稳定键的 M2 事件/M3 映射迁移（金丝雀用新容器名、旧孤儿容器已删无迁移目标，仅隔离验证覆盖）。向更多 VPS 推广前应补这两项实机验证。
- 自动发现不能取消权限边界：控制平面仍只能引用 Agent 已声明的受限能力，文件路径、日志窗口、字节数、持续时间和超时继续由 Agent 与控制平面双重校验。
- Agent 失联/恢复事件已完成本地实现和隔离 PostgreSQL 验证，下一步先做生产金丝雀，再实现 GitHub App 最小仓库版本读取。systemd/file 日志、自动诊断调度、完整仓库同步和诊断体验增强仍不进入首条闭环。

### 已确认的终局产品方向（2026-07-19）

- 每台 VPS 通过一条安装命令完成 Agent 安装、注册和能力策略绑定；用户不需要逐台编辑证据源 JSON。
- Agent 自动发现服务和运行现场，控制台负责确认业务语义、仓库、部署方式和权限档位。
- 自然语言是最终主要操作入口，但不直接变成自由 Shell：系统生成结构化计划，按风险自动执行或请求确认，再进行验证和审计。
- 重启、拉取、部署、回滚等写操作由 M4 的签名任务、能力策略和 Runbook 承载；M5 把这些能力接入全局和上下文对话。
- 高风险通用命令仅作为后期、限时、限定机器且可审计的人工兜底能力；不存在授予模型永久无限 Root 权限的模式。
- 密钥隔离由工具和权限层强制执行。GitHub 写操作留在控制平面，通过明确授权的 GitHub App 创建分支、提交或 PR，VPS Agent 不保存长期仓库写凭据。

## 6. 文档维护规则

- 架构或协议发生变化时更新 `ARCHITECTURE.md`。
- 每个里程碑开始和完成时更新本文件。
- 范围、状态或验收条件变化时更新 `ROADMAP.md`。
- 原始项目计划书作为产品基线保留，不用实际进度覆盖原文。
