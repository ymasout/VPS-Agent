# M6.4b 可信 Principal 与有限只读角色

当前状态：**b1+b2 已由 codex 实现、Claude 审计通过（无 P0/P1/P2），提交 `4c19a45`+`d847a7d` 推送至 main，四个 CI 全绿（含真实 Caddy 集成测试），并于 2026-07-30 通过两阶段只读生产金丝雀。** M6.4a 已于 2026-07-30 以
`714da5a` 完成四条 CI 验证；M6.4b 只建立可信 Principal 上下文和有限的
只读 capability，不改变任何写权限、M4 actor、Agent 协议或生产数据模型。

## 1. 目标

1. 把“谁在访问控制台”从客户端自报字段变成服务端可验证的 `Principal`。
2. 建立与认证提供方解耦的 Principal/role/capability 类型和失败关闭依赖。
3. 先以 shadow 模式验证身份链，再只对明确列出的 GET 路由执行只读授权。
4. 为 M6.4c 的具名写操作和 maker-checker 留下稳定接口，但不提前接入写路径。

## 2. 非目标

- 不新增本地用户表、密码、登录页、session、OIDC、邀请、注册或账户恢复。
- 不声称当前单用户 Caddy Basic Auth 已经实现真正的多人团队协作。
- 不修改 `requested_by`、`confirmed_by`、Operation Transition actor 或 M4 状态机。
- 不让 viewer 创建诊断、会话轮次、反馈、草稿、通知测试、注册令牌或 Operation；这些 POST 即使业务上“只读”也会写数据库。
- 不把 `ADMIN_API_TOKEN` 在本切片中改称或改造成 break-glass；它继续保持现有 legacy 管理边界，降级和轮换属于 M6.4c。
- 不新增 Agent/VPS/GitHub 网络权限，不实现 SaaS、多租户、Web SSH 或自由 Shell。

## 3. 已审计基线

- Caddy 对 Web、管理 API 和文档使用一组 Basic Auth；认证成功后可以取得
  `{http.auth.user.id}`，但当前没有把它传给应用。
- Caddy 默认会保留大多数客户端请求 header；若不显式覆盖 Principal header，
  浏览器可以伪造身份。
- Web 通过内部 Docker 网络调用 API。普通 GET helper 当前不带管理令牌，部分
  管理 GET 和所有写代理使用共享 `ADMIN_API_TOKEN`。
- API 的 `require_admin` 只返回 `None`，没有 Principal；多数只读 GET 在应用层
  不认证，而是依赖 Caddy 外层边界。
- 生产 Compose 不把 API/Web 端口发布到宿主机，但同网络中的容器仍不能被当作
  可信身份来源。
- 当前只有一个 Caddy 用户配置，因此首片最多验证一个真实生产 Principal；测试
  可以覆盖多个身份，但不能据此宣称生产已具备多人账号。

## 4. 冻结的 Principal 模型

首片采用不可变、请求级对象，不落数据库：

```text
Principal
  id                = "caddy-basic:<normalized-user-id>"
  display_name      = authenticated Caddy username
  auth_source       = "caddy_basic"
  organization_id   = "local"
  roles             = ["viewer"]
  capabilities      = explicit finite read capability set
  authorization_mode = "shadow" | "read_enforced"
```

约束：

- `id` 由服务端拼接固定 source 前缀，不接受浏览器提交完整 ID。
- 用户名只允许稳定 ASCII 标识字符和有限长度；空值、控制字符、重复 header、
  未列入绑定配置的用户名全部拒绝。
- `display_name` 只用于显示，不作为授权键；未来改名不得改写历史审计。
- `organization_id` 在 M6.4 固定为 `local`，请求不能选择组织。
- role 只展开为显式 capability；路由不直接比较页面名或角色字符串。

首批 capability：

- `system:read`
- `fleet:read`
- `event:read`

`diagnostic:read`、`conversation:read`、`operation:read`、`repository:read` 和
`notification:read` 必须逐路由审计后再加入，不能用通配符一次开放。

## 5. 可信身份链

### 5.1 Caddy 到上游

新增独立高熵 `PRINCIPAL_PROXY_TOKEN`，只注入 Caddy、Web 和 API：

1. 对通过 Basic Auth 的 Web 与管理 API 请求，Caddy 使用 `header_up` **覆盖**：
   - `X-VPS-Agent-Principal-Id` = `{http.auth.user.id}`
   - `X-VPS-Agent-Principal-Source` = `caddy_basic`
   - `X-VPS-Agent-Principal-Proxy-Token` = 内部共享 token
2. 对 GitHub webhook、Agent API、下载与 `/healthz`，Caddy 显式删除全部
   `X-VPS-Agent-Principal-*` header，避免公共/Agent 路径携带伪造身份。
3. 不把 proxy token 写入响应、HTML、客户端 JavaScript、错误正文或日志。

Caddy [Basic Auth 文档](https://caddyserver.com/docs/caddyfile/directives/basic_auth)
说明成功认证后提供 `{http.auth.user.id}`；
[`reverse_proxy header_up`](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#headers)
的 set 语义会覆盖传入 header。实现时必须用真实 Caddy 配置测试证明该覆盖行为，
不能只靠单元测试假设。

### 5.2 Web 到内部 API

- Web 只在服务端读取 Caddy 注入的三项 header。
- Web 先用常量时间比较验证 proxy token，再接受 Principal ID/source。
- 普通只读 API helper 显式转发已验证的 ID/source，并使用 Web 自身环境中的 token；
  不直接转发未经验证的浏览器 header。
- 客户端组件、HTML、RSC payload 和浏览器网络响应不得包含 proxy token。
- 现有写代理在 M6.4b 不添加 Principal actor，也不改变 `ADMIN_API_TOKEN` 行为。

### 5.3 API 解析

- API 对三项 header 做重复计数、格式、source、共享 token 和绑定 allowlist 校验。
- 缺失/重复/无效 token 返回 401；身份合法但缺 capability 返回 403；错误正文使用
  稳定原因码，不回显 header、用户名列表或 token。
- 解析器只由明确加入的 Principal/read capability 依赖调用；Agent、webhook、健康
  检查和 M4 写路由不调用它。

## 6. 配置和默认关闭规则

候选配置名：

```text
PRINCIPAL_CONTEXT_ENABLED=false
PRINCIPAL_READ_AUTHORIZATION_ENABLED=false
PRINCIPAL_PROXY_TOKEN=
PRINCIPAL_VIEWER_IDS=
```

验证规则：

- `PRINCIPAL_READ_AUTHORIZATION_ENABLED=true` 必须蕴含 context enabled。
- 任一 Principal 功能开启时，生产环境要求非占位、高熵 proxy token 和至少一个
  合法 viewer ID；缺失时 API、Web 或 Caddy 配置校验失败关闭。
- viewer 列表是管理员部署配置，不由 Web 表单或 API 修改；重复、空项、非法字符
  均拒绝启动。
- `.env.example`、生产示例与 Compose 默认值保持关闭，不提供真实 secret。

## 7. 两个连续纵向切片

### M6.4b1：可信上下文 shadow

- 新增 Principal 类型、解析/验证依赖和受保护的 `/api/v1/principal` 有限视图。
- Caddy 覆盖/清除身份 header；Web 增加只读“当前身份”状态，但明确标注
  “shadow，不改变现有权限”。
- 只记录有限结构化事件：principal ID、source、mode 和请求关联 ID；不记录凭据、
  Basic Auth header 或 proxy token。
- 不改变任何现有路由的允许/拒绝结果，不写数据库，不改变 Operation/Transition。

### M6.4b2：有限 GET capability

- 仅对以下路由加入 feature-gated capability 依赖：
  - `/api/v1/system-info` → `system:read`
  - `/api/v1/agents`、`/api/v1/agents/{id}` → `fleet:read`
  - `/api/v1/events`、`/api/v1/events/{id}` → `event:read`
- flag 关闭时保持现有行为；开启时 trusted viewer 或现有显式管理令牌可读取，
  缺失身份/能力失败关闭。
- Web 只读 helper 转发可信上下文，使首页、移动页和详情页在开启后继续工作。
- 页面可显示“只读授权已生效”，但不得显示“写操作已禁止”；M6.4c 前写代理仍属于
  legacy 管理边界。

两个切片可连续完成本地实现，但必须分别测试；生产验证先 b1 shadow，再 b2 有限 GET，
不能一次打开全部未来 read capability。

## 8. API / Web / Caddy 职责

| 层 | 负责 | 不负责 |
| --- | --- | --- |
| Caddy | 认证、覆盖身份 header、注入内部 token、公共路径清除 | 角色/capability 决策、数据库 actor |
| Web server | 验证上游身份、只在服务端转发、展示有限状态 | 自报身份、保存密码、决定 API 授权 |
| API | 构造 Principal、绑定 role/capability、逐路由 401/403 | 信任裸 header、修改 M4 actor、创建用户 |
| Agent | 无变化 | 身份认证、团队角色、浏览器会话 |

## 9. 数据与迁移

M6.4b 计划**不新增 Alembic 迁移**，head 保持
`0019_m6_multichannel_notify`。Principal 是请求上下文，绑定来自部署配置；不新增
用户、角色、session、凭据或审计 actor 表。持久化不可变 actor ID/display-name
快照属于 M6.4c 写路径设计。

## 10. 测试矩阵

- **配置：**默认关闭；read flag 无 context、缺 token、占位 token、空/重复/非法 ID
  全部拒绝；生产示例与 Compose 一致。
- **header：**缺失、重复、大小写、空值、超长、非法字符、未知 source、错误 token、
  未绑定 ID；401 与 403 分离且不泄密。
- **Caddy：**客户端伪造三项 header 后仍被覆盖；Agent/webhook/health 路径被清除；
  Basic Auth 失败时上游不可达。
- **Web：**只在 server context 读取；错误 token 不转发；HTML/RSC/响应不含 proxy
  token；SSR 首页、移动页和详情页在 b2 开启时正常。
- **capability：**每个已纳入 GET 的 allow/deny 表；未列入的 GET 不被误标为已保护；
  所有 POST/PUT 与 M4 路由行为逐项保持不变。
- **回归：**API/Web/Go/Ruff/build/Compose/Caddy；Alembic 单 head；真实 PostgreSQL
  验证 Operation/Transition 和关键业务表计数零变化。
- **日志：**错误与结构化日志不含 Basic Auth、proxy token、管理令牌或完整 header。

## 11. P0 / P1 / P2

### P0

- Caddy 追加而非覆盖身份 header，或 API 信任未验证的浏览器 header。
- b2 把未审计的全部 GET/POST 一次接入 role，破坏 Agent/webhook/M4 路径。
- UI 把 shadow viewer 描述为已禁止写操作，形成虚假安全保证。

### P1

- Web 内部调用没有携带可信上下文，开启 b2 后页面整体 401；或为了兼容而匿名放行。
- proxy token 出现在日志、错误、HTML、RSC 或浏览器响应。
- direct API 与 Web→API 使用不同解析规则，产生绕过或权限漂移。
- Basic Auth 用户名改名/复用被误当作永久稳定的人类身份。
- 共享 proxy token 只适用于当前只读首片；若 M6.4c 继续复用它为写 actor 证明，
  Web 或同网络服务被攻破后可伪造具名写操作。M6.4c 必须重新威胁建模并采用更强
  的短期签名/会话证明。

### P2

- 环境变量绑定不适合规模化团队管理，修改需要部署。
- Basic Auth 缺少良好的注销、单人撤销、MFA 和生命周期能力。
- 首片没有持久 Principal/role 表，不能用于历史具名审计。

## 12. 生产金丝雀边界

1. 经明确授权部署时两个 flag 均保持关闭，核对 system-info、head 和现有页面。
2. 只开启 b1：核对 `/api/v1/principal` 的 ID/source/mode、伪造 header 被覆盖、页面
   不泄露 token；Operation/Transition 与业务表计数不变。
3. 再开启 b2：核对当前登录用户访问有限 GET 成功，缺失/伪造身份失败，Agent
   report/claim、GitHub webhook、`/healthz` 和现有 M4 行为不变。
4. 不创建、确认或执行 Operation；M6.4b 是只读金丝雀。
5. 验证后两个 flag 还原关闭；是否长期启用必须单独决定。不得移除或轮换现有管理
   入口，M6.4c 前也不得宣称 viewer 已受全局写限制。

## 13. 预计修改范围

- API：Principal 模块、配置、有限 schema/endpoint、选定 GET 的 capability 依赖和测试。
- Web：server-only Principal 解析/转发 helper、有限身份状态组件和测试。
- Caddy/Compose：header 覆盖与公共路径清除、默认关闭配置及校验测试。
- 文档：README、ARCHITECTURE、WEB_UI_PLAN、ROADMAP、PROJECT_STATUS 和本文。
- 不修改 Agent、M4 Operation schema/状态机、Alembic 迁移、通知通道或 Provider。

## 14. 完成定义

- b1/b2 各自通过单元、静态、构建、真实 Caddy/Compose 与 PostgreSQL 零副作用门。
- 客户端无法通过重复/伪造 header 改变 Principal；内部 token 不离开服务端边界。
- 只有明确列出的 GET capability 被执行，所有写路径和 M4 actor 完全不变。
- CI 与经授权的两阶段只读金丝雀通过，文档准确区分 shadow、有限 read enforcement
  和尚未实现的团队写授权。

## 15. 本地实现记录（2026-07-30）

- API 新增不可变请求级 Principal、`SecretStr` proxy token、用户名 allowlist、重复 header
  检测、常量时间 token 校验与 `/api/v1/principal` 有限视图。配置默认关闭；read 开关不能
  脱离 context 开关开启，短 token、占位 token、空/重复/非法 viewer 配置均启动失败。
- `system:read` 仅挂到 `/system-info`，`fleet:read` 仅挂到 `/agents` 和
  `/agents/{id}`，`event:read` 仅挂到 `/events` 和 `/events/{id}`。开关关闭时保持原行为；
  开启时可信 viewer 或现有显式管理令牌可读。POST、写代理、M4 actor/状态机均未改动。
- Caddy 对 Basic Auth 成功后的 Web/管理 API 覆盖三项 Principal header；对 GitHub
  webhook、Agent API、下载和 `/healthz` 删除三项 header。Web 仅在 server-only helper
  验证 token/source/id 后转发，首页和移动页显示 shadow/read-enforced 状态，token 不进入
  客户端组件。
- 本地 API 定向测试、Ruff、Web 95 项、ESLint、production build、Compose config 与
  `git diff --check` 已通过；本机 Docker daemon 未运行，真实 Caddy 覆盖/清除测试已加入
  Control Plane Web CI，必须在提交后 Ubuntu CI 通过后才能进入金丝雀。
- 未新增 Alembic 迁移，head 仍为 `0019_m6_multichannel_notify`。已提交推送并部署；M6.4b 生产金丝雀通过 2026-07-30（见 §16）。

## 16. 生产金丝雀记录（2026-07-30）

两阶段只读金丝雀在用户明确授权下执行并通过：

- **Phase A（flags OFF）**：部署 `d847a7d` + Caddy 新配置（header 覆盖/清除）+ 新 env vars；system-info commit=d847a7d/revision=0019；`/principal` 403（context off）；ops/trans 14/89 不变；`/healthz` 最小。
- **Phase B（b1 shadow）**：开 `PRINCIPAL_CONTEXT_ENABLED=true`；`/api/v1/principal` 返回 `id=caddy-basic:admin`、`auth_source=caddy_basic`、`authorization_mode=shadow`、`capabilities=[event:read,fleet:read,system:read]`；**发送伪造 `X-VPS-Agent-Principal-Id: forged-attacker` + valid Basic Auth，API 仍看到 `caddy-basic:admin`**（Caddy 覆盖生产实证）；响应不含 proxy token；ops/trans 不变。
- **Phase C（b2 read-enforced）**：开 `PRINCIPAL_READ_AUTHORIZATION_ENABLED=true`；mode=read_enforced；`/agents` 200、`/events` 200（Basic Auth 注入 principal，capability 通过，无需 admin token）；无 Basic Auth -> 401；`/healthz` 200；ops/trans 不变。
- **Phase D（还原）**：两 flag 还原 false；`/principal` 403。`d847a7d` 留作运行基线（flags OFF = legacy 行为）。
