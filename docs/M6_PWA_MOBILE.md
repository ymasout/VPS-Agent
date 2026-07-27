# M6.2 PWA 与移动端只读/审批设计

本文冻结 M6.2a 与 M6.2b 的产品和安全边界。当前状态为：**M6.2 生产金丝雀通过 2026-07-27（Phase 3 PWA + Phase 4 移动 M4 审批全链路）；M6.2 完成**。

## 1. 目标与切片

- **M6.2a：**让控制台具备可安装的 PWA 基础、可靠的离线提示和适合窄屏的只读浏览体验。
- **M6.2b：**在移动端清晰展示 M4 操作的目标、动作、风险、有效期、前置检查、执行阶段和验证结果，并提供有意图的独立确认交互。
- 复用现有 API、Web 管理代理和 M4 `plan → confirmation → signing → claim → execute → verify → audit` 闭环；不新增迁移、Agent 协议、Operation 状态或写入口。

## 2. 非目标

- 不实现推送通知、后台同步、离线写入、离线审批或自动重试 POST。
- 不实现自动确认、自动执行、自动回滚、批量审批、弱化确认或自然语言直接执行。
- 不实现 Web SSH、实时终端、自由 Shell、任意命令、任意路径或限时高风险会话。
- 不改变 Caddy/管理认证，不实现用户注册、多租户、SaaS、计费或团队角色。
- 不缓存或离线展示事件、机器、诊断、对话、操作、仓库或系统信息快照。

## 3. 当前基线与职责边界

- API 继续拥有能力策略、计划冻结、独立确认、签名、过期、nonce、幂等和 Operation 状态机。
- Web 继续通过受同源保护的 `/console/operations/{id}/confirm` 管理代理提交确认；浏览器不接触管理令牌。
- Agent 仍只通过出站连接领取签名任务，PWA/service worker 不与 Agent 建立连接。
- 移动 UI 的核对勾选只是防误触的人机交互门，不代替服务端独立确认，也不改变确认者身份和审计语义。

## 4. 威胁模型

| 威胁 | 约束 |
|---|---|
| service worker 缓存敏感响应 | 只预缓存固定公开静态资产；API、`/console`、动态 HTML 和 Next 数据均不写缓存 |
| 离线显示陈旧运维状态 | 页面导航始终访问网络；失败时只显示无业务数据的离线页 |
| 离线确认稍后自动执行 | 不注册 Background Sync；非在线状态禁用确认，service worker 不处理写请求 |
| 移动误触高风险操作 | 先展示动作、目标、风险、有效期和检查结果，再要求显式勾选并点击确认 |
| 前端篡改目标或动作 | 确认请求不携带可覆盖的目标/动作；服务端继续使用已冻结计划 |
| 跨站诱导确认 | 保留现有同源检查、服务端管理令牌和 M4 独立确认端点 |
| 安装 PWA 绕过认证 | 安装能力不改变 Caddy/管理认证；所有动态请求继续走既有保护 |
| 更新后旧 UI 冒充新版本 | service worker 仅缓存版本化静态资产，不缓存动态页面；更新激活时清理旧静态缓存 |
| 不可信日志/输出影响审批 | 输出只作为文本展示，不解释为指令，不生成自动操作 |

## 5. 缓存与离线矩阵

| 资源 | 策略 | 可离线 |
|---|---|---|
| manifest、PWA 图标、离线页 | 固定 allowlist，版本化静态缓存 | 是 |
| 页面导航 | network-only，网络失败回退静态离线页 | 仅离线提示 |
| `/api/*`、`/console/*` | network-only，不拦截写入、不缓存响应 | 否 |
| `/_next/data/*` 与动态 RSC/HTML | network-only，不缓存 | 否 |
| Operation/事件/机器/诊断/会话/仓库数据 | 不进入 Cache Storage | 否 |

service worker 不调用 `cache.put()` 保存运行时响应，不存认证头、管理令牌、响应正文或用户输入。

## 6. M6.2a 交互

- manifest 提供名称、启动路径、scope、standalone 展示模式、主题色和可 mask 的图标。
- 根布局注册 service worker，并提供移动安全区和只指向 `/mobile` 状态/机器/事件锚点的底部只读导航；该页面不呈现注册、同步、会话提交或其他写控件。
- 窄屏下卡片、表格、日志和 JSON 保持可读；按钮满足触控尺寸，信息不依赖 hover。
- 网络中断时不伪装为“最后已知正常”，而是明确提示需要重新联网获取当前状态。

## 7. M6.2b 独立审批流程

1. 服务端渲染当前 Operation 及其冻结计划。
2. 审批卡展示动作、机器/服务/环境、风险、有效期和前置检查摘要。
3. 用户勾选“已核对目标、动作、风险和有效期”；默认未勾选，确认按钮禁用。
4. 浏览器必须在线；离线时按钮禁用且不会排队请求。
5. 用户点击确认后，仅向现有同源 Web 代理发送空 POST；代理按现有规则注入本地管理员身份。
6. API 再次执行 M4 确认、过期和状态检查，签发任务；页面轮询现有状态并展示执行与健康验证结果。
7. 回滚仍须由用户从失败部署显式创建计划，再对该新计划独立确认；目标继续由服务端派生。

## 8. 测试矩阵

- manifest：scope、start URL、standalone、主题和图标完整。
- service worker：静态 allowlist 固定；不缓存 API、console、动态页面；无 Background Sync；导航失败只回退静态离线页。
- 布局：注册入口、manifest 元数据、移动导航与语义标签存在。
- 审批摘要：重启、部署、回滚动作映射及目标字段稳定。
- 审批 UI：默认未确认、按钮禁用；展示目标/风险/有效期/前置检查；离线不提交。
- Web 代理：保留同源拒绝、ID 校验、服务端管理员身份和 `no-store`。
- 回归：Web test/lint/build，API 全量测试，Agent test/vet；无迁移且 Alembic head 保持 `0017_m5_runbook_drafts`。

## 9. P0 / P1 / P2 风险

### P0：进入审计前必须关闭

- **本地已关闭：**动态 HTML、API、console、Next 数据和运维响应不得写入 PWA 缓存。
- **本地已关闭：**离线审批、Background Sync、自动确认、自动执行和自动回滚均不存在。
- **本地已关闭：**移动核对不能覆盖冻结目标/动作，确认仍复用 M4 服务端状态、过期、签名和审计门。

### P1：生产金丝雀前必须关闭

- **已关闭并通过审计：**`/mobile` 入口和底部导航不进入包含注册、同步、诊断触发或会话提交的页面。
- **已关闭并通过审计：**service worker 在 hydration 早于或晚于 window load 时均尝试注册，失败不影响在线控制台。
- **已关闭并通过审计：**审批默认禁用、离线禁用、显式核对后只发送现有空 POST；同源与管理令牌保护未改变。
- **金丝雀发现、本地已修复，待 CI/重新部署：**standalone runtime 必须复制 `apps/web/public`；Ubuntu CI 必须真实构建/启动 Web 镜像并确认 `/sw.js`、`/offline.html`、`/pwa-icon.svg`、`/manifest.webmanifest` 均可读取。

### P2：兼容与后续增强

- Caddy Basic Auth 下真实 Chrome 的 service worker install/预缓存、manifest/图标抓取和 install/standalone 必须由生产金丝雀确认；代码已显式使用同源凭据，但浏览器安装判定不能由单元测试替代。
- 真实受管理浏览器须确认静态缓存严格只有三项 allowlist、离线无动态数据，以及一条低影响 M4 审批全链路。
- 不同移动平台的安装提示和 SVG maskable 图标兼容性在目标浏览器金丝雀中记录；必要时后续补平台专用 PNG/apple-touch-icon，不扩大缓存或权限。
- 推送通知、平台 badge、更新提示和更丰富的移动筛选属于后续切片，均不得引入后台写。

## 10. 生产金丝雀边界

金丝雀必须另获用户授权，且只允许：

1. 部署指定已提交镜像，核对 `/api/v1/system-info` 的 commit/version/schema；`/healthz` 仍保持最小公开信息。
2. 在已通过 Caddy Basic Auth 的真实移动 Chrome 中确认 `/sw.js` 注册成功；其 install 预缓存严格只有 `/offline.html`、`/pwa-icon.svg`、`/manifest.webmanifest`，三项请求在认证会话中均成功。
3. 确认 Chrome 能在 Basic Auth 保护下读取 manifest/maskable 图标并提供安装；从已安装 standalone 入口启动在线只读页面。
4. 断网验证 Cache Storage 能提供无数据离线页，且缓存键和响应中没有 API、console、动态 HTML、Operation 或其他运维数据。
5. 使用专用低影响 M4 测试对象创建一次计划；确认前验证无任务领取，移动端显式核对后再确认，并观察完整执行、健康验证与审计。
6. M6.2 不新增 feature flag；回退仅回退 Web 镜像，无迁移和 Agent 变更。

金丝雀不得停止控制平面、修改生产开关、批量操作、自动确认、自动回滚或测试 Web SSH；已有 M5 只读开关保持原值。

## 11. 完成定义

- M6.2a/M6.2b 代码、测试和本文边界经独立审计，无未关闭 P0/P1。
- 本地 Web test/lint/build 与项目既有 API/Agent 回归通过。
- 经用户明确授权后，生产完成 PWA 安装/离线无数据泄露和一条低影响 M4 移动审批全链路金丝雀。
- 金丝雀通过后再同步 README、ROADMAP、PROJECT_STATUS 和本文状态；此前不得标记 M6.2 完成。

## 12. 本地验证记录（2026-07-27）

- Web：30 个测试文件、80 项测试通过；ESLint 与普通 Next.js 生产构建通过，`/manifest.webmanifest` 为静态路由，`/mobile` 为动态在线只读路由。
- API：212 项通过、9 项既有 PostgreSQL 条件用例跳过；Ruff 通过。
- Agent：`go test ./...` 与 `go vet ./...` 通过；Compose config 通过。
- 移动核对：390px 视口下 manifest、viewport-fit、安全区底栏和 44px 触控目标正确；`/mobile` 无 button/input/form 且无横向溢出；375px/390px 离线页无横向溢出。
- 安全回归：service worker 只预缓存 manifest、图标和无数据离线页，预缓存请求显式使用 `credentials=same-origin`/`cache=reload`；成功导航只刷新同一固定 allowlist，不缓存导航响应，不注册 sync/push。新增运行时事件测试实际执行 install、API/POST 旁路、在线刷新和离线回退；审批默认禁用，需显式勾选且在线，提交内容不包含可覆盖目标或动作。`navigator.onLine` 仅为 UX 防误触门，真正安全门仍是服务端 M4 重新校验。
- 无 API、迁移、Agent 协议、Operation 状态或生产配置变更；Alembic head 预期继续为 `0017_m5_runbook_drafts`。

独立源码审计于 2026-07-27 通过，当时未发现 P0/P1。审计指出 Basic Auth + PWA 安装必须由实机金丝雀验证；代码随后补充显式同源凭据、固定静态缓存刷新和 service worker 事件执行测试。Caddy 认证范围未放宽；若目标 Chrome 仍无法安装，只能在单独评审后考虑公开这三个固定静态资产，不得扩大到动态或数据路由。

## 13. 首轮生产金丝雀失败记录（2026-07-27）

- 生产页面页脚实时显示 `0.6.1 · 80b950f64f70`，manifest link、PWA 图标 link 和移动导航均已进入运行页面，证明 `80b950f` 已部署。
- 已通过 Caddy Basic Auth 的桌面 Chrome 直接访问 `/sw.js`、`/pwa-icon.svg` 和 `/offline.html`，三者均实际返回 Next.js 404 HTML；因此 Service Workers 面板没有 `/sw.js` 是正确表现，不是浏览器操作遗漏。
- 根因：`apps/web/Dockerfile` runtime 只复制 `.next/standalone` 和 `.next/static`，没有复制 `apps/web/public`。Next 生成的 manifest 路由存在，但 `sw.js`、`offline.html` 和 `pwa-icon.svg` 三个 public 资产未进入镜像。
- 金丝雀在 SW 注册前停止；未验证预缓存、安装、standalone 启动、离线回退或移动 M4 审批，不得把 Phase 3 或 M6.2 标记为通过。
- 本地修复：runtime 增加 public 目录复制；Web 测试增加 Dockerfile 断言；新增 `Control Plane Web` Ubuntu CI，真实构建/启动 standalone 镜像并请求四项 PWA 资源。
- 本地验证：Web 80 项、ESLint、普通 Next.js 生产构建通过。Docker Desktop 未运行，Windows standalone 构建受 symlink 权限限制，故 Linux 镜像门由提交后 CI 提供。
- 修复 `fa35eee` 已提交推送；`Control Plane Recovery`/`Migrations`/`Web` 三个 CI 全通过（Web CI 1m3s 真实构建镜像+启动+验证 4 资产）。
- 生产重新部署 `fa35eee` 后 Phase 3 PWA 实机金丝雀通过 2026-07-27：`/sw.js`/`/offline.html`/`/pwa-icon.svg`/`/manifest.webmanifest` 均返回 200 且 Content-Type 正确；Chrome 在 Caddy Basic Auth 下成功注册 SW、预缓存仅 3 项静态资产（Cache Storage 无 API/console/运维数据）、抓取 manifest+maskable 图标并安装、standalone 独立窗口启动 `/mobile` 在线只读正常；离线刷新只显示无数据离线页；ops/trans 前后 13/81 不变。
- Phase 4（移动 M4 审批写路径全链路）通过 2026-07-27：aliyun-VPS `m4-deploy-bad`（instance `da777ab7`）临时启用 restart，`POST /api/v1/operations` 创建 op `43191ab3`（awaiting_confirmation, risk=medium）；standalone PWA 核对审批卡（冻结目标/动作/有效期/前置检查）+ checkbox 默认未勾 + 按钮禁用 + Offline 门禁用；移动端勾选+确认触发完整 M4 链（ops 13->14 +1, trans 81->89 +8 = awaiting_confirmation->queued->claimed->running->verifying->succeeded）；还原 `restart_enabled=false`。
- M6.2 完成（Phase 3 + Phase 4 均通过）；M6 仍进行中（M6.3-M6.4 + Web SSH 待开始）。
