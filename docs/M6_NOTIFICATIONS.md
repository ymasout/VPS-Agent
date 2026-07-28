# M6.3 通知、模板与引导式配置设计

当前状态：**M6.3a 已由 codex 实现、Claude 审计通过（无 P0/P1/P2），提交 `19e829b` 推送至 main，并于 2026-07-28 通过生产金丝雀（秘密不回显、ops/trans 14/89 不变）。M6.3b 已完成本地实现，尚待独立审计、真实 PostgreSQL CI、提交和生产验证；M6.3 整体未完成。**

## 1. 当前基线

- M2 已有钉钉自定义机器人通道，支持服务异常/恢复与 VPS 失联/恢复。
- `notification_deliveries` 以 `(event_id, sequence, channel)` 去重；待发送、失败和陈旧 `sending` 可重试，单条最多尝试 3 次。
- Webhook 与可选加签密钥只由环境变量注入 API；Web 和 Agent 不持有通知凭据。
- 当前告警建单仍硬编码 `dingtalk`，没有第二通道、模板版本、测试消息审计或 Web 配置入口。

## 2. 目标

1. 让管理员在不读取秘密值的前提下判断通知链是否具备发送条件。
2. 把现有服务/VPS firing/resolved 固定模板形成可检查目录，继续转义所有不可信事件文本。
3. 提供只说明变量名和部署步骤的引导式配置，不把凭据送入浏览器或数据库。
4. 后续在同一交付语义上增加显式测试消息和第二通道，不复制事件状态机。

## 3. 非目标

- M6.3a 不发送测试消息，不新增外部副作用，不允许页面修改运行时配置。
- 不把 Webhook、令牌、加签密钥、其长度、前后缀或主机名回显给 Web。
- 不新增迁移、Agent 协议、Operation、Provider 工具、自然语言通知发送或 M4 写权限。
- 不实现用户自定义任意模板、任意 URL Webhook、群发、定时营销或通知中的确认按钮。
- 不在首片增加邮件、Telegram、Slack 等第二通道。

## 4. 威胁模型与安全边界

- **秘密泄露：**状态 API 只返回布尔就绪信息、稳定问题码和非敏感重试参数；Web 页面无秘密输入框。
- **SSRF/任意出站：**M6.3a 不接收 URL，也不发请求；后续通道 URL 必须由服务端配置和适配器白名单决定。
- **通知轰炸：**M6.3b 测试消息必须显式触发、默认关闭、限速、幂等并记录有限审计摘要；不得提供无审计发送入口。
- **模板注入：**事件标题、目标、详情继续视为不可信文本并转义；模型和仓库内容不能定义模板或收件人。
- **错误就绪：**生产控制台链接不是 HTTPS 时返回稳定问题码；未配置 Webhook 时 `ready=false`。可选加签不被误判为必需。
- **权限扩大：**通知只消费既有 AlertEvent/Delivery，不创建、确认或执行 Operation。

## 5. API / Web / Agent 职责

- API 管理端点 `GET /api/v1/notification-configuration`：要求管理令牌，只返回秘密不敏感的就绪状态、固定模板目录和交付参数。
- Web `/settings/notifications`：服务端代持管理令牌读取状态；页面只展示布尔状态、变量名和现有部署流程说明。
- Agent 不感知通知通道、凭据或模板，继续只出站上报事实并领取已签名任务。

## 6. 阶段顺序

1. **M6.3a（已完成）：**通知就绪状态、固定模板目录、引导配置页；只读、无迁移、无外部副作用。
2. **M6.3b（当前）：**显式测试消息；固定钉钉通道和服务端模板、默认关闭、请求 UUID 幂等、数据库固定窗口限速、一次发送、有限审计；不复用生产 AlertEvent 伪造故障。
3. **M6.3c：**第二通知通道；统一适配器、每通道独立 Delivery、配置校验与真实失败重试门。
4. **M6.3d：**受限模板版本与通道选择；只允许服务端定义字段和安全渲染，不开放任意模板代码。

## 7. 测试矩阵

- API：未认证拒绝；配置/未配置；响应不含 Webhook、token、secret；固定 4 模板；HTTPS 问题码；现有钉钉 payload、签名、失败和陈旧发送重试回归。
- M6.3a Web：管理令牌仅服务端使用；页面无凭据输入或 Operation 路由；test/lint/build 通过。
- 项目：Ruff、API 全量、Web 全量、Compose 配置、Alembic 单 head；M6.3a 预期 head 仍为 `0017_m5_runbook_drafts`。
- M6.3b：默认关闭、未配置通道、相同幂等键重放、同窗口不同键 429 + `Retry-After`、并发唯一约束、最多一次发送、确定失败、发送中崩溃后 `delivery_outcome_unknown` 且不重发、秘密扫描和固定空请求正文。

## 8. 生产金丝雀边界

需用户另行授权后才执行：部署目标 commit，核对 `/api/v1/system-info` 构建身份；用管理认证读取通知配置状态；确认 `/healthz` 仍最小；页面和 HTML/日志不含 Webhook/secret；不制造生产告警、不发送测试消息、不改现有通知或 M5 开关，Operation/Transition 计数保持不变。

## 9. M6.3a 本地验证（2026-07-28）

- API 216 项通过、9 项真实 PostgreSQL 门控跳过；Ruff 通过。
- Web 84 项通过，ESLint 与 Next.js production build 通过；`/settings/notifications` 为动态服务端路由。
- Agent 全部 Go 包 test/vet 通过；Compose production 配置解析通过；Alembic 保持单 head `0017_m5_runbook_drafts`。
- 本机 Docker Desktop daemon 未运行，不能本地执行最终 Web 镜像门；提交后仍须由既有 `Control Plane Web` CI 真实构建/启动 standalone 镜像并验证页面，再考虑生产金丝雀。
- `git diff --check` 通过。已提交 `19e829b` 推送至 main，三个 CI 全绿；生产金丝雀见 §11。

## 10. M6.3 完成定义

- M6.3a–M6.3d 的最终选定范围均有测试、独立审计和经授权生产验证。
- 至少一个新增通道复用可靠 Delivery 语义，测试消息具备限速、幂等和有限审计。
- 配置和模板不泄露秘密，不接受模型生成的收件人/URL/可执行内容。
- README、ROADMAP、PROJECT_STATUS、ARCHITECTURE 与本文状态同步；未完成前不得标记 M6.3 完成。

## 11. 生产金丝雀记录（2026-07-28）

M6.3a 生产金丝雀在用户明确授权下执行并通过：

- 部署 `fa35eee -> 19e829b`（注入 build identity），`preflight`（原子备份包）+ `migrate`（no-op，head 仍 `0017`）+ `up -d` + `postflight` 全通过；三个 CI（Recovery/Migrations/Web）全绿。
- `/api/v1/system-info` 返回 `commit_sha=19e829b83355e477fa2873389c5ca833d3721edf`、`schema_current=true`。
- `GET /api/v1/notification-configuration`（受管理认证）返回 `ready=true`、`channels=[dingtalk configured+signing_enabled]`、4 模板、`issues=[]`；未带 admin token -> 401。
- 秘密不泄露：API 响应与 `/settings/notifications` 页面 HTML 均不含 webhook URL/access_token/secret（grep `access_token|oapi.dingtalk|webhook/send` 无命中；页面无 `<input>/<form>`）。
- 零副作用：生产 ops/trans 前后 `14/89` 不变（只读，无测试发送/外部消息）。
- M6.3a 无 feature flag（只读 always-on），`19e829b` 留作运行基线；M6.3 整体未完成。

## 12. M6.3b 测试消息设计

### 12.1 数据与审计

- 新迁移 `0018_m6_notification_tests` 增加独立 `notification_test_requests`，不伪造 `AlertEvent`，也不复用生产 `NotificationDelivery`。
- 审计只保存组织、固定通道、客户端请求 UUID、限速窗口、状态、尝试次数、固定 actor、稳定错误码和时间；不保存 Webhook、secret、远端响应正文或任意消息正文。
- 状态限定为 `pending → sending → succeeded|failed|delivery_outcome_unknown`；超时、网络中断、无效响应或 API 在发送后落审计前中断都视为结果未知，绝不自动重发。只有明确 HTTP/DingTalk 拒绝才记为 `failed`。`attempt_count` 数据库约束为 0–1。

### 12.2 权限、幂等与限速

- `POST /api/v1/notification-tests/dingtalk` 受管理认证保护，只接受严格 UUID `Idempotency-Key`，请求正文为空；通道、收件目标和消息模板均由服务端固定。
- `NOTIFICATION_TESTS_ENABLED=false` 默认关闭；关闭或通道未配置时失败关闭。关闭后遗留 `pending` 会记为 `notification_tests_disabled`，不会在未来意外发送。
- `(organization_id, channel, client_request_id)` 唯一保证重放返回同一审计记录且不再次发送；`(organization_id, channel, rate_limit_window)` 唯一保证数据库并发下每个固定窗口最多接受一条新测试。
- 首版窗口由 `NOTIFICATION_TEST_COOLDOWN_SECONDS` 控制，默认 60 秒、允许 30–3600 秒；触发限速返回 429 和有限 `Retry-After`。

### 12.3 Web 与消息边界

- `/settings/notifications` 展示最近 10 条有限审计；测试按钮仅在通道已配置、功能已开启、用户显式勾选且浏览器在线时可用。
- Web 同源代理拒绝跨源请求、非法 UUID 和任何请求正文；管理令牌仍只在服务端转发。
- 测试消息只含固定说明和服务端审计 ID，不含事件、机器、仓库、诊断、Operation、凭据或用户输入；不 @ 全体，不带确认按钮。

### 12.4 回退与生产金丝雀边界

- 应用回退可保留 `0018` 表；旧应用不会读取该独立表，禁止仅为应用回退而 downgrade 或删除审计。M6.3b 不修改 Agent/M4/Operation 状态机。
- 金丝雀必须先以功能关闭部署并验证 403，再经用户授权临时开启：创建一条测试、确认钉钉只收到一条、审计达到 `succeeded/attempt_count=1`；重放同一幂等键不得再发，窗口内新键必须 429。随后将功能还原关闭，并确认 ops/trans、告警事件和生产通知投递均无非预期变化。
- 任何金丝雀输出不得打印签名后的钉钉 URL、access token、secret 或远端响应正文。

## 13. M6.3b 本地实现与风险审计（2026-07-28）

### 13.1 本地验证

- API 全量 `227 passed, 10 skipped`，Ruff 通过；跳过项包含需显式提供隔离数据库的真实 PostgreSQL 门。
- Web 全量 87 项、ESLint 与 Next.js production build 通过；构建产物包含通知测试 POST/轮询代理和动态通知设置页。
- Alembic 保持单 head `0018_m6_notification_tests`；`0017 → 0018` upgrade 与 `0018 → 0017` downgrade 均可生成离线 SQL。迁移 CI 新增双向离线 SQL、`0018 → 0017 → head` 在线回退/重升和真实 PostgreSQL 幂等、限速、零 Operation 副作用验证。
- Agent 无代码或协议变化；既有 Go test/vet 通过。生产 Compose 配置可解析，功能开关默认 `false`。
- 本机 Docker daemon 未运行，因此真实 PostgreSQL 门和最终容器镜像门尚未在本地执行；它们是提交后的 CI 与独立审计硬门，不能由 SQLite/Mock 结果替代。

### 13.2 P0 / P1 / P2

- **P0：无已知开放项。** API/Web/Provider/Agent 均不能提供任意 URL、收件人或消息正文；功能默认关闭，且不会创建 AlertEvent 或 Operation。
- **P1 验证门：**真实 PostgreSQL 必须证明两项唯一约束在并发下分别保持幂等和单窗口一条；迁移 downgrade/re-upgrade、schema check 与既有数据保留必须在 CI 全过后才可进入提交后审计/生产候选。
- **P1 语义门：**超时、网络错误、无效响应和发送中崩溃只能终止为 `delivery_outcome_unknown`，不得自动重发；金丝雀也不得用新幂等键“补发”未知结果。
- **P2 固定窗口边界：**管理员可在相邻窗口边界各触发一条，形成短时两条消息；首片接受该有界行为，金丝雀避开窗口边界，后续若需要再评估滑动窗口，不通过缩短冷却规避。
- **P2 审计保留：**首片不自动删除 `notification_test_requests`；记录字段固定且不含消息正文/秘密，但长期保留与清理策略需在自托管运维规范中单独定义。
- **P2 Web 在线状态：**`navigator.onLine` 和显式勾选仅是 UX 防误触；真正的安全门始终是服务端管理认证、默认关闭、空正文、UUID 幂等、数据库限速和固定模板。

### 13.3 当前结论

M6.3a 文档收尾已复核并修正历史缺口措辞。M6.3b 本地实现与普通回归完成，但尚未独立审计、提交、推送或生产验证；生产仍运行 `19e829b` 与 schema `0017_m5_runbook_drafts`，不得提前标记 M6.3b 或 M6.3 完成。
