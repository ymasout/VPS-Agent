# M6.4 协作与开源分发评估

当前状态：**M6.4a 已完成（`714da5a`，四条 CI 全绿）；M6.4b 已完成独立审计、四条 CI 和两阶段生产只读金丝雀；M6.4c（c1/c2/c3）已完成审计+CI+生产金丝雀（2026-07-31，含首次具名 M4 完整执行链）；M6.4d 正式发行链已建立并产出 v0.6.1（2026-08-01）、v0.6.3（2026-08-04，镜像漏洞结构性清零）、v0.6.4（2026-08-12）、v0.6.5（2026-08-13，批次 A 生产金丝雀全部通过）。** 当前状态仍不代表已经具备全站 RBAC；SaaS/多租户继续冻结。

## 1. 目标

1. 在单实例自托管边界内，让审计记录能够对应服务端认证的稳定操作者，而不是共享管理员或请求正文中的自报姓名。
2. 为只读查看、计划创建、独立审批和实例管理定义最小角色矩阵，同时完整保留 M4 的计划、确认、签名、领取、执行、健康验证和审计链。
3. 建立可公开分发源码和发布资产的法律、安全、供应链、安装升级与漏洞响应基线。
4. 先形成可验证的小切片，再决定是否继续实现多人协作；不借 `organization_id` 字段启动 SaaS 或多租户。

## 2. 非目标

- 不实现 SaaS、多租户、公开注册、邀请链接、计费、跨实例组织或云端身份中心。
- 不把 Caddy 登录、OIDC、邮箱或用户名直接等同于写权限；认证成功后仍必须经过服务端授权。
- 不允许浏览器、Provider、模型、仓库内容或请求正文指定可信 actor、角色、审批人或组织。
- 不增加自由 Shell、GitHub 写、Runbook 执行、Web SSH、实时终端或永久 Root 会话。
- 不自动确认、自动执行、自动回滚，也不因引入“团队审批”而弱化 M4 的过期、nonce、幂等、能力策略和健康验证。
- 不把已公开并带许可证的源码等同于已经具备团队身份、RBAC、正式制品或商业 SaaS。

## 3. 当前基线与真实缺口

### 3.1 身份、权限和审计

以下条目记录 M6.4 设计启动时的历史缺口，不再代表当前代码能力。M6.4b/c 已补入 default-off 的可信 Principal、有限只读 capability、具名计划/确认、actor snapshot 和 maker-checker；生产金丝雀后相关 flags 已还原关闭，因此当前生产仍保持 legacy 权限行为，启用具名 enforcement 必须重新核对配置并取得明确授权。

- 外部控制台由 Caddy Basic Auth 保护，生产 Compose 当前只配置一组 `CADDY_ADMIN_USER`/密码哈希；登录者被整体视为管理员。
- Web 服务端和 API 共享一个 `ADMIN_API_TOKEN`。浏览器不持有该令牌，但 API 只能证明请求来自共享管理边界，不能区分具体操作者。
- `require_admin` 只校验共享令牌，不返回 principal 或角色；项目没有用户、会话、角色、成员关系或凭据撤销模型。
- 数据表广泛保留 `organization_id="local"`，这是单实例一致性边界，不是已实现的租户模型。
- Operation 已保存 `requested_by`、`confirmed_by` 和 Transition actor；但当前计划创建者固定为 `local-admin`，确认接口的 `confirmed_by` 来自请求正文。该字段在单管理员模式只是标签，不能作为团队审计证据。
- 当前系统允许同一管理员创建并确认计划；“独立确认”是独立交互步骤，不等于已经实现不同人员的 maker-checker。

### 3.2 开源与发布

- 第一轮审计时缺失的 `LICENSE`、`SECURITY.md`、`CONTRIBUTING.md`、行为准则、Issue/PR 模板和第三方许可证清单已由 M6.4a 提交；GitHub 当前识别根许可证为 AGPL-3.0，Agent 范围由 REUSE 映射为 Apache-2.0。
- 根包和 Web 包均标记 `private=true`；Agent Go module 仍使用 `github.com/example/...` 占位路径。这不会阻止私有开发，但不满足正式公开发行标识。
- 只有 Agent tag Release；控制平面没有不可变发行包、正式镜像发布、升级兼容清单或统一 changelog。
- Agent Release 提供 SHA-256，但没有发布者签名、SLSA provenance 或 SBOM。Source Distribution workflow 已固定 Action commit；其余既有 Actions、基础镜像和生产 Caddy/PostgreSQL/Redis 仍以可漂移 tag 为主，尚未统一固定 digest。
- 当前跟踪文件只包含 `.env.example` 和 `deploy/.env.production.example`；真实 `.env` 已被忽略。公开源码包仍必须从 Git 索引生成，禁止直接打包带 `.env`、备份、恢复审计、构建目录或本机缓存的工作区。
- Recovery、Migrations、Web 与新增 Source Distribution 四条 CI 已覆盖关键控制平面和源码分发路径；M6.4a 已加入全历史秘密扫描、Python/Node/Go 依赖许可证门和源码 SPDX，但依赖漏洞门、容器镜像 SBOM/签名与正式控制平面制品仍待 M6.4d。

## 4. 威胁模型

| 威胁 | 后果 | 必须采用的边界 |
| --- | --- | --- |
| 客户端伪造 `confirmed_by` 或身份 header | 审计把写操作归因给错误人员 | actor 必须由服务端认证上下文派生；写请求不接受 actor 字段，边缘代理必须覆盖而非追加身份 header |
| 共享管理员凭据被多人使用 | 无法撤销单人权限、无法追责 | 共享模式只能作为 legacy/break-glass；团队模式需要独立、可撤销、稳定 ID 的 principal |
| 只做 UI 隐藏、不做 API 授权 | viewer 可直接调用写 API | 每个 API 路由在服务端按 capability/role 校验，Web 只用于展示 |
| 团队功能弱化 M4 | 越权确认、自动执行或绕过能力策略 | 角色授权只决定谁可请求/确认；M4 状态机、签名任务和 Agent 策略保持原样 |
| 删除/重命名用户破坏历史审计 | 历史记录失真或悬空 | Operation/Transition 保存不可变 actor ID 和当时显示名快照；禁用不级联删除审计 |
| 登录/session/代理配置错误 | CSRF、会话固定、header spoofing、锁死管理员 | HttpOnly/Secure/SameSite、CSRF/Origin 门、可信代理列表、紧急恢复流程和默认失败关闭 |
| 源码包夹带秘密或生产数据 | 凭据、备份、日志和审计泄露 | 只从 `git archive`/干净 checkout 生成，固定 denylist + secret scan，禁止工作区复制 |
| 依赖或构建链被替换 | 发布二进制/镜像被植入代码 | 固定依赖与 Actions commit、SBOM、checksums、签名/provenance、可重放构建证据 |
| 无许可证或依赖许可证不兼容 | 用户无法合法使用/贡献或产生合规风险 | 所有者明确选择许可证；自动生成第三方清单并设置兼容性门 |
| `organization_id` 被误用为多租户开关 | 跨组织读取或写入 | M6.4 固定单组织 `local`；不开放组织创建/选择，不把字段存在当成隔离证明 |

## 5. 角色与职责候选

以下是设计候选，不是当前已实现权限：

| 能力 | viewer | operator | approver | admin |
| --- | --- | --- | --- | --- |
| 查看机器、事件、诊断、通知状态和审计 | 是 | 是 | 是 | 是 |
| 创建诊断或固定只读会话 | 否（首片） | 是 | 是 | 是 |
| 创建 M4 待确认计划 | 否 | 是 | 可选 | 是 |
| 确认 M4 计划 | 否 | 否 | 是 | 是 |
| 修改 Agent 能力策略、服务映射和系统配置 | 否 | 否 | 否 | 是 |
| 管理成员、角色和紧急访问 | 否 | 否 | 否 | 是 |

首版不得把角色直接编码成页面名称判断。API 应校验有限 capability，例如 `fleet:read`、`diagnostic:create`、`operation:plan`、`operation:approve`、`instance:admin`。是否强制“创建者不能审批自己的计划”必须成为实例级明确策略，默认值、紧急例外和审计语义需在写路径实现前单独确认。

## 6. 身份方案评估

### 6.1 不接受：继续共享身份并允许客户端填写姓名

改动最少，但没有可信归因和独立撤销能力，不能作为团队协作实现。

### 6.2 候选 A：应用内本地账号与服务端 session

- 优点：单实例、离线可用、角色和撤销语义清晰，不依赖外部身份服务。
- 风险：项目必须负责密码哈希、session、CSRF、恢复码、锁定和升级安全，认证攻击面显著增加。

### 6.3 候选 B：可信反向代理/OIDC 身份

- 优点：可复用 Authentik、Authelia、Cloudflare Access 等成熟身份源，不在应用保存密码。
- 风险：必须严格限定可信代理并覆盖身份 header；Web 到 API 的身份传递需要可验证来源，不能信任浏览器自带 header；离线自托管复杂度更高。

### 6.4 建议

先实现与具体认证提供方解耦的 `Principal(id, display_name, capabilities, auth_source)` 服务端上下文和审计快照，不立即开放多人写权限。认证适配器必须另行选型；在选型冻结前，M6.4 不做用户表、登录页面或生产角色迁移。

## 7. 开源分发决策门

1. **许可证选择（已关闭）：**所有者已选择默认/控制平面 `AGPL-3.0-only` 与 Agent `Apache-2.0`，精确目录范围由 REUSE 固定。
2. **公开范围（已关闭）：**整个 monorepo 已公开，控制平面与 Agent 分许可证；第三方依赖保留各自条款。
3. **安全响应：**确定私下报告渠道、支持版本、响应窗口和不应公开提交的漏洞类型。
4. **发行身份：**确定正式仓库坐标、镜像仓库、包名、版本规则和签名主体，替换 `github.com/example/...` 等占位值。
5. **依赖合规：**生成 Python、Go、Node 和容器基础镜像的第三方组件/许可证清单，拒绝与所选许可证不兼容或来源不明的依赖。

## 8. 分阶段实施顺序

### M6.4a：可审计源码分发基线（已完成）

- 先取得许可证和公开范围的明确选择。
- 增加 LICENSE、SECURITY、CONTRIBUTING、行为准则、Issue/PR 模板、支持范围和自托管安装入口。
- 从干净 Git 索引生成源码包；CI 验证不含 `.env`、密钥、数据库、备份、恢复审计、本机构建或缓存文件。
- 增加 secret scan、依赖许可证清单、SBOM 和已有三条 CI 聚合门；先不发布控制平面镜像。

### M6.4b：可信 actor 基础（只读落地，已完成）

- 定义服务端 `Principal` 和 capability 表，不接受请求 body 中的 actor。
- 在明确列出的只读管理端点和有限身份展示中传播 server-derived actor；默认 feature flag 关闭，legacy 单管理员模式继续工作。
- 冻结认证适配器、session/代理信任和紧急访问设计后，才决定是否需要用户/凭据迁移。
- 代码前冻结方案见 [M6_PRINCIPAL_READONLY.md](./M6_PRINCIPAL_READONLY.md)：先做可信
  Caddy→Web/API shadow，再只对明确的 system/fleet/event GET 执行有限 capability。

### M6.4c：角色授权与具名 M4 审批

- 服务端逐路由执行 capability 校验；先 viewer/read-only，再 operation plan，最后 operation approve。
- `requested_by`、`confirmed_by` 和 Transition actor 全部由 principal 派生并保存不可变快照；移除客户端 `confirmed_by`。
- 如启用 maker-checker，服务端拒绝同一 principal 自批；不得自动找人、自动审批或超时后降级为共享管理员。
- 冻结设计见 [M6_NAMED_APPROVAL.md](./M6_NAMED_APPROVAL.md)：独立 write token 不进入 Web，稳定 Principal 绑定和 actor 快照保留历史，实施按 c1 shadow → c2 具名计划 → c3 具名确认分门推进。

### M6.4d：正式发行与协作收尾

- 冻结设计见 [M6_RELEASE_DISTRIBUTION.md](./M6_RELEASE_DISTRIBUTION.md)；为减少无意义切分，源码坐标、发行流水线、制品、签名、release bundle 和干净主机演练按一个连续实现批次完成，但 tag、draft、publish 与生产升级保留独立授权门。
- 发布不可变控制平面资产、checksums、SBOM、签名/provenance、升级兼容矩阵和 changelog。
- 在全新主机按公开文档完成安装→升级→备份→隔离恢复；贡献者能在干净 checkout 运行统一检查。
- 经独立审计和授权金丝雀后同步 M6 状态；Web SSH 仍留到最后独立设计。

## 9. 当前纵向切片

M6.4a/b 已完成。当前切片为 **M6.4c：角色授权与具名 M4 审批**；设计审计已通过，c1
写身份 shadow 已完成审计、CI 与生产金丝雀，c2 具名计划已完成审计、CI 与生产金丝雀
（2026-07-31），c3 具名确认/maker-checker 已完成审计+CI+生产金丝雀（首次具名 M4 完整执行链 succeeded）。原有单
Caddy 用户、共享 `ADMIN_API_TOKEN`、正文 `confirmed_by` 和硬编码
`local-admin` 不能提供可信 maker-checker。M6.4c 分为：

1. c1：至少两个独立认证 subject、稳定 Principal 角色绑定、独立 Caddy/API write token、
   actor snapshot migration 与 write-context shadow；
2. c2：只让 operator 对精确 M4 入口创建具名冻结计划，approver/viewer 失败关闭；
3. c3：只让不同 approver 确认，API 行锁事务拒绝同人自批并保留现有 M4 全链。

完整边界见 [M6_NAMED_APPROVAL.md](./M6_NAMED_APPROVAL.md)。该设计不新增 SaaS、
用户注册、OIDC、Agent 协议、自动确认/执行/回滚或 Web SSH。

## 10. 测试矩阵

- **身份：**缺失/伪造/重复 header、禁用 principal、角色变更、会话过期、CSRF、可信代理边界、legacy 模式。
- **授权：**每个角色对每类 API 的允许/拒绝矩阵；直接 API 调用与 Web UI 结果一致；UI 隐藏不能替代 403。
- **审计：**请求者/审批者来自服务端、客户端 actor 字段 422、用户改名/禁用后历史快照不变、Operation/Transition 不丢失。
- **M4：**具名 actor 之外的计划、确认、签名、nonce、过期、领取、执行、验证和回滚规则完全回归；maker-checker 策略并发下不可绕过。
- **单实例：**所有数据继续固定 `organization_id=local`，不存在组织创建、选择或跨组织 API。
- **发行：**干净 checkout 构建；源码包只含通过 denylist 与秘密门的 tracked 文件；秘密/备份/日志/缓存/symlink 负向门；SBOM、checksums、签名和 provenance 可验证。
- **许可证：**Python/Go/Node/容器依赖清单可重复生成，禁止项失败关闭。

## 11. 生产金丝雀边界

- M6.4a 源码分发门已以 CI-only 方式完成，没有部署生产、创建正式 Release 或改变仓库可见性。
- M6.4b 已完成只读生产验证，验证后 flags 已还原关闭；其 read token 不得在 M6.4c 复用为写 actor 证明。
- M6.4c 写路径按 c1/c2/c3 分阶段金丝雀：c1 只验证具名写身份 shadow 与伪造覆盖；c2 验证具名 operator 创建低影响计划且 viewer/approver 不能创建；c3 先证明 requester 自批和 viewer/operator 确认均被拒绝，再由不同具名 approver 完成既有 M4 全链。所有 actor 必须由服务端 Principal 证据核对。
- 金丝雀不得删除共享紧急入口，除非新身份路径、恢复流程和锁死演练均已通过；紧急入口的每次使用必须形成高优先级审计。
- 任何正式 Release、镜像推送或生产身份切换均需用户单独明确授权；仓库与许可证已在 M6.4a 公开落地。

## 12. 风险清单

### P0

- 项目文件或新依赖脱离 REUSE 目录映射，导致发布范围与许可证不兼容。
- 团队模式继续信任客户端 `confirmed_by`/身份 header，产生可伪造审批审计。
- 角色只在 Web 隐藏，API 写路径没有服务端授权。

### P1

- 新认证/session 引入 CSRF、固定会话、header spoofing 或管理员锁死。
- maker-checker 在并发、重放、管理员例外或 legacy fallback 下可绕过。
- 源码/镜像资产夹带 `.env`、密钥、备份、日志、数据库或私有仓库内容。
- 发布资产没有不可变版本、SBOM、签名/provenance 或可验证升级/回退说明。

### P2

- 用户改名/删除导致历史审计显示漂移；紧急访问没有清晰告警和复盘。
- Actions、基础镜像和依赖仅固定大版本 tag，供应链结果随时间漂移。
- 社区支持范围、漏洞响应、版本兼容和弃用策略不清晰。

## 13. M6.4 完成定义

- 项目所有者明确决定许可证、公开范围、正式坐标和安全报告渠道。
- 源码与发布资产可从干净 checkout 重复生成，不含秘密/生产数据，并具有依赖清单、SBOM、checksums 和发布者真实性证据。
- 如启用团队协作，所有 principal/role/capability 均由服务端认证和授权；客户端不能声明可信 actor。
- 具名计划与审批继续完整复用 M4，maker-checker 策略有明确默认值、失败关闭实现和真实 PostgreSQL 并发测试。
- 单实例 `local` 边界、SaaS 冻结、Agent 出站、能力策略、禁止自由 Shell 和禁止自动确认/执行/回滚均保持不变。
- 独立审计、CI、干净主机安装/升级/恢复演练和经授权生产金丝雀全部通过，README、ROADMAP、PROJECT_STATUS、ARCHITECTURE 与 WEB_UI_PLAN 状态一致。

## 14. 实现注意项（审计补充）

以下为独立设计审计提出的实现 watch-item，非设计缺口，但 M6.4b/c/d 实现时必须处理：

1. **`confirmed_by` 移除是 confirm 端点契约变更（M6.4c）**：M4.1/M5.3 金丝雀使用了 body `{"confirmed_by":"local-admin"}`（由 Web 代理注入）。冻结设计已选择开关隔离的过渡：feature OFF 时保留 legacy 契约；enforcement ON 时 confirmation 只接受空 body，客户端 actor 字段必须拒绝，身份仅由 Principal 派生，同时禁用 Web 管理代理对该写路由的 token/body 注入。外部 legacy 客户端的废弃窗口必须在实施文档中明确。

2. **`ADMIN_API_TOKEN` 降级为 break-glass（M6.4c）**：M6.4b 按冻结边界继续保留现有 legacy 管理入口，不能在只读首片中改名或改变语义。M6.4c 引入具名写授权时，才需明确令牌轮换流程、每次 break-glass 使用的高优先级审计告警，以及"令牌泄露后如何在不锁死管理员的前提下撤销"，并完成恢复与锁死演练。

3. **贡献者开发环境（M6.4d）**：M6.4d "贡献者能在干净 checkout 运行统一检查"隐含贡献者面向的开发环境文档。现有 `Makefile`/`compose.yaml` 存在但面向项目所有者。M6.4d 应确保贡献者指南覆盖：干净 checkout 的依赖安装（Python/Node/Go）、本地 Compose 启动、运行统一检查（API/Web/Agent/Compose/Ruff/ESLint）、以及贡献流程（分支、PR、CI 预期）。

## 15. M6.4a 完成记录（2026-07-30）

- 许可证决定冻结为目录级双许可证：控制平面、Web、文档及默认范围采用 `AGPL-3.0-only`；`apps/agent/**`、`scripts/install-agent.sh` 与 Agent Release workflow 采用 `Apache-2.0`。`REUSE.toml` 是机器可读的精确映射，`LICENSING.md` 是人类可读说明。
- 新增 `scripts/source_release.py`：审计 tracked 与待审查的非忽略文件，但正式 archive 只由干净 committed `HEAD` 的 `git archive` 生成；拒绝运行环境、私钥/常见 token、备份、数据库、日志、缓存、构建目录和 symlink，产出 commit 绑定 manifest 与 SHA-256。
- 新增 `scripts/dependency_licenses.py`：清点 Python、Node 和 Go 依赖，采用精确 SPDX 表达式白名单，未知或未批准项失败关闭；`BlueOak-1.0.0`、`ODC-By-1.0` 和 `Python-2.0` 只有在第三方通知存在时才能通过。
- 新增固定 action commit 的 `Source Distribution` CI：干净 Ubuntu checkout 运行 Gitleaks、源码负向测试、Ruff、REUSE 3.3、依赖许可证门，并产出 review-only 源码包、checksum、manifest、源码 SPDX 和依赖清单；不会自动创建 Release、推送镜像或部署生产。
- 技术来源审计见 `COPYRIGHT_PROVENANCE.md`。Git 历史只能证明提交身份与内容，不能证明雇佣成果归属、第三方转让或所有复制来源；项目所有者已于 2026-07-30 明确确认拥有或获授权许可全部项目原创内容、无已知冲突权利，并接受 `YY Home` 权利人名称与既定双许可证范围。该记录不是独立法律意见。
- 只读 GitHub 核对发现仓库在本切片实施前已经是 Public，且当时没有已提交 LICENSE；本轮没有执行可见性变更。提交后 GitHub 已识别根许可证为 AGPL-3.0，Agent 的 Apache-2.0 边界继续由目录 LICENSE 与 REUSE 映射表达。
- 独立审计发现首版 Python 清单错误扫描了解释器内所有包，导致结果随本地环境漂移；已改为从 `requirements-dev.txt`（含递归 `-r`）出发，按已安装 `Requires-Dist` 与 extras/marker 计算传递闭包，无关环境包不再进入清单；非 SPDX 长文本回退 classifier，常见非标准短名称只做精确规范化，未知项继续失败关闭。
- `ed4e584` 提交后按 CI 证据完成三轮修复：`3d62f28` 精确抑制新增测试中的两项合成 PEM；`8122dc8` 审核批准 sharp Linux 平台包的 `LGPL-3.0-or-later`；`0a47a15` 增加 clean-worktree 有限诊断；`714da5a` 忽略 Gitleaks 生成的 `results.sarif`。
- 最终 `714da5a` 的 Recovery、Migrations、Web、Source Distribution 四条 CI 全绿。Source Distribution 验证 Gitleaks、源码候选 283 文件、REUSE 278/278、依赖 421 包零拒绝、SPDX SBOM 和 archive build。该切片不含 API、数据库、Agent 或生产运行变更，无需生产金丝雀；M6.4a 完成。

## 16. M6.4b 完成记录

M6.4b 已按可信 Principal shadow → 有限 GET capability 的顺序完成。代码
`4c19a45` + Gitleaks 修复 `d847a7d` 已推送 main，四条 CI 全绿并包含真实 Caddy
header 覆盖/清除门。2026-07-30 两阶段生产只读金丝雀实证 `caddy-basic:admin`、
shadow/read-enforced、伪造 header 被覆盖、有限 GET 成功且 ops/trans 14/89 不变；验证后
flags 已还原关闭。完整证据见 [M6_PRINCIPAL_READONLY.md §16](./M6_PRINCIPAL_READONLY.md#16-生产金丝雀记录2026-07-30)。

## 17. M6.4c 设计交接

M6.4c 不能直接复用 M6.4b 的共享 read token 或现有 Web 管理代理。冻结设计采用独立且不
注入 Web 的 write token、稳定 Principal 绑定、具名 actor 快照、精确
`operation:read/plan/approve` 路由和默认 maker-checker，并把 legacy/break-glass 明确
隔离。计划 migration 为 `0020_m6_named_approval`；Agent 任务协议和 M4 状态机不变。
完整设计见 [M6_NAMED_APPROVAL.md](./M6_NAMED_APPROVAL.md)。

M6.4c 已按 c1 shadow → c2 具名 operator 计划 → c3 独立 approver 确认顺序完成。代码
`2673877` + CI 修复 `0d75342` 已推送 main，四条 CI 全绿；`0020_m6_named_approval`、精确
operation capability、actor snapshot、Origin/Fetch Metadata、行锁 maker-checker 与默认关闭
break-glass 均已落地。2026-07-31 生产金丝雀由不同 Principal 完成计划与确认，并完整复用
M4 签名、Agent 领取、固定 `docker_restart` 与健康验证进入 `succeeded`；验证后 restart 与
Principal flags 已还原关闭。完整证据见 [M6_NAMED_APPROVAL.md §23](./M6_NAMED_APPROVAL.md#23-m64c3-生产金丝雀记录2026-07-31)。
