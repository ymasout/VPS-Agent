# M6.3 通知、模板与引导式配置设计

当前状态：**M6.3a 已由 codex 实现、Claude 审计通过（无 P0/P1/P2），提交 `19e829b` 推送至 main，并于 2026-07-28 通过生产金丝雀（秘密不回显、ops/trans 14/89 不变）。M6.3 整体未完成（M6.3b 测试消息/M6.3c 第二通道/M6.3d 模板版本待开始）。**

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
- **通知轰炸：**测试消息不能作为无审计 POST 直接加入首片；后续必须显式触发、限速、幂等并记录有限审计摘要。
- **模板注入：**事件标题、目标、详情继续视为不可信文本并转义；模型和仓库内容不能定义模板或收件人。
- **错误就绪：**生产控制台链接不是 HTTPS 时返回稳定问题码；未配置 Webhook 时 `ready=false`。可选加签不被误判为必需。
- **权限扩大：**通知只消费既有 AlertEvent/Delivery，不创建、确认或执行 Operation。

## 5. API / Web / Agent 职责

- API 管理端点 `GET /api/v1/notification-configuration`：要求管理令牌，只返回秘密不敏感的就绪状态、固定模板目录和交付参数。
- Web `/settings/notifications`：服务端代持管理令牌读取状态；页面只展示布尔状态、变量名和现有部署流程说明。
- Agent 不感知通知通道、凭据或模板，继续只出站上报事实并领取已签名任务。

## 6. 阶段顺序

1. **M6.3a（当前）：**通知就绪状态、固定模板目录、引导配置页；只读、无迁移、无外部副作用。
2. **M6.3b：**显式测试消息；先设计幂等、限速、审计摘要、超时和失败呈现，不复用生产 AlertEvent 伪造故障。
3. **M6.3c：**第二通知通道；统一适配器、每通道独立 Delivery、配置校验与真实失败重试门。
4. **M6.3d：**受限模板版本与通道选择；只允许服务端定义字段和安全渲染，不开放任意模板代码。

## 7. 测试矩阵

- API：未认证拒绝；配置/未配置；响应不含 Webhook、token、secret；固定 4 模板；HTTPS 问题码；现有钉钉 payload、签名、失败和陈旧发送重试回归。
- Web：管理令牌仅服务端使用；页面无凭据输入、POST、测试发送或 Operation 路由；test/lint/build 通过。
- 项目：Ruff、API 全量、Web 全量、Compose 配置、Alembic 单 head；M6.3a 预期 head 仍为 `0017_m5_runbook_drafts`。

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
