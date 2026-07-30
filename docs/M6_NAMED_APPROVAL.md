# M6.4c 角色授权与具名 M4 审批设计

当前状态：**设计审计通过；M6.4c1 已完成本地实现与本地验证，待独立代码审计、CI 和生产
shadow 金丝雀；M6.4c2/c3 尚未实现。** M6.4b 已于 2026-07-30 通过独立审计、
四条 CI 与两阶段生产只读金丝雀；生产运行 `d847a7d`、Alembic head
`0019_m6_multichannel_notify`，Principal 两个开关已还原关闭。M6.4c 会改变 M4 写路径
的身份、授权和审计契约，必须单独实现、审计、迁移验证并取得生产金丝雀授权。

## 1. 为什么不能直接实现

当前真实代码有四个不能靠 UI 隐藏修补的缺口：

1. 所有 M4 重启、部署、回滚及会话交接计划都把 `requested_by` 和首条 Transition actor
   写死为 `local-admin`。
2. `/operations/{id}/confirm` 接受正文 `confirmed_by`；Web 代理主动注入
   `{"confirmed_by":"local-admin"}`，因此 actor 不是认证层派生值。
3. Web 容器持有 `ADMIN_API_TOKEN`。若只在新依赖旁保留这个代理，任何角色都可能继续
   经共享令牌绕过具名授权。
4. 生产 Caddy 目前只有一组 Basic Auth 用户；单一身份无法证明 maker-checker，不能把
   “创建后另点一次确认”称为两个人独立审批。

M6.4c 因此不是给现有按钮加一个角色判断，而是一个受控的身份契约、数据库审计快照、
直接写入口和并发确认切片。

## 2. 目标

1. 由服务端认证证据构造稳定、不可由请求 body 指定的具名 Principal。
2. 只对明确列出的 M4 路由增加 `operation:read`、`operation:plan`、
   `operation:approve` 三项 capability。
3. 创建者和确认者都写入不可变 Principal 快照；Transition 同步保存稳定 actor。
4. 默认强制 maker-checker：创建计划的 Principal 不能确认同一计划。
5. 完整复用 M4 的计划冻结、到期、二次预检、Ed25519 签名、nonce、领取、执行、健康
   验证和审计状态机。
6. 保留一个显式、默认关闭、不可由 Web UI 使用的事故 break-glass 路径，避免身份配置
   错误锁死管理员。

## 3. 非目标

- 不实现 SaaS、多租户、注册、邀请、计费、用户数据库、密码找回或公开登录页。
- 不在首片引入 OIDC、MFA、WebAuthn 或长期浏览器 session；Basic Auth 的限制保留为
  已知 P2，后续可替换认证适配器。
- 不给诊断、会话、通知、GitHub、服务策略、注册令牌或任意其他 POST 顺带开放角色权限。
- 不改变 Agent 协议、任务签名字段、能力策略、目标派生、幂等、nonce 或 Operation 状态。
- 不允许模型、Provider、Runbook、仓库内容、日志或自然语言声明 actor 或触发审批。
- 不自动确认、自动选择审批人、超时降级审批或自动回滚。
- 不实现 Web SSH、自由 Shell、任意命令或任意路径。

## 4. 威胁模型

| 威胁 | 影响 | 设计门 |
| --- | --- | --- |
| 浏览器伪造 Principal/header | 冒充 operator/approver | Caddy 覆盖 subject/source；API 验证仅 Caddy/API 持有的 write token |
| Web 容器伪造具名写 actor | 冒充其他用户创建或确认 | write token 不注入 Web；选定写请求由浏览器同源直达 Caddy→API |
| Web 继续使用共享管理令牌代理 | 绕过角色矩阵 | enforcement 开启后选定 M4 Web 代理停用；API 不把普通 admin-token 调用静默当角色 |
| 客户端提交 `confirmed_by` | 伪造审批审计 | enforcement 模式拒绝任何 actor 字段；确认者只从 Principal 派生 |
| 同一 Principal 自建自批 | maker-checker 失效 | 行锁事务内比较稳定 Principal ID，默认 409 拒绝 |
| 两名审批者并发/重放 | 覆盖确认者或重复排队 | `SELECT ... FOR UPDATE`；同一确认者幂等，其他确认者对已排队计划 409 |
| 旧 awaiting plan 没有具名请求者 | 无法判断是否自批 | enforcement 前要求不存在旧待确认/queued 写计划；具名模式拒绝确认无请求者快照的计划 |
| 用户名改名或复用 | 历史 actor 漂移/冒充 | 部署绑定使用稳定 `principal_id`；Operation/Transition 保存当时 display/source/role 快照 |
| 角色在计划后撤销 | 已创建/已排队计划语义不清 | 每次请求实时授权；历史快照不变；撤权不自动取消已签名任务，取消仍须显式发起 |
| CSRF/跨站 POST | 以已登录用户身份写入 | 精确 Origin 与 `Sec-Fetch-Site` 门、JSON/空正文契约、同源直达；CORS 不作为安全门 |
| break-glass 被日常 UI 使用 | 永久绕过 maker-checker | 默认关闭；Web 无入口；额外 UUID+有限原因；高优先级日志和 Transition 审计 |
| 共享 read token 被用于写 | M6.4b 信任边界升级 | 新增独立 write token；read token 永远不能满足写依赖 |
| 部分 M4 入口漏接 capability | 从会话/回滚旁路具名授权 | 路由精确 allowlist 测试覆盖所有计划入口和唯一确认入口 |
| 不可信页面脚本诱导当前用户 | 以当前真实用户执行错误动作 | 冻结计划展示、默认未勾选、到期/二次预检继续生效；承认 Basic Auth 无强用户在场证明 |

## 5. 身份与角色绑定

### 5.1 认证 subject 与稳定 Principal 分离

Caddy 认证用户名只是 `auth_subject`，不再直接作为永久写审计 ID。部署配置新增严格 JSON
绑定，示意如下；它不是秘密，不通过 Web/API 修改：

```json
[
  {
    "auth_source": "caddy_basic",
    "auth_subject": "ops-alice",
    "principal_id": "local:4bf4ab08-4da6-44bb-8607-3c87f1946012",
    "display_name": "Alice",
    "roles": ["operator"]
  },
  {
    "auth_source": "caddy_basic",
    "auth_subject": "ops-bob",
    "principal_id": "local:7c09f56b-f777-4277-99d8-8ac55b69b0ff",
    "display_name": "Bob",
    "roles": ["approver"]
  }
]
```

约束：

- `principal_id` 使用管理员生成且不可复用的 UUID 前缀 ID；改名只改 `display_name`。
- `auth_subject`、`principal_id` 都必须唯一；两个角色的 subject/ID 必须互斥。
- 第一版一个 Principal 不能同时拥有 `operator` 与 `approver`，不提供超级角色。
- write enforcement 开启时至少要有一个 operator 和一个不同的 approver；否则启动失败。
- Caddy 必须拥有两组独立凭据。现有 `CADDY_ADMIN_USER` 保留为 legacy 管理身份，但不能
  自动获得 operator/approver；具体多用户 Caddy 配置必须在 M6.4c1 先完成真实 Caddy 测试。
- M6.4b 的 read-only viewer 绑定可继续兼容；write 角色绑定启用后 `/principal` 返回稳定
  ID、实际角色与有限 capability，不把用户名当永久 actor。

### 5.2 冻结角色与 capability

| 角色 | capability | 首片权限 |
| --- | --- | --- |
| viewer | `system:read`, `fleet:read`, `event:read` | 保持 M6.4b 有限 GET |
| operator | viewer + `operation:read`, `operation:plan` | 查看 Operation，显式创建冻结计划；不能确认 |
| approver | viewer + `operation:read`, `operation:approve` | 查看并确认其他 Principal 创建的计划；不能创建 |

`operation:cancel`、`operation:policy`、`diagnostic:write`、`notification:write`、
`github:write` 等均不进入首片。角色名不能在路由中直接比较；API 只检查展开后的精确
capability。

## 6. 写请求信任链

1. 增加独立高熵 `PRINCIPAL_WRITE_PROXY_TOKEN`，只注入 Caddy 与 API，不注入 Web、
   Agent、Provider 或浏览器。
2. Caddy 在**方法+路径双重 allowlist**命中的 M4 请求上完成 Basic Auth，覆盖：
   - `X-VPS-Agent-Principal-Id`：认证 subject；
   - `X-VPS-Agent-Principal-Source=caddy_basic`；
   - `X-VPS-Agent-Principal-Write-Token`：独立 write token。
3. 所有其他路径删除 write token；M6.4b read token 不能通过写依赖。
4. Web 客户端把选定 M4 请求同源发送到 `/api/v1/...`，由 Caddy 直接转发 API；Web
   server 不读取、不转发、不持有 write token。
5. API 先验证唯一 header、write token、Origin/Fetch Metadata 和部署绑定，再检查精确
   capability；身份缺失/无效为 401，绑定或能力不足为 403，maker-checker 冲突为 409。
6. API 错误、HTML、RSC、日志和响应不得包含 read/write token、Basic Auth 或全部绑定表。

该边界防止 Web 容器单凭自身环境伪造另一个写 Principal。若 Web 页面代码被攻破，它仍
可能诱导**当前已登录用户**发起请求；Basic Auth 没有 MFA/强用户在场证明，这是首片明确
接受的残余风险，不得在文档中宣称已经达到企业 IAM 强度。

## 7. 精确路由矩阵

### `operation:read`

- `GET /api/v1/operations/{operation_id}`

### `operation:plan`

- `POST /api/v1/operations`（重启计划）
- `POST /api/v1/deployment-plans`（永久不可执行预览）
- `POST /api/v1/deployment-operations`（部署计划）
- `POST /api/v1/deployment-operations/{operation_id}/rollback`（服务端派生回滚）
- `POST /api/v1/events/{event_id}/conversation/turns/{turn_id}/restart-plan`
- `POST /api/v1/events/{event_id}/conversation/turns/{turn_id}/rollback-plan`

### `operation:approve`

- `POST /api/v1/operations/{operation_id}/confirm`

不纳入：Agent health/claim/start/complete、deploy/restart policy、cancel、注册、诊断、会话
轮次、反馈、Runbook、通知测试和 GitHub。未列入路由保持原有 legacy 管理边界，不能在
M6.4c 完成说明中声称已实现全站 RBAC。

## 8. Actor 数据模型与迁移

计划新增单一 migration：`0020_m6_named_approval`，head 仍须保持单 head。Operation 保留
现有 `requested_by`/`confirmed_by` 字段用于兼容投影，并新增：

- `requested_principal_snapshot JSON NULL`
- `confirmed_principal_snapshot JSON NULL`
- `authorization_mode VARCHAR(32) NOT NULL DEFAULT 'legacy'`

OperationTransition 新增：

- `actor_principal_snapshot JSON NULL`

快照固定包含 `principal_id`、`display_name`、`auth_source`、`auth_subject`、
`organization_id=local`、触发动作时的 `roles` 和 `capability_used`；不含密码、token、
完整 header、Basic Auth 或部署绑定全集。

规则：

- 具名计划把 `requested_by=principal_id`，并同时保存完整请求者快照。
- 具名确认把 `confirmed_by=principal_id`，保存确认者快照；queued Transition 使用
  `actor_type=principal`、稳定 actor ID 和同一快照。
- 历史行不伪造 backfill：旧 `local-admin` 行保持 snapshot NULL、mode=`legacy`。
- downgrade 在存在任何具名快照行时失败关闭，避免静默丢失审计；offline SQL 双向生成
  必须通过，revision 字符串必须不超过 Alembic `VARCHAR(32)`。
- 备份 manifest 的关键表 allowlist 不因 JSON 内容扩张；恢复/schema check 覆盖新列。

## 9. 创建与确认事务

### 9.1 创建计划

- route dependency 返回 Principal，而不是 `None`；builder 必须显式接收请求者快照。
- 所有现有服务端目标派生、预检、`active_key`、过期与 conversation source 规则原样复用。
- 请求 body 不接受 principal、role、actor、approver、digest 之外的新增身份字段。
- operator 创建的计划最多到 `awaiting_confirmation`；Provider/模型仍不能调用它。

### 9.2 确认计划

在现有 `SELECT ... FOR UPDATE` 事务中按顺序执行：

1. 验证 approver capability 和具名模式；
2. 验证 Operation 存在、可执行、仍在有效状态；
3. 要求请求者快照存在且组织为 `local`；
4. 比较稳定 Principal ID，不同才继续；相同返回
   `409 maker_checker_same_principal`，不写 Transition、不签名；
5. 重新执行现有 M4 precheck；
6. 保存确认者快照、nonce、签名与 queued Transition；
7. 提交后继续由 Agent 按现有协议领取、执行和健康验证。

同一 approver 对已经 queued 的请求可获得幂等 200；另一 approver 重放返回
`409 operation_already_confirmed_by_other_principal`，不能覆盖首个确认者。过期、失败、
已领取或完成状态继续使用既有拒绝语义。

enforcement 模式的确认正文必须为空；`confirmed_by` 等任何 actor 字段返回 422。feature
关闭时 legacy 契约保持到 M6.4c 完成并经过弃用窗口，不能在同次发布中无提示硬删外部 CLI。

## 10. Legacy 与 break-glass

- `PRINCIPAL_WRITE_CONTEXT_ENABLED=false` 且
  `PRINCIPAL_WRITE_AUTHORIZATION_ENABLED=false` 时，现有 `ADMIN_API_TOKEN` 行为完全不变。
- authorization 不能在 context 关闭时开启；启用前 preflight 要求无 `awaiting_confirmation`
  或 `queued` 的 legacy Operation。
- enforcement 开启后，选定 M4 路由不再把普通 `ADMIN_API_TOKEN` 静默视为 operator 或
  approver，现有 Web `/console/...` M4 写代理必须停用。
- 事故路径另设 `PRINCIPAL_BREAK_GLASS_ENABLED=false`。启用后还必须同时提供管理令牌、
  UUID 请求键和 1–256 字符有限原因；Web/PWA 无该 header、表单或按钮。
- break-glass 允许在事故中绕过角色和 maker-checker，但每次必须保存
  `authorization_mode=break_glass`、actor `break-glass:local-admin`、有限原因与高优先级日志；
  不得自动开启、永久开启或静默回退。
- 管理令牌轮换、禁用 break-glass、恢复旧 flags 和验证 `/healthz`/数据库 head 构成锁死
  恢复手册；M6.4c 金丝雀不得删除现有令牌。

## 11. 配置与默认关闭

候选配置名：

```text
PRINCIPAL_WRITE_CONTEXT_ENABLED=false
PRINCIPAL_WRITE_AUTHORIZATION_ENABLED=false
PRINCIPAL_WRITE_PROXY_TOKEN=
PRINCIPAL_ROLE_BINDINGS_JSON=[]
PRINCIPAL_BREAK_GLASS_ENABLED=false
```

校验必须拒绝：read Principal 未开启、write authorization 无 context、短/占位/复用 read
token、空角色、重复 subject/ID、非法 UUID、角色重叠，以及没有不同 operator/approver。
API 启动校验负责绑定与 token 约束；它不能读取 Caddy 密码哈希，因此“生产至少两组可验证
凭据”必须由部署 preflight 和真实 Caddy 集成测试失败关闭。配置变化需要显式重建
Caddy/API；不能只 reload 配置后假定容器环境已更新。

## 12. API / Web / Caddy / Agent 职责

| 层 | M6.4c 负责 | 仍然禁止 |
| --- | --- | --- |
| Caddy | 多个独立凭据；写路由方法+路径 allowlist；覆盖身份并注入 write token | 决定角色、接收客户端 actor、把 write token 发给 Web |
| Web client | 展示当前 Principal/角色/创建者/确认者；同源直达选定 API；保留核对+勾选+在线门 | 保存 token、提交 actor、替服务端决定 maker-checker |
| Web server | SSR 只读展示；feature off 时兼容旧页面 | enforcement 时用 `ADMIN_API_TOKEN` 代理选定 M4 写路由 |
| API | 验证证据、绑定稳定 Principal、执行 capability、Origin、maker-checker、快照和 break-glass 审计 | 信任裸 header/body actor、自动授权、改变 M4 目标或状态机 |
| Agent | 无变化，继续验证签名任务并出站领取 | 认识用户/角色、接受浏览器身份、绕过能力策略 |

## 13. 分阶段实施顺序

### M6.4c1：多 Principal 写上下文 shadow

- 多 Caddy 凭据、稳定角色绑定、独立 write token、方法+路径 allowlist。
- 新 migration 与 actor 快照 schema。
- `/principal` 展示角色/capability；只计算 write 授权决定，不改变任何 M4 允许/拒绝结果。
- 真实 Caddy 测试证明 Web 容器没有 write token、伪造 subject 被覆盖、公共/Agent 路径清除。

### M6.4c2：具名计划创建

- 接入 `operation:read` 与所有冻结的 `operation:plan` 路由。
- builder 统一接收请求者 Principal，Web 选定请求改为同源直达 API。
- operator 可创建、approver/viewer 拒绝；计划仍停在 `awaiting_confirmation`，不签名执行。

### M6.4c3：具名确认与 maker-checker

- 确认正文空契约、`operation:approve`、请求者/确认者分离、并发与幂等语义。
- break-glass 默认关闭并完成锁死恢复演练。
- 只在 c1/c2 证据通过后进行一次低影响 M4 完整执行金丝雀。

不建议把 c1–c3 合成一个不可观察的大提交；可以连续本地实现，但必须分别有测试门和
生产阶段门。

## 14. 测试矩阵

- **配置：**所有开关蕴含关系、token 独立性、绑定格式/唯一性/角色互斥、双凭据要求。
- **Caddy：**真实容器验证多用户、身份覆盖、write token 仅到 API、方法+路径 allowlist、
  Agent/webhook/download/health 清除；Web echo 永远看不到 write token。
- **API 路由矩阵：**viewer/operator/approver/无身份/伪造身份/admin/break-glass 对每个精确
  GET/POST 的 allow/deny；未列入路由不被误接。
- **Origin：**缺失、跨站、错误 host/proto、非 JSON、actor body、重复 header 全部失败关闭；
  明确的 CLI break-glass 使用独立契约。
- **actor：**改名/撤权后历史快照不变；旧行保持 legacy；响应不含 token/绑定全集。
- **maker-checker：**同人拒绝、两 approver 并发仅一个落库、首人幂等、他人重放 409、
  legacy plan 拒绝、过期/预检变化/签名缺失保持原语义。
- **M4 全回归：**重启、部署、回滚、会话交接；签名、nonce、claim、start、complete、健康
  验证、显式回滚和 active-key 均不变。
- **PostgreSQL：**`0019 -> 0020 -> 0019 -> 0020`、offline 双向 SQL、空库、已有 legacy
  数据、具名快照、downgrade 有数据失败关闭和并发事务。
- **Web/PWA：**角色只影响按钮展示但 API 才是安全门；确认默认未勾选、离线禁用；无 actor
  body、无 admin/write token；移动审批同一契约。
- **零越权副作用：**403/409 不增加 Operation/Transition、不签名、不生成 nonce、不被
  Agent 领取；日志和 HTML 无凭据。
- **全量：**API/Web/Go/Ruff/ESLint/build/Compose/Caddy、Source Distribution、REUSE、
  dependency licenses 与单 Alembic head。

## 15. P0 / P1 / P2

### P0

- write token 注入 Web，或 selected M4 Web 代理继续用共享 admin token 绕过角色。
- actor 仍可由 body/header 自报，或请求者/确认者快照在同一事务外写入。
- maker-checker 只在 UI 判断，或 queued 并发/重放可覆盖确认者。
- 只改直接 Operation 路由而遗漏部署、回滚或会话交接旁路。
- enforcement 允许确认 snapshot 为空的 legacy plan，或迁移/downgrade静默丢审计。

### P1

- Caddy 仍只有一组真实凭据，却把测试中的双 Principal 宣称为生产团队能力。
- Origin/Fetch Metadata 不严格，Basic Auth 会话遭跨站写请求。
- role binding 改名/复用导致稳定 ID 漂移；撤权后历史从实时配置渲染。
- break-glass 可被 Web 使用、无原因/请求键/高优先级审计或静默常开。
- `confirmed_by` 硬切破坏现有 CLI，却没有 feature-off 兼容和弃用说明。

### P2

- Basic Auth 没有 MFA、良好注销、单设备撤销或强用户在场证明。
- 环境 JSON 不适合大团队；角色变更需要部署。
- 首片不提供全站 RBAC；cancel、policy、诊断和其他管理写仍是 legacy 边界。

## 16. 生产金丝雀边界

1. **Phase A（flags OFF）：**部署 migration/Caddy/Web/API，确认旧行为、head、build identity、
   Agent 路由、ops/trans 和 `/healthz`；不得有在途 legacy plan。
2. **Phase B（c1 shadow）：**两个独立 Basic 用户分别核对稳定 Principal/角色；伪造 header
   被覆盖；Web/响应/日志不含 write token；不创建 Operation。
3. **Phase C（c2 plan）：**operator 对一项已启用的低影响 restart 创建计划；approver/viewer
   创建 403；计划停在 awaiting_confirmation、无 nonce/签名、Agent 不可领取；同 operator
   确认 409，随后显式取消或等到期。
4. **Phase D（c3 execution）：**再次新建计划，由不同 approver 核对并确认；完整通过现有
   M4 签名、领取、执行、健康验证和审计链。禁止自动回滚；若失败按 M4 规则处理。
5. **Phase E（还原）：**write flags 与临时能力还原关闭；是否长期启用角色模式需单独决定。
   保留审计 Operation/Transition，不删除生产数据。

生产金丝雀必须分别获得提交/推送和部署/执行授权；“开始 M6.4c”不自动授权创建、确认、
执行 Operation、修改生产凭据或启用 break-glass。

## 17. 完成定义

- c1–c3 分别通过独立审计、真实 Caddy、真实 PostgreSQL 并发、全量 CI 和授权金丝雀。
- 两个不同生产身份完成 operator 创建与 approver 确认，actor 全由服务端证据派生且历史
  快照不可随配置漂移。
- 同人自批、角色不足、伪造 header/body、跨站请求、legacy plan 和并发覆盖均失败关闭且
  无签名/nonce/Transition 副作用。
- M4 的 Ed25519、过期、幂等、claim、执行、健康验证、审计和显式回滚边界完全保留。
- 文档明确 M6.4c 只覆盖列出的 M4 路由，不虚假宣称已实现企业 IAM、全站 RBAC 或 SaaS。

## 18. M6.4c1 本地实现记录（2026-07-30）

已实现：

- 严格 `PRINCIPAL_ROLE_BINDINGS_JSON`：拒绝 malformed JSON、非数组、额外字段、错误类型、
  非 canonical UUIDv4、重复 subject/ID、空/重叠角色和缺少独立 operator/approver。
- 独立 `PRINCIPAL_WRITE_PROXY_TOKEN`，API 校验其非占位、与 read token 不同；Compose 只将
  write token 注入 Caddy/API，Web 明确不接收。
- Caddy 增加 admin/operator/approver 三组凭据，以及精确 7 个 M4 POST 的方法+路径 matcher；
  命中时覆盖 subject/source/read token/write token，其他 API、Web、Agent、webhook、下载和
  health 路径清除 write token。
- `/principal` 将已绑定 subject 映射为稳定 Principal ID，展示 operator/approver 角色、有限
  operation capability 和 `write_authorization_mode=shadow`。
- 7 个冻结 POST 仅记录有限 `would_allow`/`would_deny`/`untrusted` shadow 决策；依赖顺序后
  仍执行原 `require_admin`，不改变写结果、body actor、签名、nonce、Transition 或状态机。
- 新增 migration `0020_m6_named_approval`：Operation/Transition actor snapshot 列与
  `authorization_mode=legacy`；历史数据不伪造 backfill，存在具名审计时 downgrade 失败关闭。
- 发布 preflight 从 Compose 解析后的配置核对三用户、三哈希、角色 subject、token 一致性和
  Web 无 write token；不输出密码哈希、token 或完整绑定。
- 真实 Caddy 测试扩展为两个角色登录、7 路由 allowlist、伪造覆盖、write token 隔离以及
  Origin/`Sec-Fetch-Site` 透传。Web 直达和 CSRF enforcement 仍按设计留在 c2。

本地结果：API `282 passed, 12 skipped`；Web `95 passed`、ESLint、production build 通过；
Ruff、单 head、0020 双向离线 SQL、Compose config、部署配置预检通过。Docker Desktop 恢复
后，真实 Caddy 多用户/7 路由/伪造覆盖/header 隔离测试通过；真实 PostgreSQL 16 完成
全迁移至 0020、备份→隔离恢复→schema check，并实证存在具名 actor snapshot 时 downgrade
失败关闭（`1 passed`）。Windows Git Bash 挂载路径兼容与 Recovery 测试新增 Caddy 必填变量
也已修复。push 后 Ubuntu CI 仍是合并与金丝雀前的必要门。当前生产仍为
`d847a7d + 0019` 且 Principal flags OFF。
