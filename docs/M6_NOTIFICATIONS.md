# M6.3 通知、模板与引导式配置设计

当前状态：**M6.3a/b/c+d 均已完成审计、CI 与生产金丝雀。M6.3c+d 提交 `ece22d5`+`1073969`（P0 revision 长度超 varchar(32) 已修复），三个 CI 全绿，2026-07-29 通过生产金丝雀（迁移 0019 + 多通道视图 + backfill + 零副作用；telegram 实发留待启用时验证，CI 已覆盖适配器）。M6.3 完成。**

## 1. 当前基线

- M2 已有钉钉自定义机器人通道，支持服务异常/恢复与 VPS 失联/恢复。
- `notification_deliveries` 以 `(event_id, sequence, channel)` 去重；待发送、失败和陈旧 `sending` 可重试，单条最多尝试 3 次。
- Webhook 与可选加签密钥只由环境变量注入 API；Web 和 Agent 不持有通知凭据。
- 生产当前运行 `1073969 + 0019_m6_multichannel_notify`，告警通道选择仍为 `dingtalk`；M6.3c+d 已消除代码中的硬编码单通道，M6.3b 测试审计和 Web 配置入口均保留。

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
2. **M6.3b（已完成）：**显式测试消息；固定钉钉通道和服务端模板、默认关闭、请求 UUID 幂等、数据库固定窗口限速、一次发送、有限审计；不复用生产 AlertEvent 伪造故障。
3. **M6.3c（已完成）：**Telegram 第二通知通道；适配器注册表、每通道独立 Delivery、配置校验和真实失败隔离门；飞书只保留不可启用的注册/测试位。
4. **M6.3d（已完成）：**受限模板 `v1`、通道白名单组合和冻结渲染上下文；只允许服务端定义字段和安全渲染，不开放任意模板代码。

## 7. 测试矩阵

- API：未认证拒绝；配置/未配置；响应不含 Webhook、token、secret；固定 4 模板；HTTPS 问题码；现有钉钉 payload、签名、失败和陈旧发送重试回归。
- M6.3a Web：管理令牌仅服务端使用；页面无凭据输入或 Operation 路由；test/lint/build 通过。
- 项目：Ruff、API 全量、Web 全量、Compose 配置、Alembic 单 head；M6.3a 预期 head 仍为 `0017_m5_runbook_drafts`。
- M6.3b：默认关闭、未配置通道、相同幂等键重放、同窗口不同键 429 + `Retry-After`、并发唯一约束、最多一次发送、确定失败、发送中崩溃后 `delivery_outcome_unknown` 且不重发、秘密扫描和固定空请求正文。

## 8. 生产金丝雀边界

M6.3a 的历史金丝雀边界是只读且不发送测试消息。M6.3c+d 已按 §15.4 的安全默认边界完成生产验证；未配置或启用 Telegram，也未制造生产 AlertEvent。未来启用 Telegram 仍是管理员单独授权的配置事件，不得把凭据发送到聊天、日志或工单。

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
- M6.3a 无 feature flag（只读 always-on），`19e829b` 留作运行基线。M6.3c+d 生产金丝雀通过 2026-07-29（§15.4）；M6.3 完成。

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

M6.3a 文档收尾已复核并修正历史缺口措辞。M6.3b 已由 codex 实现、Claude 审计通过（无 P0/P1；P2-1 迁移 downgrade offline 守卫已修复+验证），提交 `a4944fb` 推送至 main，三个 CI 全绿，并于 2026-07-28 通过两阶段生产金丝雀（见 §14）；生产现运行 `a4944fb` 与 schema `0018_m6_notification_tests`。该段记录的是 M6.3b 收尾时点，当时 M6.3c 第二通道与 M6.3d 模板版本尚未开始；当前进度以文首和 §15 为准。

## 14. M6.3b 生产金丝雀记录（2026-07-28）

两阶段金丝雀在用户明确授权下执行并通过：

- **Phase A（功能关闭）**：部署 `a4944fb` + 迁移 `0017 -> 0018`（建 `notification_test_requests` 表）+ postflight 通过；`/api/v1/system-info` commit=a4944fb、revision=0018、schema_current=true；`/api/v1/notification-configuration` test_messages_enabled=false；测试端点 403；ops/trans 14/89 不变；`notification_test_requests` 表空。
- **Phase B（临时开启 + 发一条测试 + 还原）**：开启 `NOTIFICATION_TESTS_ENABLED=true`；POST 测试 -> 202 + id=dcae38ab -> 轮询 `succeeded/attempt_count=1`（钉钉群收到 1 条“✅ VPS Agent 通知测试”）；同 Idempotency-Key 重放 -> 200（不重发，无新消息）；新 KEY 同窗口 -> 429（被拦截，不入库）；还原关闭 -> 403。
- **P2 固定窗口边界**：因对话往返延迟，KEY1/2/3 跨分钟落不同窗口（16:10/16:12/16:16）各 202，符合设计 §13.2 P2 接受的相邻窗口边界行为；KEY4/KEY5 背靠背同窗口 -> key4 202 + key5 429，验证限速。
- **零副作用**：ops/trans 前后 14/89 不变（测试不创建 Operation）；`notification_test_requests` 4 条 succeeded（KEY5 被 429 拦截不入库）；不污染 AlertEvent/NotificationDelivery。
- M6.3b 功能已还原关闭（`NOTIFICATION_TESTS_ENABLED=false`），`a4944fb` 留作运行基线。

## 15. M6.3c+d 多通道与版本化模板设计（2026-07-29）

### 15.1 通道、秘密与组合边界

- `NOTIFICATION_CHANNELS` 默认 `dingtalk`，只接受内置且已实现的 `dingtalk`、`telegram` 及无重复组合；空值、未知值和 `feishu` 都由 Settings 校验拒绝。飞书已进入通道目录但 `implemented=false`，且发送适配器注册表中没有飞书入口。
- Telegram 只接受 API 容器环境中的 `TELEGRAM_BOT_TOKEN` 与 `TELEGRAM_CHAT_ID`；API origin 固定为 `https://api.telegram.org`，请求、Web 或模型不能覆盖。配置 API 只返回 implemented/enabled/configured 布尔值，绝不返回 token、chat ID、Webhook 或其片段。
- 通道选择在 AlertEvent 创建时冻结并贯穿 firing/resolved 生命周期，避免中途启用产生“只恢复未告警”或中途禁用造成“告警后无恢复”；既有 Delivery 也保留创建时的通道意图。移除相应凭据可停止该通道扫描，恢复凭据前不会发送；不得通过 Web 或自然语言动态修改通道和秘密。
- 生产通知和测试通知均只保存稳定错误码。HTTP 异常、签名 URL、Telegram token URL、远端 `errmsg/description` 不进入数据库、备份或应用日志。

### 15.2 Delivery 与模板冻结

- 新迁移 `0019_m6_multichannel_notify` 为 `alert_events` 增加冻结通道集合，为 `notification_deliveries` 增加非空 `template_key`、`template_version` 和有限 JSON `render_context`，并把测试审计通道约束扩大为 `dingtalk|telegram`。
- 同一 firing/resolved 逻辑转换只递增一次 `AlertEvent.notification_sequence`，随后为每个选定通道创建相同 sequence、相同模板版本、独立状态/尝试次数的 Delivery；一个通道失败不得修改另一通道。
- 当前目录只有服务/VPS firing/resolved 四类 `v1` 模板。创建 Delivery 时冻结标题、详情、来源、机器与服务键；重试继续使用冻结上下文，不读取后来变化的事件文本。模板 key/version/type/target 任一不匹配都失败关闭。
- 历史 Delivery 在 `0018 → 0019` 迁移中从对应 AlertEvent 回填 `v1` 与有限上下文。旧版应用内置的 schema head 是 `0018`，不会在 `0019` 数据库上静默启动；`0019 → 0018` downgrade 若存在 Telegram 测试审计、未终结的非钉钉 Delivery，或仍冻结多通道的活跃告警会明确拒绝，不会删除审计或丢弃生命周期意图来强行回退。应用回退与数据库回退仍是管理员单独授权事件。

### 15.3 Telegram 测试与验证矩阵

- `POST /api/v1/notification-tests/telegram` 复用 M6.3b 管理认证、空正文、UUID 幂等、每通道固定窗口限速、最多一次、未知结果不重发和有限审计语义；只有通道已在 `NOTIFICATION_CHANNELS` 中显式启用且凭据完整时才能创建，通道目标完全由服务器配置决定。
- 单元验证覆盖：钉钉/Telegram 适配器注册完整、飞书不能启用、组合去重/未知通道拒绝、同 sequence 两条 Delivery、冻结上下文、HTML 转义、固定 Telegram origin、远端错误脱敏、每通道测试路由与 Web 同源代理。
- 真实 PostgreSQL CI 门覆盖：同事件钉钉失败与 Telegram 成功相互隔离、两条 Delivery sequence 一致、冻结上下文落库、Operation/Transition 零副作用，以及 Telegram 测试审计能够通过扩展后的约束并达到 succeeded/attempt_count=1。
- 首次提交 `ece22d5` 后，真实 PostgreSQL Migrations/Recovery CI 发现原 revision 名超过 Alembic `version_num VARCHAR(32)` 限制；离线 SQL 只生成文本，未能发现真实写入失败。现已把 revision 缩短为 `0019_m6_multichannel_notify`，并新增遍历全部迁移、强制 revision 长度不超过 32 的本地回归门。
- 修复后本地结果：API `238 passed, 11 skipped`，Web 88 项、Ruff、ESLint、Next.js production build、Agent Go test/vet、Compose 配置和 `0018 ↔ 0019` 双向离线 SQL 通过；Alembic 单 head `0019_m6_multichannel_notify`。revision 长度门已显式加入 Migrations workflow；修复提交 `1073969` 及文档提交 `5cd7bd9` 的 Migrations、Recovery、Web CI 均已转绿。

### 15.4 生产金丝雀计划与实际记录

1. 先以 `NOTIFICATION_CHANNELS=dingtalk`、`NOTIFICATION_TESTS_ENABLED=false` 部署和迁移，核对 system-info commit/revision、schema current、配置 API 三通道目录、`/healthz` 最小响应，以及既有 ops/trans/AlertEvent/Delivery 计数。
2. 用户在服务器本地配置 Telegram token/chat ID；不得在聊天或命令输出中展示。先保持通道选择仍为 dingtalk，确认 API 只报告 Telegram configured，不产生发送。
3. 经再次授权改为 `NOTIFICATION_CHANNELS=dingtalk,telegram` 并临时开启测试消息；只向 Telegram 创建一条审计测试，核对 202→succeeded/attempt_count=1、群内恰好一条、同键重放 200 不重发、同窗口新键 429。
4. 不通过伪造生产告警测试 Delivery；多通道失败隔离由真实 PostgreSQL CI 证明。金丝雀结束后恢复 `NOTIFICATION_TESTS_ENABLED=false`；是否保留 Telegram 启用和凭据由用户明确决定，默认回到仅钉钉。
5. 核对 ops/trans、AlertEvent 与生产 NotificationDelivery 无非预期变化，API/页面/日志/数据库审计均不含 Webhook、token、chat ID、签名 URL 或远端响应正文。通过前不得标记 M6.3 完成。

实际执行于 2026-07-29 完成：部署 `1073969`、迁移 `0018 → 0019` 和 postflight 全部通过；`system-info` 返回 commit `1073969`、revision `0019_m6_multichannel_notify`、`schema_current=true`。配置视图显示钉钉已实现/启用/配置，Telegram 已实现但未启用，飞书未实现；生产继续保持 `NOTIFICATION_CHANNELS=dingtalk` 与 `NOTIFICATION_TESTS_ENABLED=false`。既有 17 条 Delivery 与 25 条 AlertEvent 均完成模板字段和 `["dingtalk"]` 通道集合回填，ops/trans 保持 `14/89`。本次没有配置 Telegram 凭据、没有外部 Telegram 实发，也没有伪造生产告警；Telegram 适配器、测试审计和双通道失败隔离由真实 PostgreSQL CI 覆盖。该限制必须与“金丝雀通过”一并保留，不能把它描述为 Telegram 生产实发证明。
