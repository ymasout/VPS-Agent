# 项目状态

最后同步：2026-07-15
当前阶段：**M0、M1 已完成；M2 进行中**

## 1. 当前结论

项目已完成工程骨架和“机器可见”里程碑。生产控制平面通过 Caddy/HTTPS 运行，Agent 使用一次性令牌注册、独立凭证认证和主动出站 HTTPS 上报。

当前共有 4 条真实 VPS 机器记录：3 台外部 VPS 和控制平面宿主机均已通过 Release 安装器运行 Agent `v0.2.4`，全部在线并持续上报。升级过程保留了原 Agent 身份，没有创建重复机器。M1 的“至少 3 台真实或测试 VPS 稳定接入”验收线已经满足。

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
| DMIT VPS | 外部被管主机 | 在线，Agent `v0.2.4` |
| 腾讯云硅谷 VPS | 外部被管主机 | 在线，Agent `v0.2.4` |
| Tencent-VPS-Hermes | 国内外部被管主机 | 在线，已通过同域中转安装 Agent `v0.2.4` |
| control-plane | 控制平面宿主机自监控 | 在线，已保留身份升级到 Agent `v0.2.4` |

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

状态：**进行中**

首个通知通道由原计划中的 Telegram 调整为钉钉自定义机器人；Telegram 保留为后续通知适配器。当前已完成第一批控制平面能力：

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

随后使用启用加签的专用钉钉测试机器人完成真实链路验收：连续异常只发送一次 Firing，服务恢复只发送一次 Resolved，两条投递均由钉钉接口成功接收。生产 VPS 部署和生产群配置仍待后续验收。

### 已知限制

- 通知失败重试目前没有指数退避，最多尝试三次，并且仍由后续 Agent 上报触发；独立调度器属于 M2 后续工作。
- `deliver_notification` 领取投递后先提交 Sending 状态，再发送 HTTP，发送完成后继续修改同一 ORM 对象；该流程明确依赖 `session_factory` 的 `expire_on_commit=False` 配置。
- Docker 上报目前没有结构化退出码或容器运行模式。Agent 会将所有 `exited` 容器标记为 `healthy=false`，因此一次性或 cron 容器正常退出 0 仍可能产生误报；在 Agent 协议增加退出码/期望状态前，不在 API 层解析非结构化详情字符串。
- `active_key` 唯一约束能够阻止重复活动事件，但并发创建同一事件时的 `IntegrityError` 尚未在报告事务内恢复。当前 Go Agent 串行上报，实际风险较低；后续应使用保存点或按 Agent 串行化评估，避免回滚整份报告。

当前仍需完成：

- 在生产 PostgreSQL 上部署 M2，并继续验证真实并发去重风险。
- 在生产部署中验证钉钉异常、重复异常和恢复通知。
- 增加 Agent 失联检测与恢复事件。
- 增加事件中心 Web 页面和安全的服务端操作代理。
- 将失败通知重试从后续 Agent 报告触发扩展为独立调度。
- 为 Docker 服务上报增加退出码和期望运行模式，降低正常一次性容器的误报。
- 验证并发报告下的活动事件冲突处理。

## 5. 文档维护规则

- 架构或协议发生变化时更新 `ARCHITECTURE.md`。
- 每个里程碑开始和完成时更新本文件。
- 范围、状态或验收条件变化时更新 `ROADMAP.md`。
- 原始项目计划书作为产品基线保留，不用实际进度覆盖原文。
