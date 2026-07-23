# M5 诊断与操作会话

本文记录 M5 的会话体验设计、威胁模型、实现边界和分阶段验收。M5.1 已提交推送（`f53eeee`）并以 deterministic Provider 通过生产只读金丝雀（2026-07-23）；真实 HTTP Provider 金丝雀亦通过 2026-07-23（DeepSeek 经临时适配器；已还原 deterministic）。

M5 不替代 M3 的诊断事实，也不新建一条绕过 M4 的执行路径。M3 继续负责有边界的只读取证和结构化诊断；M4 继续唯一负责写操作的计划、确认、Ed25519 签名、Agent 领取、执行、验证和审计。

当前实现增加独立的事件会话、轮次和关系型引用模型，三个控制平面端点、严格的确定性/HTTP JSON Provider、事件页非流式会话区以及陈旧轮次回收。实现只读取当前事件既有控制平面记录，不创建 Operation、不领取 Agent 任务、不访问 VPS，也没有 Provider 工具接口。两轮生产金丝雀均已通过，生产已恢复并保持 deterministic 已知良好状态。

M5.2.1 GitHub 白名单仓库知识检索已经本地完成、默认关闭且尚未生产部署，见 [M5.2_REPOSITORY_KNOWLEDGE.md](./M5.2_REPOSITORY_KNOWLEDGE.md)。

## 1. 当前审计结论

### 1.1 兼容性判断

建议的第一阶段 **M5.1：事件上下文的只读会话基础** 与现有架构兼容，没有阻塞设计或后续实现的问题：

- `AlertEvent` 已提供事件边界，事件页已有稳定深层链接。
- `DiagnosticRun`、`EvidenceItem` 和既有结构化诊断结果可作为只读上下文。
- `Agent`、`ServiceInstance`、`ServiceStatus` 和 `ManagedService` 已能形成事件相关的机器与服务摘要。
- `Operation` 已保存来源事件/诊断、状态、计划、有限结果、验证结果和审计时间线，可生成只读摘要。
- M3 已有确定性 Provider、HTTP JSON Provider、双端脱敏和未知证据引用拒绝，可复用设计和部分基础设施。
- Web 事件页已有诊断历史、证据展示、加载/错误状态和服务端管理令牌代理，可在同一页面增加会话区域。
- M5.1 审计开始时 Alembic 为单一 head `0009_m4_2_rollback`；当前实现 head 已随 M5.2.1 前进至 `0011_m5_repository_citations`。

M5.1 不应直接扩展现有 `DiagnosticRun` 为聊天记录。诊断任务表示一次取证与诊断生命周期；会话需要用户问题、连续历史、Provider 调用状态、上下文快照和每轮引用。把两者混在同一表会模糊状态机、保留策略和引用语义。

### 1.2 现有实现中必须正视的差距

- 仓库 HEAD 与交接一致为 `62c488e`，开始审计时工作区干净；但 `v0.4.2` 是 annotated tag，解引用后指向 `df01ec1`，不是 `116cd47`。`116cd47` 是包含 Agent v0.4.2 执行代码的 M4.2b 实现提交，标签随 M4.2c 收尾落在 `df01ec1`。该差异不影响当前 Fleet 或 M5.1 设计。
- 当前产品固定 `organization_id=local`，部分现有读路由依赖 Caddy/容器网络边界，查询没有逐条显式组织过滤。M5.1 必须从第一天使用显式组织作用域，不能只依赖当前单租户假设。
- `DiagnosticResult` 当前没有全局 `extra="forbid"`；Provider 返回多余字段时可能被忽略。M5.1 的 Provider 输出必须严格拒绝未知字段。
- M3 只验证事实和推断引用的 ID 是否属于本次证据集合；会话还会引用事件、诊断、机器/服务摘要和操作，必须建立新的统一引用清单并逐项校验。
- 当前 M3 Provider 上下文按单项限制，但没有统一的会话总字节预算。M5.1 必须确定性裁剪上下文并记录省略项。
- 当前事件页把事件或诊断读取的任意失败统一转成 404。会话区需要分别展示“不存在”“控制平面不可用”和“Provider 失败”。
- 现有 API 自动测试以单元/模拟会话为主；迁移 CI 使用真实 PostgreSQL。M5.1 必须新增真实 PostgreSQL 的作用域、约束和迁移集成验证，不能只依赖 AsyncMock。

## 2. M5.1 目标与非目标

### 2.1 目标

1. 用户从已有事件页进入该事件唯一的只读会话。
2. 用户提交非空、最多 2000 个 Unicode 字符且 UTF-8 不超过 8 KiB 的问题。
3. 控制平面只组装当前组织、当前事件范围内已有的数据。
4. Provider 返回严格结构化回答，区分事实、推断、建议、未知/缺失信息和证据引用。
5. 每个引用只能从服务端本轮生成的引用清单中选择；引用在落库前再次按事件和组织校验。
6. 保存事件会话和轮次历史，并保留每轮使用的有界上下文清单，便于复现和审计。
7. Provider 超时、HTTP 错误、超大响应、非法 JSON、未知字段、非法引用或输出脱敏失败时受控失败。
8. Web 展示历史、加载、失败、结构化回答和可跳转引用。
9. 测试默认使用确定性 Provider，不依赖真实 AI 服务。

### 2.2 非目标

- 全局 Fleet 对话、机器/服务/仓库抽屉或跨事件搜索。
- 新取日志、领取 Agent 证据请求、访问 VPS、Agent 或 Docker。
- 创建、确认、取消或执行任何 M4 `Operation`。
- 把“修复它”“建议执行”等自然语言解释为写授权。
- 自动修复、自动部署、自动回滚或回滚链。
- GitHub 分支、提交、推送、PR 或其他写操作。
- 整仓同步、向量数据库、复杂 RAG、流式输出、多 Agent 循环或工具编排。
- 自由 Shell、任意命令、任意参数或任意文件系统路径。
- 为 M5 修改 M4 v1/v2 协议、状态机、签名字段、能力策略或验证语义。

## 3. 必须继承的 M4 边界

- 会话 Provider 没有工具接口，也不持有 Agent、Docker、GitHub 或 M4 操作能力。
- 会话模块不得调用 `create_operation`、`confirm_operation`、Agent Claim/Complete 或任何部署/回滚入口。
- M5.1 的“建议”只是文本结果；即使 Provider 返回 `requires_confirmation=false`，也不能产生写授权或执行副作用。
- 后续 M5 写意图只能由控制平面生成独立结构化计划，并完整复用 M4 的预检、确认、Ed25519 签名、有效期、幂等、Agent 本地策略、领取、执行、健康验证和审计。
- M4.2 的同仓库不可变 digest、Compose 允许目录/软链接边界、双基线 config-hash 漂移门、同报告 digest+健康验证、显式回滚和服务端派生回滚目标保持不变。
- Web/API 仍只连接控制平面，不直接连接 VPS 或 Agent。

## 4. 威胁模型

| 威胁 | 可能后果 | M5.1 控制 |
| --- | --- | --- |
| 日志、诊断、操作输出或用户历史中的提示注入 | 诱导模型改变权限、伪造事实或请求工具 | 所有业务文本标记为不可信数据；Provider 无工具；系统约束与数据分层传输；输出仍由服务端校验 |
| 引用伪造 | 回答引用其他事件、其他组织或不存在的记录 | 服务端生成不透明引用 ID；Provider 只能回传该集合；落库前重新查询并校验作用域 |
| IDOR / 组织越权 | 读取其他事件或未来其他组织的数据 | 从受信任管理上下文取得 `organization_id`；所有根查询显式过滤；子资源通过受作用域父记录连接；不匹配统一返回 404 |
| 事件边界逃逸 | 通过问题中的 ID 请求其他事件、诊断或操作 | 问题文本不参与数据库选择；上下文只从路径中的事件服务端派生 |
| 上下文洪泛 | Provider 成本、延迟或内存失控 | 问题、历史、条目数、单项字节数和总字节数均设硬上限；确定性优先级裁剪 |
| 敏感信息泄露 | 密钥、Token、路径或签名材料进入 Provider/日志/UI | 只取允许字段；组装前再次脱敏；不含凭据、签名、nonce、幂等键和原始计划载荷；日志不记录正文 |
| Provider 超时或恶意响应 | 请求挂起、超大内存、非法结果落库 | 连接/总超时、256 KiB 响应上限、严格 JSON schema、未知字段拒绝、受控错误码 |
| 重复提交与并发 | 重复调用 Provider、历史顺序混乱 | 客户端请求 ID + 会话内唯一约束；每会话首版最多一个活动轮次；行锁/唯一约束处理竞争 |
| 上下文与回答竞态 | 引用生成后来源已变化或被撤销 | 每轮保存上下文清单、采集时间和内容摘要；回答引用该轮快照；读取时仍校验源记录存在性并标注历史快照 |
| Provider 文本被当作授权 | 触发 M4 写操作 | M5.1 路由和服务没有 Operation 写依赖；测试断言操作表计数和状态不变 |
| 浏览器跨站请求 | 未经用户意图提交问题 | 复用 Web 服务端代理、同源校验、管理令牌仅在服务端；请求体和事件 ID严格校验 |

## 5. 最小数据模型

M5.1 建议新增迁移 `0010_m5_event_conversation`，使用显式 DDL，不从未来 ORM 动态建表。

### 5.1 `conversation_sessions`

| 字段 | 约束与用途 |
| --- | --- |
| `id` | UUID 字符串主键 |
| `organization_id` | 非空、索引；当前来自管理上下文的 `local`，不由客户端提交 |
| `scope_type` | 首版固定为 `event`，数据库 CHECK |
| `event_id` | 非空外键到 `alert_events.id` |
| `created_by` | 当前为 `local-admin` |
| `created_at` / `updated_at` | UTC 时间 |

首版对 `(organization_id, event_id)` 建唯一约束，使一个事件只有一个连续会话，避免先做会话选择器。未来全局或其他上下文会话应增加明确外键和约束，不使用无法保证引用完整性的任意 `context_id`。

为防止应用错误写出“会话组织与事件组织不一致”的记录，迁移应给 `alert_events` 增加可供引用的 `(id, organization_id)` 唯一约束，并让会话使用 `(event_id, organization_id)` 复合外键；不能只建立单列 `event_id` 外键。轮次同样通过 `(session_id, organization_id)` 复合外键继承会话作用域。

### 5.2 `conversation_turns`

| 字段 | 约束与用途 |
| --- | --- |
| `id` | UUID 字符串主键 |
| `organization_id` | 非空、索引；与会话组织一致 |
| `session_id` | 非空外键到 `conversation_sessions.id` |
| `client_request_id` | 客户端生成 UUID；与 `session_id` 唯一，支持安全重试 |
| `question` | 已脱敏、有界的用户问题；不保存另一个未脱敏副本 |
| `status` | `pending/running/completed/failed` |
| `provider` | 确定性或 HTTP JSON Provider 名称 |
| `answer` | 严格校验后的结构化 JSON；未完成时为空 |
| `context_manifest` | 本轮实际使用的来源类型、记录 ID、采集时间、内容摘要、截断/省略信息；不保存凭据 |
| `error_code` / `error_detail` | 固定错误码和有限安全说明；不保存 Provider 原始正文 |
| `created_at` / `started_at` / `completed_at` | UTC 时间 |

每会话首版只允许一个 `pending/running` 轮次。PostgreSQL 部分唯一索引用于多 API 实例并发保护。

一次轮次同时保存用户问题、Provider 生命周期和回答，比首版拆分任意角色消息更小、更容易保证幂等与失败状态；API 可以把每轮投影成用户消息和助手消息。以后需要工具事件或多参与者时再增加独立消息表。

### 5.3 引用保存

首个实现切片建议同时新增 `conversation_citations`，不要只把引用字符串埋在回答 JSON 中：

- `turn_id`、`section`、`item_index`、`citation_index`。
- `source_type` 固定为 `alert_event`、`diagnostic_run`、`evidence_item`、`agent_summary`、`service_instance_summary` 或 `operation`。
- 对持久资源使用对应的可空外键，并用 CHECK 保证恰好一个目标；Agent/ServiceInstance 摘要同样保存对应外键、本轮内容摘要和生成时间。
- `(turn_id, section, item_index, citation_index)` 唯一。

服务端只根据本轮 `context_manifest` 创建引用行。Provider 不能提交数据库 ID 之外的任意 URL、路径或显示文本。引用删除策略应优先 `RESTRICT`；若未来引入保留期删除，必须保留不可误导的引用墓碑，而不是静默指向别的记录。

## 6. API 协议

### 6.1 读取或创建事件会话

`GET /api/v1/events/{event_id}/conversation`

- 先以 `(organization_id, event_id)` 查询事件；不匹配返回 404。
- 事件存在但尚无会话时返回 200，`session_id=null`、`turns=[]`；404 只表示事件不存在或不属于当前组织。
- 第一次提问时惰性创建会话。已有会话返回会话和按创建时间升序的最近 50 轮；首版不做无限历史。

### 6.2 提交问题

`POST /api/v1/events/{event_id}/conversation/turns`

```json
{
  "client_request_id": "UUID",
  "question": "这个事件目前能确认什么？"
}
```

- 需要管理认证，并经 Web 同源代理调用。
- Pydantic 使用 `extra="forbid"`；问题去除首尾空白后必须非空，最多 2000 字符/8 KiB。
- 问题只描述用户意图，不接受事件 ID、诊断 ID、证据 ID、操作 ID、工具名或执行参数作为可信选择器。
- 服务端惰性创建/读取事件会话，创建 `pending` 轮次并提交事务后再调用 Provider。
- 首次创建返回 202；相同 `client_request_id` 返回原轮次，不重复调用 Provider。
- 同会话已有活动轮次时返回 409，Web 等待该轮完成。

### 6.3 读取单轮

`GET /api/v1/conversation-turns/{turn_id}`

- 必须通过 `conversation_turn -> session -> event` 连接验证当前组织和事件范围。
- 返回状态、结构化回答、引用和安全错误。
- 首版 Web 可按 1–2 秒间隔有界轮询，进入终态后停止；不做流式传输。

所有不存在、跨事件或跨组织资源统一返回 404，避免暴露资源是否存在。

## 7. 上下文组装与脱敏

### 7.1 允许的数据

上下文完全由 URL 中的当前事件服务端派生：

1. 当前 `AlertEvent` 的标题、状态、严重程度、来源、观测次数和时间。
2. 当前事件 `agent_id` 对应的非敏感 `Agent` 摘要：名称、主机名、系统、架构、版本、在线状态和最后心跳。
3. 服务事件按 `(agent_id, service_kind, service_key)` 唯一解析的 `ServiceInstance`、`ManagedService` 和最新 `ServiceStatus` 摘要。
4. 当前事件最近最多 5 个 `DiagnosticRun` 的状态和严格结构化结果。
5. 上述诊断最多 32 个 `EvidenceItem`；按诊断新旧、证据类型优先级、采集时间和 ID 确定性排序。
6. `source_event_id` 等于当前事件，或 `source_diagnostic_id` 属于当前事件诊断的最近最多 20 个 `Operation` 只读摘要。
7. 当前会话最近最多 10 个已完成轮次，且历史总计不超过 32 KiB。

### 7.2 明确排除的数据

- Agent credential、注册令牌、管理令牌、GitHub App 私钥/安装令牌、Webhook Secret。
- Operation 的任务签名、nonce、幂等键、签名 key、Claim 租约和 Agent 本地 target。
- 任意 Compose 路径、任意文件路径、原始 `plan_snapshot`、原始 Transition details 或未截断执行输出。
- 未属于当前事件的诊断、证据、服务、Agent 或操作。
- M5.1 不新增仓库正文；GitHub 白名单检索在后续 M5 阶段设计。

### 7.3 上限与优先级

- Provider 请求的全部不可信正文默认最多 128 KiB。
- 单个证据进入会话上下文前最多 16 KiB；操作摘要最多 4 KiB；单个历史轮次最多 4 KiB。
- 优先级：事件事实 > 当前 Agent/服务摘要 > 最新诊断的已引用证据 > 其他诊断证据 > 操作结果摘要 > 对话历史。
- 超出预算时从最低优先级、最旧项开始删除；不得在 UTF-8 字符中间截断。
- `context_manifest` 记录实际使用、截断和省略数量，回答的“缺失信息”可明确说明上下文不完整。

### 7.4 脱敏与日志

- 用户问题、事件文本、诊断结果、证据、操作输出和历史全部视为不可信文本。
- 进入 Provider 前再次调用控制平面脱敏；Provider 输出在校验前后都执行长度限制和脱敏。
- 用户问题只保存脱敏版本；不在结构化日志中记录问题、上下文、Provider 原始响应或 API Key。
- 日志只记录 `event_id/session_id/turn_id/provider/status/error_code/context_bytes/context_items/duration_ms`。

## 8. 结构化回答与引用规则

Provider 必须返回严格对象，所有模型使用 `extra="forbid"`：

```json
{
  "summary": "简短回答",
  "facts": [
    {"statement": "已确认事实", "citation_ids": ["本轮引用 ID"]}
  ],
  "inferences": [
    {"statement": "推断", "confidence": "medium", "citation_ids": ["本轮引用 ID"]}
  ],
  "recommendations": [
    {
      "action": "建议的下一步",
      "risk": "low",
      "requires_confirmation": true,
      "citation_ids": ["本轮引用 ID"]
    }
  ],
  "missing_evidence": ["仍缺少的信息"]
}
```

规则：

- 每条事实和推断至少一个引用；建议如声称基于当前情况，也必须至少一个引用。
- Provider 只能返回本轮引用清单中的不透明 `citation_id`；未知、重复异常、跨作用域或类型不匹配引用使整轮受控失败，不做部分接受。
- 引用 ID 不直接授予读取能力。服务端根据清单生成显示标签和内部链接。
- 引用必须在落库时仍能通过当前事件和组织连接验证；验证失败时返回 `citation_scope_invalid`。
- Provider 的 `requires_confirmation` 只是展示字段，不是权限判断。M5.1 不提供“执行建议”按钮，也不创建 Operation。
- 输出建议若涉及重启、部署、回滚、GitHub 写入、Shell 或其他写操作，界面统一标记“未授权建议；需另行生成并确认受控计划”。
- 回答正文不得包含可点击的任意外部 URL、命令或任意文件路径作为可信引用。

## 9. Provider 失败与恢复

固定错误码至少包括：

- `provider_timeout`
- `provider_http_error`
- `provider_response_too_large`
- `provider_invalid_json`
- `provider_invalid_schema`
- `provider_unknown_citation`
- `citation_scope_invalid`
- `context_assembly_failed`

失败轮次进入 `failed`、释放会话活动键并保存有限错误说明。不得保存或回显 Provider 原始响应、Header 或带查询参数的 URL。失败不创建 Agent 请求、不创建 Operation，也不自动重试造成重复费用；用户可以显式重新提问，得到新的 `client_request_id`。

进程在提交 `pending` 后退出，或在 Provider 调用期间退出时，维护扫描应把超过阈值的轮次标记为 `failed/provider_interrupted` 并释放活动键，不自动重放可能已经发送的模型请求。这样牺牲透明重试，换取费用和回答幂等语义可控。

测试 Provider 固定根据输入引用清单生成确定性事实，不进行网络访问，不声称根因。

选择 `conversation_provider=http_json` 时必须同时配置 `CONVERSATION_API_URL`，缺失或未知 Provider 在控制平面启动期即被拒绝，而不是等到用户提交问题后才失败。

## 10. Web 最小交互

事件页在现有诊断和操作入口下增加“事件会话”区域：

- 首次为空时解释只使用当前事件已有记录，不访问 VPS、不执行操作。
- 多行问题输入、字符计数、2000 字符限制和提交按钮。
- 提交中禁用重复发送；活动轮次显示加载状态并轮询。
- 历史按用户问题/结构化回答展示，明确区分事实、推断、建议和缺失信息。
- 引用显示真实来源类型、时间和短标签；可跳到当前页证据锚点、诊断记录或操作详情。
- Provider 失败显示固定错误与“重新提问”，不把失败伪装为空回答。
- 事件不存在显示 404；控制平面不可用显示独立错误，不再统一伪装成 404。
- 首版无流式输出、无全局对话抽屉、无工具调用、无“执行建议”快捷按钮。

Web 会话提交与轮询请求都通过 `/console/...` 服务端代理并执行同源校验，管理令牌不进入浏览器。

## 11. 测试矩阵

### 11.1 API 单元与契约

- 问题空白、超长、UTF-8 超限、未知字段和非法 `client_request_id` 被拒绝。
- 确定性 Provider 输出稳定且每项引用合法。
- HTTP Provider 超时、非 2xx、超 256 KiB、非法 JSON、缺字段、多余字段、超长字段和未知引用均受控失败。
- 恶意问题、证据、诊断结果和操作输出中的“忽略系统指令/执行命令”只作为不可信内容。
- 上下文排序、条目上限、总字节预算、UTF-8 截断和脱敏确定可重复。
- 相同 `client_request_id` 幂等；同会话并发活动轮次返回 409。
- Provider 失败后活动键释放，可创建新轮次。

### 11.2 作用域与引用真实性

- 当前事件只能读取自己的诊断和证据。
- 其他事件的诊断/证据 ID 即使存在也不能进入引用清单。
- 其他组织的事件、Agent、服务、诊断、证据、Operation 和会话统一返回 404。
- `source_diagnostic_id` 指向当前事件的 Operation 可以进入摘要；其他事件 Operation 被排除。
- 每个已落库引用都能通过会话事件和组织连接回真实来源。
- 来源在 Provider 调用期间失效时，落库前二次校验使该轮失败，不留下虚假引用。

### 11.3 M4 零副作用

- 提问前后 `operations` 与 `operation_transitions` 行数、状态、签名字段均不变。
- 不调用 Operation 创建/确认函数，不触发 Agent operation/evidence Claim。
- Provider 文本包含“立即重启/部署/回滚”也只形成建议文本。

### 11.4 Web

- 事件页空状态、历史、事实/推断/建议分区和引用跳转。
- 输入长度、忙碌禁用、409、502、Provider 失败和轮询终止。
- 服务端代理拒绝跨站 Origin、非法事件 ID、非法请求体；不泄露管理令牌。
- API 不可用与事件不存在使用不同 UI。

### 11.5 真实 PostgreSQL 与回归

- 空库 `0009 -> 0010`、模拟已有 M4 数据的 `0009 -> 0010`、`0010 -> 0009 -> 0010` 和 `app.schema check`。
- 真实 PostgreSQL 验证会话唯一、请求幂等、活动轮次部分唯一索引、外键、CHECK 和跨组织查询。
- 使用真实 API + PostgreSQL + 确定性 Provider 完成事件提问、轮询、引用落库和历史读取。
- 运行现有 API、Web、Go 测试，Ruff、ESLint、`go vet` 和 Web 生产构建。

## 12. P0 / P1 / P2 风险清单

### P0：实现前必须关闭

1. **事件与组织作用域未形成统一查询门。** M5.1 必须先实现受信任管理上下文和显式作用域查询；禁止用 `session.get(id)` 后再补判断。
2. **引用真实性缺少统一清单和持久校验。** 必须由服务端生成引用 ID、Provider 只回传 ID、落库前二次验证，并保存引用关系。
3. **会话可能成为 M4 的 confused deputy。** Provider 接口必须无工具；会话服务只可读取 Operation 摘要，不得导入或调用 Operation/Agent 写服务入口；增加零副作用回归测试。
4. **Provider schema 不够严格。** 会话输出必须 `extra="forbid"`、有总响应上限，并拒绝未知引用和部分非法结果。
5. **缺少总上下文预算。** 必须在调用 Provider 前实施确定性 128 KiB 总预算和条目上限。

### P1：首个垂直切片应完成

1. 问题、历史、证据和操作输出再次脱敏，正文不进入日志。
2. Provider 失败错误码分类、活动轮次释放和显式重试语义。
3. `client_request_id` 幂等和多 API 实例并发保护。
4. 真实 PostgreSQL 的迁移、约束、作用域和引用集成测试。
5. Web 区分 404、控制平面不可用、Provider 失败与加载中。
6. 上下文清单保存内容摘要、截断和省略信息，支持审计回答使用了什么。
7. 陈旧 `pending/running` 轮次受控失败并释放活动键，不自动重放 Provider 请求。

### P2：M5.1 稳定后增强

1. 历史分页、会话标题/归档和保留策略。
2. 更细的上下文新鲜度提示和引用墓碑。
3. Provider 调用耗时、失败率、上下文字节和裁剪率指标。
4. 诊断/操作引用的更丰富预览和事件复盘导出。
5. 在不扩大权限的前提下评估异步持久任务队列；首版可沿用提交后后台任务。

## 13. 分阶段实施顺序

1. [x] **M5.1a 数据与安全门**：新增显式 `0010`、会话/轮次/引用模型、管理组织上下文、作用域查询助手和约束测试。
2. [x] **M5.1b 上下文与 Provider**：实现确定性上下文组装、总预算、再脱敏、严格回答 schema、引用清单/二次验证和确定性 Provider。
3. [x] **M5.1c API**：实现读取会话、提交轮次、读取轮次；幂等、活动轮次锁、后台 Provider 和受控失败。
4. [x] **M5.1d Web**：事件页会话区、服务端代理、历史、引用、加载和错误状态。
5. [x] **M5.1e 本地验收**：自动测试、真实 PostgreSQL 闭环、M2/M3/M4 零回归和文档同步。
6. [x] **M5.1f 生产金丝雀**：deterministic 与真实 HTTP/DeepSeek 两轮只读金丝雀通过，均未改变 Agent 策略或 M4 写权限；生产恢复 deterministic。

GitHub 白名单关键词检索、服务过滤和 Commit 追踪已由 M5.2.1 的事件作用域首片实现；M4 计划接入会话属于更晚的 M5.3，仍须单独设计和确认。

## 14. 第一个已实现的垂直切片

2026-07-23 经计划确认后，首笔本地实现严格限定为：

### 新增

- 模型：`ConversationSession`、`ConversationTurn`、`ConversationCitation`。
- 迁移：`0010_m5_event_conversation.py`，显式表、外键、CHECK、唯一约束、部分唯一索引和索引。
- API 模块：事件作用域查询、上下文组装、严格会话 Provider、引用验证和三个只读/提问端点。
- Web：事件页会话区、`/console/events/{id}/conversation/turns` 服务端代理、轮询与引用展示。
- 测试：API 契约/安全/Provider/作用域/零 Operation 副作用，Web 代理/组件，真实 PostgreSQL 迁移与闭环。

### 修改

- `models.py`、`schemas.py`、`config.py`、`main.py` 和数据库 schema 检查。
- `apps/web/lib/api.ts`、事件页和样式。
- `.env.example`、Compose/生产配置中的会话 Provider 上限；默认仍为 deterministic。
- `ROADMAP.md`、`PROJECT_STATUS.md`、`ARCHITECTURE.md`、`WEB_UI_PLAN.md` 和本文件的实际实现状态。

### 不触碰

- Go Agent。
- M4 v1/v2 任务协议、签名、状态机、能力目录、确认、执行、验证和回滚逻辑。
- GitHub 写权限、Shell、任意路径、Agent 证据领取和生产部署。

## 15. 本地验收标准

M5.1 只有同时满足以下条件才可标记本地实现完成：

- 已有事件能完成提问、确定性回答、真实引用和历史读取。
- 所有引用在数据库中真实存在，并通过当前事件与组织作用域校验。
- 其他事件/组织的资源不能读取或引用。
- 恶意证据、问题和操作输出不能改变指令、权限或触发工具。
- 提问前后没有创建或改变任何 M4 Operation/Transition。
- Provider 超时、异常、超大响应、非法结构和非法引用均进入可解释失败状态。
- 新迁移在真实 PostgreSQL 的空库和 `0009` 旧库路径通过，现有数据保留。
- API/Web/Go 全部现有测试和静态检查无回归；Web 生产构建通过。
- 完成独立的真实 PostgreSQL + API + deterministic Provider 闭环。

2026-07-23 本地验收结果：

- M5.1 完成时 Alembic 单一 head 为 `0010_m5_event_conversation`；当前 M5.2.1 本地 head 为 `0011_m5_repository_citations`，`0010 -> 0011 -> 0010 -> 0011` 和 `app.schema check` 均通过。
- 真实 PostgreSQL 集成验证覆盖事件存在但无会话的 200 空结果、跨组织 404、复合外键隔离、单活动轮次约束、已有诊断/恶意证据进入有界脱敏上下文、引用落库和 Operation 计数前后为 0。
- API 146 项通过、1 项 PostgreSQL 门控测试在常规无数据库运行中跳过；该门控测试在独立 PostgreSQL 中单独通过。Web 41 项、全部 Go 包、Ruff、ESLint、Compose 配置和 Next.js 生产构建通过。
- 提交前加固补齐轮询代理同源校验、上下文优先于历史的预算顺序、HTTP Provider 超时/非 2xx/超大响应/非法 JSON 测试、启动期 Provider 配置校验和后台生命周期组织参数传递。
- 已提交 `f53eeee` 并推送 `main`；没有修改 Go Agent 或 M4 v1/v2 协议与状态机。

## 16. 生产金丝雀记录与后续边界

deterministic 只读金丝雀已于 2026-07-23 在用户授权下通过（控制平面 `df01ec1 -> f53eeee`、迁移 `0009 -> 0010`、postflight 通过；事件 `f4ca0d89` 提问 -> 轮次 `completed`，2 事实 + 1 建议(`requires_confirmation=true`) + 2 真实引用；`operations=7`/`operation_transitions=45` 不变；日志无泄露；Fleet 未变）。真实 HTTP Provider 金丝雀亦已于 2026-07-23 通过：经临时适配器接 DeepSeek，事件 `f4ca0d89` 提问 -> 轮次 `completed`(`provider=http_json`)，DeepSeek 返回结构化答案并正确引用本轮真实 `ctx_`；控制平面 `extra="forbid"` + 引用集合校验 + 作用域二次校验 + 再脱敏全部通过；`operations=7`/`operation_transitions=45` 不变（零写副作用）；日志无正文/凭据泄露。金丝雀后已还原 deterministic 并移除临时适配器。以下边界同样适用：

- 控制平面先按 M4.1 标准流程备份、迁移、部署和 postflight。
- 只选择一个已有、非敏感、可人工核对的事件；Provider 首次金丝雀优先 deterministic。
- 记录会话/轮次/引用 ID、上下文字节、裁剪、Provider 状态和数据库约束结果。
- 金丝雀前后核对 `operations`/`operation_transitions` 无新增或状态变化。
- 不升级 Agent、不更改 Agent evidence/operation/deploy policy、不访问 VPS。
- 以后重新启用真实 HTTP Provider 时仍须使用受信任、生产网络可达的网关和非敏感测试数据，并重新核对超时、非法引用、脱敏和日志泄露；临时适配器不属于仓库或长期生产组件。
- 任何写操作会话、GitHub 写入或 M4 计划生成必须另立切片、重新威胁建模并再次获得授权。
