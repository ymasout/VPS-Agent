# M5 收尾统一设计（M5.5–M5.7）

本文统一设计 M5 剩余三个产品体验切片：

- M5.5：全局 Fleet 只读会话；
- M5.6：诊断历史、相似事件与用户反馈；
- M5.7：Runbook 草稿与事件复盘。

当前状态：**M5.5–M5.7 已完成本地实现与验收，生产金丝雀通过 2026-07-26。** 新能力均由默认关闭的独立开关保护；生产运行 `a5208e7`，三个新开关默认关闭。

## 1. 决策摘要

三个切片统一设计、连续实现，但必须独立提交、独立功能开关、独立真实 PostgreSQL 门控和独立生产金丝雀。推荐顺序固定为：

1. M5.5 建立组织级 Fleet scope、确定性预筛选和聚合引用；
2. M5.6 在既有事件/诊断/会话数据上增加历史、可解释相似事件和显式反馈；
3. M5.7 增加不可执行的 Runbook 草稿及只读事件复盘。

实现期间可以连续开发，不要求每片重新编写一份总设计；但前一片本地门未关闭前，不进入后一片。生产不得一次开启三个功能。

## 2. 目标

### 2.1 M5.5

- 在顶级 Agent 页面提供当前组织的全局 Fleet 只读会话。
- 回答 Fleet 健康概况、当前异常、离线 Agent、异常服务、最近失败操作和相关诊断。
- 服务端先确定性聚合与预筛选，再调用既有 Conversation Provider。
- 聚合事实与具体资源事实都具有真实、可复查、带时间点的引用。
- 引导用户进入具体 Agent、服务、事件、仓库或 Operation 页面继续查看。

### 2.2 M5.6

- 在事件工作区统一展示诊断、会话和操作历史。
- 用可解释的结构化规则查找同组织相似事件，不使用整库向量检索。
- 允许用户对已完成会话轮次提交“有帮助/无帮助”反馈。
- 反馈只用于质量统计和以后离线评估，不自动改变 Provider 提示、权限或执行策略。

### 2.3 M5.7

- 把已完成轮次中的一条建议显式保存为不可执行的 Runbook 草稿。
- 在事件页生成基于已有记录的只读复盘视图。
- 复盘串联事件、诊断、证据、会话结论与 Operation 时间线，并标出缺失证据。
- 所有可执行操作仍只能从现有可信页面或 M5.3 的显式交接进入 M4。

## 3. 非目标

- 不允许 Provider 工具调用、自由 Shell、任意命令或任意文件系统路径。
- 不把整个 Fleet、全部历史日志或全部仓库文件发送给 Provider。
- 不做跨组织、跨授权仓库或隐式多仓库检索。
- 不从问题正文解析 Agent ID、实例 ID、服务键、digest、路径、回滚来源或确认字段。
- 不创建自动修复、自动部署、自动回滚或自动 Runbook 执行。
- 不新增会话到部署计划交接；部署继续使用 M4.2 的可信候选和 digest 选择器。
- 不实现 GitHub branch、commit、push、PR 等写操作。
- 不让反馈在线修改提示词、排序权重、引用门或权限策略。
- 不在首版引入向量数据库、多 Agent 自主循环或长期记忆。
- 不把 Runbook 草稿视为已审核 Runbook，不提供发布、执行或转换为任意命令的端点。
- 不改变 M4 v1/v2 协议、签名、过期、幂等、确认、领取、执行、验证、回滚或审计状态机。

## 4. 必须继承的安全边界

1. Provider 和自然语言保持零写权限。
2. Web/API 不直接访问 VPS；会话请求不领取 Agent evidence/operation 任务。
3. 所有作用域由 URL、管理身份和数据库关系服务端派生。
4. 所有根查询先带 `organization_id`；未知或跨组织资源统一 404。
5. Provider 只能返回本轮服务端生成的不透明引用别名。
6. 引用落库前再次按当前组织、scope 和来源关系校验；整轮失败而不是部分接受非法引用。
7. 日志、诊断、仓库快照、历史问题、反馈和 Provider 输出全部是不可信数据。
8. 上下文继续执行统一字节预算、确定性排序、UTF-8 安全截断和二次脱敏。
9. Provider 超时、非 2xx、超大响应、非法 JSON/schema 和未知引用继续受控失败，不保存原始响应。
10. 任何操作计划仍需结构化计划、显式用户动作、M4 独立确认和原有签名执行闭环。

## 5. 威胁模型

| 风险 | 场景 | 控制 |
| --- | --- | --- |
| 跨组织枚举 | 全局入口或相似事件搜索泄露其他组织资源是否存在 | 所有根查询先带组织；ID 不存在和跨组织统一 404；真实 PostgreSQL 复合外键与隔离测试 |
| Fleet 上下文爆炸 | 大量 Agent、服务、事件和历史进入 Provider，造成费用、超时或遗漏高优先级异常 | 全量只做服务端计数；正文只取有界候选；固定优先级、分项上限和 128 KiB 总预算 |
| 聚合事实无真实来源 | Provider 声称“5 台离线”，但引用只指向一台 Agent | 每轮持久化不可变 Fleet 快照；聚合数字必须引用快照，命名资源必须另引原子记录 |
| 问题正文扩大 scope | 用户输入其他组织 UUID、仓库名或“读取全部日志” | 问题只参与同组织候选的有界排序，不作为授权或直接查询主键 |
| 提示注入 | 服务名、事件文本、诊断、证据、仓库或历史要求忽略系统指令或调用工具 | 明确标为不可信数据；无工具 Provider；严格输出 schema；二次引用校验 |
| 相似事件侧信道 | 相似结果暴露其他组织或不应进入当前服务范围的事件 | 首版仅同组织；结果显示匹配原因；服务/Agent过滤只使用服务端关系 |
| 相似度伪精确 | 模型或模糊算法给出不可解释高分 | 首版只使用版本化确定性规则和离散理由，不使用 Provider 或向量生成相似度 |
| 反馈投毒 | 恶意反馈直接改变后续提示、权限或排序 | 反馈不进入在线上下文；只记录有限枚举和短备注；后续使用需离线审核 |
| Runbook confused deputy | Provider 建议被保存后伪装成已授权操作，或一键执行 | 只允许显式创建不可执行草稿；请求体不接受命令/路径/目标；无执行和 M4 转换端点 |
| 复盘伪造 | 复盘把推断写成事实或丢失来源 | 事实、推断、建议、缺失证据分区；每项保留真实来源；只读生成失败关闭 |
| CSRF/管理令牌泄露 | 浏览器跨站提交反馈或创建草稿 | 所有客户端代理 GET/POST/PUT 均执行同源校验；管理令牌只在服务端 |
| TOCTOU | Provider 调用期间来源被删除、撤权或改属 | 每轮快照记录时间点；落库前二次校验；撤权来源显示墓碑且不再读取正文 |
| 非运维写副作用扩散 | 反馈/草稿写入意外创建 Operation 或触发 Agent/GitHub | 模块依赖隔离；数据库计数和 mock/spies 证明零 Operation、零 Agent、零 GitHub 写副作用 |

## 6. 数据模型

### 6.1 M5.5：组织级 Fleet 会话

迁移建议：`0015_m5_fleet_conversation`。

扩展 `conversation_sessions`：

- `scope_type` 增加 `fleet`；
- `fleet` 要求 `event_id/repository_id/agent_id/service_id` 全部为 `NULL`；
- 其余四种 scope 继续严格恰好一个目标，不允许混合；
- PostgreSQL 增加 `UNIQUE (organization_id) WHERE scope_type = 'fleet'`，保证每个组织至多一个 Fleet 会话；
- 不新增可由客户端填写的 `fleet_id`。组织本身就是可信根。

新增 `fleet_conversation_snapshots`：

| 字段 | 规则 |
| --- | --- |
| `id` | UUID 主键 |
| `organization_id` | 必填，并与 turn 形成复合外键隔离 |
| `turn_id` | 一轮一个快照，唯一；轮次删除时级联 |
| `schema_version` | 固定版本，如 `m5.5-fleet-snapshot-v1` |
| `captured_at` | 聚合查询时间点 |
| `counts` | 仅保存白名单整数计数和状态桶 |
| `selected_source_ids` | 保存进入本轮候选的来源类型与 ID，不保存正文 |
| `omitted_counts` | 分来源记录因上限、预算或无权限省略的数量 |
| `content_sha256` | 对 counts、selected source IDs、omitted counts 与时间点组成的规范化快照计算摘要，支持审计；Provider 展示内容不暴露这些内部 ID |

`counts` 只允许固定键，例如 Agent 在线/离线数、服务健康状态数、活动事件严重级别数、近期 Operation 状态数。应用 schema 必须拒绝未知键、负数和非整数。

扩展 `conversation_citations`：

- 新增 `fleet_snapshot` 来源类型和可空 `fleet_snapshot_id`；该外键使用 `ON DELETE SET NULL`；
- 聚合事实只能引用本轮快照；
- 涉及具体 Agent、服务实例、事件、诊断或 Operation 的事实必须引用既有原子来源；
- `fleet_snapshot` 不允许替代具体资源引用；
- 快照存在时，snapshot、citation 和 turn 必须属于同一组织和同一轮次；快照因保留策略删除后，citation 只保留 `source_label`、`source_collected_at` 与 `snapshot_sha256` 墓碑，不再渲染 counts 或任何正文。

### 6.2 M5.6：反馈

迁移建议：`0016_m5_conversation_feedback`。

新增 `conversation_turn_feedback`：

| 字段 | 规则 |
| --- | --- |
| `id` | UUID 主键 |
| `organization_id` | 必填 |
| `turn_id` | 与组织形成复合外键，轮次删除时级联 |
| `created_by` | 当前管理身份，不能由请求体覆盖 |
| `rating` | `helpful` 或 `not_helpful` |
| `reason_code` | 可空，固定枚举，如 `incorrect`、`missing_context`、`unclear`、`unsafe_suggestion`、`other` |
| `comment` | 可空，最多 500 字符/2 KiB UTF-8，写前脱敏，不进入日志 |
| `created_at/updated_at` | 审计时间 |

唯一约束为 `(organization_id, turn_id, created_by)`；使用 PUT 覆盖同一用户反馈，保证幂等。反馈不进入 Provider 上下文，不触发自动训练或提示变更。

首版相似事件不新增持久化索引表。服务端按当前数据库记录实时执行有界、确定性的候选查询；需要优化时再增加可重建缓存，不把缓存作为权限或真实性来源。

### 6.3 M5.7：不可执行 Runbook 草稿

迁移建议：`0017_m5_runbook_drafts`。

新增 `runbook_drafts`：

| 字段 | 规则 |
| --- | --- |
| `id` | UUID 主键 |
| `organization_id` | 必填 |
| `source_turn_id` | 可空，复合外键；轮次删除时 `SET NULL`，保留墓碑 |
| `source_event_id` | 可空，复合外键；事件删除时 `SET NULL` |
| `service_id` | 可空，必须由来源会话关系服务端派生 |
| `client_request_id` | 与组织/来源轮次组成幂等键 |
| `title` | 服务端从所选建议生成并再次脱敏，有限长度 |
| `content` | 固定 schema：目标、前置检查、展示步骤、风险和引用别名；不含可执行参数字段 |
| `source_citation_ids` | 仅保存属于来源轮次且创建时仍有效的 citation ID；来源删除后只显示墓碑 |
| `status` | 首版固定 `draft` |
| `created_by/created_at/updated_at` | 审计字段 |

创建请求只能包含：

```json
{
  "client_request_id": "UUID",
  "recommendation_index": 0
}
```

请求体不得接受标题、步骤、命令、路径、Agent、实例、服务键、镜像、digest、回滚来源、操作类型、确认或执行字段。服务端只从一个同组织、已完成、引用仍有效的轮次中确定性复制指定建议和已有引用，不发起第二次 Provider 调用，并将其标记为“不可信、不可执行草稿”。

首版事件复盘不新增持久化模型。`GET` 在请求时从单个事件的已有记录确定性组装只读视图；以后只有出现人工编辑、签署或保留策略需求时才增加 `incident_reviews`。

## 7. API 协议

所有请求继续使用当前管理身份的组织上下文。响应采用 `extra="forbid"` 的严格 schema，分页使用不透明 cursor，默认和最大 limit 固定。

### 7.1 M5.5

#### `GET /api/v1/fleet/conversation`

- 组织存在但尚无会话：`200`，`session_id=null`、`turns=[]`；
- 功能关闭：仍返回 `200`，`available=false`、`unavailable_reason=feature_disabled`；
- 不返回其他组织是否存在。

#### `POST /api/v1/fleet/conversation/turns`

请求复用 `ConversationQuestion`，只接受 `client_request_id` 和有限问题正文。

服务端创建/复用当前组织唯一 Fleet session，生成快照和有界上下文，再进入既有 Provider、轮次状态、幂等、活动轮次锁和失败恢复流程。端点不接受任何资源 ID。异步 Provider 只读取创建轮次时已经持久化的不可变 snapshot counts 和当时选定的有界原子项，不得在 Provider 阶段重新查询 live 聚合数字。

#### `GET /api/v1/conversation-turns/{turn_id}`

继续复用 scope-aware 轮询。增加 `fleet` 分支后，必须通过 turn→session→organization 联接验证，不能只按 turn ID 读取。

### 7.2 M5.6

#### `GET /api/v1/events/{event_id}/history`

返回单个事件的有界统一时间线：

- 事件状态变化；
- DiagnosticRun；
- 已完成/失败 ConversationTurn；
- Operation 及白名单转换摘要。

不返回 Operation 计划、签名、nonce、target、digest、输出正文、transition details/reason/actor ID。

#### `GET /api/v1/events/{event_id}/similar-events`

参数仅允许 `limit` 和不透明 cursor。当前事件由 URL 服务端解析，不接受组织、Agent、服务、时间范围或权重参数。

每项至少返回：

- 事件有限摘要；
- `score_band=high|medium|low`；
- 固定 `match_reasons`；
- 是否同服务/同 Agent；
- 最近已完成诊断的有限结论；
- 事件详情内部链接。

#### `PUT /api/v1/conversation-turns/{turn_id}/feedback`

严格接受：

```json
{
  "rating": "helpful",
  "reason_code": null,
  "comment": null
}
```

只允许对当前组织已经 `completed` 的轮次反馈；未知、跨组织、pending/running/failed 轮次拒绝。返回规范化后的单条反馈。

### 7.3 M5.7

#### `GET /api/v1/events/{event_id}/review`

返回只读复盘：

- 事件起止、严重级别和当前状态；
- 关键观测时间线；
- 已确认事实；
- 诊断推断和缺失证据；
- Operation 计划/执行/验证的白名单状态摘要；
- 相关会话结论；
- 来源引用。

事件未解决也可预览，但响应必须标记 `provisional=true`，不能声称最终根因或处置成功。

#### `POST /api/v1/conversation-turns/{turn_id}/runbook-drafts`

这是显式的控制平面数据库写入，但不是运维操作。只创建 `draft`，不创建 Operation、不签名、不确认、不执行。

只允许来源轮次仍存在、已完成、作用域有效且所选建议具有真实引用。重复 `client_request_id` 返回同一草稿。

#### `GET /api/v1/runbook-drafts/{draft_id}`

返回不可执行草稿、来源墓碑状态和内部引用。无执行、发布、确认、转 Operation、导出 Shell 或 GitHub 写端点。

## 8. Fleet 上下文组装

### 8.1 两阶段查询

第一阶段只在数据库内计算当前组织的完整计数快照，不读取大正文。计数、候选选择和 snapshot 落库必须处于同一个只读 `REPEATABLE READ` 快照或等价的单语句一致性查询中；不能把多个 `READ COMMITTED` 查询的不同时间点伪装成同一份 Fleet 快照。

第二阶段选择有限候选：

1. firing/acknowledged 的高严重度事件；
2. 离线或陈旧 Agent；
3. unhealthy/unknown 服务实例；
4. failed/verifying/awaiting_confirmation 的近期 Operation；
5. 上述资源的最新已完成诊断；
6. 用户问题与同组织可信元数据匹配的少量候选；
7. 正常资源仅作为剩余预算内的对照样本。

问题中的 UUID、仓库名、路径或命令文本不得直接转化为无作用域主键查询。匹配只在已经按组织取出的候选集合或带组织条件的查询中进行。

### 8.2 固定上限

首版建议上限：

- Agent 原子项：12；
- 服务实例：20；
- 活动事件：20；
- Operation：10；
- DiagnosticRun：10；
- 每项有限 Evidence：2，总计不超过 12；
- 历史完成轮次：最多 6，且不超过 32 KiB；
- Fleet 首版不装载仓库文件正文；需要代码上下文时引导进入单仓库或具体事件会话；
- 总序列化上下文继续不超过 128 KiB。

优先选择当前事实和原子证据，最后才加入会话历史；超预算先删除低优先级历史，再删除正常资源对照项。每类省略数量同时进入 snapshot 与 `context_manifest`。

### 8.3 脱敏与不可信边界

- 沿用 M5.1 的凭据、URL 查询参数、Authorization、令牌、私钥和常见密钥模式脱敏。
- Fleet 聚合不包含日志正文、Operation output、签名、nonce、Agent target 或 GitHub 凭据。
- 事件复盘默认不装载原始用户问题、反馈备注或 Provider 原始响应，只读取已验证的结构化答案和真实引用。
- 名称、标签、事件消息、诊断、反馈和 Runbook 文本在 Provider 输入中使用明确的数据包边界，不能与系统指令拼接。
- 上下文清单保存来源 ID、时间、字节、截断、脱敏和省略原因，不保存 Provider 原始请求或响应。

## 9. 相似事件规则

首版算法固定版本为 `m5.6-similarity-v1`，候选仅来自当前组织，默认回看 180 天，最多返回 10 项。

匹配信号及理由：

- 同一个 ManagedService；
- 同一个 Agent；
- 同一事件来源和规则键；
- 同一严重级别；
- 相同的结构化状态/错误码；
- 相同诊断结论标签（若当前模型已有结构化值）；
- 时间接近仅作为弱信号。

自由文本只允许经过脱敏、长度限制和确定性规范化后形成低权重关键词交集；不得把日志正文直接建立长期索引。分数只用于当前组织候选排序，Web 显示离散 `score_band` 和具体匹配理由，不显示伪精确百分比。

Provider 不参与候选选择和分数计算。相似事件即使被返回，也不会自动进入当前会话上下文；用户必须打开该事件，或以后通过显式“加入上下文”功能重新做作用域检查。

## 10. 结构化回答与引用规则

- 继续使用 `summary/facts/inferences/recommendations/missing_evidence`。
- 每条事实和推断至少一个有效引用；声称基于当前情况的建议也必须引用。
- 聚合数字引用 `fleet_snapshot`；具体资源陈述引用对应原子记录。
- 相似事件结果引用真实 `alert_event`，相关诊断结论另引 `diagnostic_run`。
- Runbook 草稿保留来源轮次和建议的引用集合，但引用失效后只显示墓碑，不重新读取已撤权正文。
- 复盘中的“已确认事实”“推断”“处置结果”分区展示；Operation `succeeded` 只按 M4 已验证状态陈述。
- Provider 不得生成外部可点击 URL；链接由服务端根据白名单资源类型构造。
- 未知、重复异常、跨 scope、跨组织、已撤权或时间点不一致的引用使整轮受控失败。

## 11. Web 最小交互

### 11.1 M5.5

- 顶级导航的“Agent”进入 `/agent` 全局会话页。
- 页首固定显示“当前组织 Fleet，只读，不访问 VPS，不执行操作”。
- 提问前展示服务端聚合的更新时间和范围说明，不展示隐藏资源 ID。
- 回答引用可以进入现有 Agent、服务、事件或 Operation 页面。
- 加载、轮询、失败、空会话和功能关闭状态复用现有组件语义。

### 11.2 M5.6

- 事件页增加“历史与相似事件”区域。
- 历史按统一时间轴展示，但保留诊断、会话、操作的类型标识。
- 相似事件显示匹配原因、时间、状态和服务，不自动合并证据。
- 已完成回答提供有帮助/无帮助反馈；备注是可选项，提交后可修改。

### 11.3 M5.7

- 事件页增加“复盘”标签，未解决事件明确显示“临时视图”。
- 已完成轮次的一条建议旁增加“保存为 Runbook 草稿”，按钮说明不会执行任何操作。
- 创建成功后进入独立草稿详情页；页面固定显示“未审核、不可执行”。
- 不渲染 Provider 提供的任意 HTML，不把文本识别成按钮，不提供复制并执行命令的快捷动作。

所有客户端代理执行同源校验；能由 Server Component 直接读取的 GET 继续经服务端 API 客户端完成，管理令牌不进入浏览器。

## 12. 功能开关

建议新增三个独立且默认关闭的开关：

- `CONVERSATION_FLEET_CHAT_ENABLED=false`
- `CONVERSATION_INSIGHTS_ENABLED=false`
- `CONVERSATION_REVIEW_ENABLED=false`

开关关闭时不得创建 session、snapshot、feedback 或 draft。关闭 M5.5–M5.7 不影响 M5.1–M5.4 和 M4。

## 13. 测试矩阵

### 13.1 API 与 Provider

- Fleet GET 在无会话时返回 200 空 turns；功能关闭返回明确原因。
- Fleet POST 只接受问题和 `client_request_id`，未知字段拒绝。
- Provider 不拥有工具；恶意资源文本不能改变 scope 或触发写入口。
- 超时、非 2xx、超大响应、非法 JSON/schema、未知/跨 scope 引用均受控失败。
- 聚合事实引用本轮快照；具体资源事实不能只引用快照。
- 上下文排序、上限、总字节、历史低优先级和 omitted 计数确定可重复。

### 13.2 组织与作用域

- Fleet session 每组织唯一，五种 scope CHECK 拒绝空目标或混合目标。
- 同一个问题包含其他组织 UUID 时仍无法读取或推断对应资源。
- 通用 turn 轮询覆盖 fleet 分支并验证 session/turn/organization 联接。
- 相似事件只来自当前组织，跨组织同规则键也不能出现。
- 反馈、草稿和复盘未知/跨组织统一失败关闭。

### 13.3 M5.6

- 相似事件规则版本、排序、并列顺序和理由确定性。
- 没有相似事件时返回 200 空列表。
- 反馈仅允许 completed turn；PUT 幂等更新，不产生重复行。
- 反馈备注脱敏且不进入日志、Provider 上下文或相似度计算。
- 历史分页稳定，不暴露 Operation 敏感字段。

### 13.4 M5.7

- 草稿创建只接受轮次与建议索引，服务/事件由服务端派生。
- 草稿读取按 `source_citation_ids` 重新查询当前仍存在且属于来源轮次的 citation；缺失、撤权或跨 scope 引用只显示墓碑，不渲染原来源正文。
- 非法索引、无引用建议、失效 scope、pending/failed turn 受控拒绝。
- 草稿幂等；来源删除后 `SET NULL` 墓碑可读。
- 草稿文本永不被解释为命令、操作参数或 HTML。
- 未解决事件复盘 `provisional=true`；已解决事件也不能把推断提升为事实。
- 复盘 Operation 状态与 M4 当前记录一致，失败或 verifying 不声称成功。

### 13.5 零副作用与回归

每个只读请求前后验证：

- `operations` 和 `operation_transitions` 行数、状态、签名字段不变；
- 无 Agent evidence/operation Claim；
- 无 GitHub 同步、文件、binding 或写请求；
- 无 VPS 网络连接。

Runbook 草稿和反馈只允许对应业务表新增/更新，仍不得改变上述对象。

运行现有 API/Web/Go 全部测试、Ruff、ESLint、`go vet`、Web production build 和 Compose 配置检查。

### 13.6 真实 PostgreSQL

每个迁移分别验证：

- 空库升级到 head；
- `0014 -> 0015 -> 0014 -> 0015`，随后依次覆盖 `0016`、`0017` 往返；
- `app.schema check`；
- 五 scope CHECK、部分唯一索引、复合组织外键、幂等、级联/`SET NULL`；
- M5.1、M5.2.1、M5.2.2、M5.3.1、M5.3.2、M5.3.3、M5.4 门控不回归。

## 14. 分阶段实施顺序

### M5.5a：数据库与可信 Fleet scope

- `0015`、Fleet session CHECK/唯一索引、snapshot 与 citation；
- 组织级查询门、确定性聚合和上下文预算；
- API/Provider/真实 PostgreSQL 安全测试。

### M5.5b：全局会话 Web

- `/agent` 页面、会话历史、引用跳转、加载/错误/关闭状态；
- 同源代理和 Web 测试；
- 全量本地回归。

### M5.6a：历史与相似事件

- 统一历史读 API；
- `m5.6-similarity-v1`；
- 事件页历史和相似事件区。

### M5.6b：显式反馈

- `0016`、反馈 PUT、Web 控件和脱敏；
- 反馈零在线权限影响测试。

### M5.7a：只读复盘

- 事件 review GET；
- 事实/推断/操作结果/缺失证据分区和来源链接；
- 未解决事件临时状态。

### M5.7b：Runbook 草稿

- `0017`、显式草稿创建和详情页；
- 无发布、无执行、无 Operation 转换；
- M5 总回归。

## 15. 本地验收标准

M5.5–M5.7 只有同时满足以下条件才可标记本地完成：

- 所有新 schema、API、Web 状态与本文一致；
- Fleet 聚合和具体资源引用都能回查真实来源；
- 跨组织、混合 scope、恶意正文、非法引用全部失败关闭；
- 相似事件可解释、确定性且不由 Provider 选数；
- 反馈不改变在线回答、权限或执行策略；
- Runbook 只能生成显式、不可执行草稿；
- 复盘不把推断写成事实，不把非 succeeded 操作写成成功；
- 所有 M5.1–M5.4 和 M2/M3/M4 测试无回归；
- 真实 PostgreSQL 完成迁移往返、schema check 和新增门控；
- 功能开关默认关闭；
- 未修改 Go Agent、M4 协议或生产 Agent 策略。

## 16. 生产金丝雀边界

每个切片必须在用户明确授权后独立金丝雀：

1. 备份、单步迁移、部署、postflight；
2. 功能关闭状态验证既有 M5 与 M4 无回归；
3. 只选择当前组织的非关键数据；
4. 临时只开启当前切片开关；
5. 记录请求、session、turn、snapshot/feedback/draft 和引用 ID；
6. 对每个引用验证真实存在、组织和 scope；
7. 前后核对 Operation/Transition、Agent 任务、GitHub 文件与 binding；
8. 检查日志不包含问题、证据、反馈备注、Provider 原始响应或凭据；
9. 验证后关闭当前开关，保留必要审计记录。

M5.7 草稿金丝雀只允许创建不可执行草稿，不允许把草稿转为 Operation。生产金丝雀不授权部署、回滚、重启、GitHub 写或 Agent 新能力。

2026-07-26 生产金丝雀结果：部署 `a5208e7`（含 `c08e54b` M5.5-7 代码 + 迁移 `0014->0017` 离线守卫修复）+ postflight。M5.5：fleet `completed`，快照持久化（5 agents/3 instances/3 events 真实 counts），`fleet_snapshot` 聚合引用 + `agent_summary`/`service_instance_summary` 原子引用，ops/trans 13/81 不变。M5.6：历史脱敏 grep=0，相似事件 `m5.6-similarity-v1` 离散 score_band，反馈 `count=1` 落库。M5.7：复盘 `provisional=false`，草稿 `executable=false`/`status=draft`，execute 端点 404。还原三开关 false，ops/trans 仍 13/81。

**实施偏差说明**：设计 §1 要求三片独立提交，实际经用户批准以统一提交 `c08e54b` 连续实现 + `a5208e7` 离线守卫修复。三片仍保持独立迁移（0015/0016/0017）、独立开关和独立验证边界（各自金丝雀、各自 PG 门控）。

## 17. M5 完成定义

完成 M5.5–M5.7 的本地验收和各自生产金丝雀后，可以把 **M5 诊断与操作会话体验** 标记为完成，前提是：

- event/repository/agent/service/fleet 五种只读会话 scope 均有生产证据；
- restart/rollback 交接仍完整复用 M4，部署继续走可信部署页；
- 历史、相似事件、反馈、Runbook 草稿和复盘均有真实引用与组织隔离；
- 所有功能默认关闭策略和生产回退状态有记录；
- 没有把 GitHub 写、自由 Shell、自动修复、多 Agent 循环或复杂 RAG 偷渡进完成范围。

M3 未完成项曾按自身里程碑单独跟踪，没有因 M5 收尾而提前关闭；其两项收尾生产门已于 2026-07-26 通过，现已独立标记完成。GitHub 写操作、Runbook 发布/执行和更复杂知识检索进入后续独立里程碑或扩展切片。

## 18. P0 / P1 / P2

### P0：实现前必须关闭

1. Fleet 第五 scope 必须有数据库 CHECK、组织级部分唯一索引和通用轮询分支。
2. Fleet 聚合必须有持久快照；聚合事实不能伪装成某个原子资源事实。
3. 相似事件候选必须先按组织过滤，Provider 不得参与选数。
4. Runbook 草稿没有执行、发布、转 Operation 或任意参数入口。
5. 所有新入口证明不会创建/改变 Operation，不会访问 Agent/VPS/GitHub。
6. Provider、历史、反馈和草稿文本继续作为不可信数据，不能改变权限和系统指令。
7. Fleet 计数、候选与 snapshot 必须来自同一数据库一致性快照，并具有查询超时和索引门。

### P1：每个切片提交前关闭

1. 上下文预算优先保留当前异常与原子证据，历史最后加入。
2. 聚合快照和所有原子引用落库前二次校验。
3. 客户端代理同源校验、严格请求 schema、幂等和并发保护。
4. 反馈备注脱敏、日志最小化且不进入在线 Provider。
5. 真实 PostgreSQL 迁移往返、schema check、跨组织和墓碑测试。
6. 功能关闭状态、空状态和 Provider 失败在 Web 中可区分。

### P2：生产验证前或后续增强

1. Fleet 历史分页、会话归档和保留期。
2. 快照统计耗时、上下文字节、裁剪率和 Provider 费用指标。
3. 相似事件规则的离线质量评估与版本比较。
4. 反馈分析面板和导出；在人工审核前不影响线上排序。
5. 可编辑、审核和发布的 Runbook 生命周期。
6. 可编辑/签署的复盘记录及保留策略。

## 19. 2026-07-26 本地实现与验收记录

M5.5–M5.7 已按本文顺序连续实现：

- `0015_m5_fleet_conversation` 增加严格第五种 `fleet` scope、组织级单会话约束、不可变 Fleet 快照和 `fleet_snapshot` 引用；引用到快照的外键为 `ON DELETE SET NULL`，墓碑保留标签、时间与哈希。
- Fleet 轮次创建时先在 PostgreSQL `REPEATABLE READ` 事务中持久化 counts 和有界 source IDs，再异步运行 Provider；Provider 只读取该快照的 counts/IDs，不重新计算 live 聚合，引用落库前仍按组织和快照摘要二次校验。
- `0016_m5_conversation_feedback`、事件统一历史、确定性相似事件和反馈 PUT 已落地；反馈脱敏后保存，不进入 Provider、权限或在线排序。
- `0017_m5_runbook_drafts`、只读复盘和不可执行 Runbook 草稿已落地；草稿仅从已完成答案中的建议及真实 citation 行派生，保存 citation 行 ID。读取时重新查询，缺失、跨作用域或已墓碑引用只显示“引用已失效”，不渲染来源正文。
- Runbook 来源轮次、事件和服务使用组织复合外键；来源删除时仅将来源列 `SET NULL`，草稿自身 `organization_id` 与不可执行审计内容继续保留。
- API 使用 `/api/v1/...`；Web 写代理执行同源校验。三个功能开关分别为 `CONVERSATION_FLEET_CHAT_ENABLED`、`CONVERSATION_INSIGHTS_ENABLED`、`CONVERSATION_REVIEW_ENABLED`，均默认 `false`。

本地门控结果：API `199 passed, 8 skipped`，Web `67 passed`，Ruff、Python compile、ESLint、Next.js production build、全部 Go 包与 `go vet` 通过；隔离 PostgreSQL 16 完成空库升级、`0014 -> 0017 -> 0014 -> 0017` 往返、应用 schema check 和 8 项 M5 PostgreSQL 门控。测试证明快照摘要覆盖候选 source IDs、跨组织数据不进入 Fleet 快照、恶意证据不能触发写操作、Operation/Transition 计数不变、快照引用 `SET NULL` 墓碑、Runbook citation 删除墓碑，以及来源轮次删除后的组织审计保留。

M5.5-7 已完成 Claude 审计、提交推送（`c08e54b` + 离线守卫修复 `a5208e7`）和三片独立生产金丝雀（2026-07-26 通过）。未修改 Go Agent、M4 协议、状态机或生产策略。**M5 诊断与操作会话体验标记为完成。**


## 19. 已知技术债

- `0006_m4_safe_operations` 迁移从空基线执行完整 `upgrade head --sql` 离线预览时，其检查逻辑会在 `MockConnection` 上失败（与 0015-0017 的 P0 同类问题）。这不阻塞当前生产升级（`0014 -> 0017` 的离线预览已验证通过）或 M5 完成，但「所有历史迁移均支持全链离线预览」目前不能宣称成立。后续可为 0006 补 offline 守卫。
