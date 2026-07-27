# M6 自托管产品化

本文冻结 M6 的目标、安全边界、阶段顺序和第一个可实现切片。M6 当前状态为：**M6.1 首片已由 codex 实现、Claude 审计通过（无 P0/P1；P2-1 symlink 经 ubuntu CI 确认；P3 非阻断），提交 `38b8d40` 推送至 main，并于 2026-07-27 通过生产金丝雀（在线一致性备份 + 隔离空库恢复，零生产副作用）**。本文不是后续生产操作授权；任何生产备份恢复演练或数据修改仍需用户另行明确授权。

## 1. 目标与非目标

### 1.1 目标

1. 让单实例自托管控制平面具备可验证的安装、升级、备份、恢复、版本检查和发布流程。
2. 让操作者能证明当前运行的 API/Web 代码、数据库 revision、配置基线和 Agent 版本，而不是只根据宿主机 Git HEAD 推断。
3. 让 PostgreSQL 备份具备原子成品、有限元数据、完整性校验、兼容性检查和真实恢复演练。
4. 在可靠发布与恢复基础上，再增加 PWA、移动只读/审批、更多通知通道和引导式配置。
5. 最后评估单实例内的团队协作与开源分发；这些能力不等于 SaaS 或多租户。

### 1.2 非目标

- 不实现 SaaS、多租户、外部用户注册、计费、跨租户控制平面或客户支持 SLA。
- 不允许 Web、Provider、自然语言或 Agent 自动触发数据库恢复、升级、回滚或密钥轮换。
- 不把备份恢复接入 M4 Operation；它是管理员显式执行的控制平面离线维护操作。
- 不提供自由 Shell、任意命令、任意路径或任意数据库目标。
- 不修改 M4 的确认、Ed25519 签名、过期、nonce、幂等、领取、执行、健康验证和审计闭环。
- 不自动确认、自动部署、自动回滚或把 Runbook 草稿变成可执行 Runbook。
- 第一个切片不包含远程对象存储、自动清理旧备份、跨 PostgreSQL 主版本恢复、跨任意应用版本恢复、Web 一键恢复或在线覆盖恢复。
- Web SSH、实时终端和限时高风险会话单独设计、最后实施，不进入 M6.1。

## 2. 当前基线与已有能力

### 2.1 已存在的可靠性基础

- 生产 Compose 由 Caddy、Web、API、PostgreSQL 16 和 Redis 组成；PostgreSQL、Redis 与 Caddy 数据使用命名卷。
- Alembic 是当前 schema 演进唯一入口，迁移链为单 head `0017_m5_runbook_drafts`。API 启动时校验数据库 revision，不自动迁移。
- `deploy/control-plane-release.sh` 已分离 `preflight`、`migrate`、`reload-caddy` 和 `postflight`；`postflight` 会运行 schema check、数据库感知健康检查、Agent operation 路由和映射候选检查。
- `preflight` 会生成 PostgreSQL custom-format `pg_dump` 和迁移 SQL 预览，备份目录/文件权限分别为 `0700`/`0600`，不自动删除备份。
- Agent 通过 GitHub Release 发布 Linux amd64/arm64 静态二进制、安装器和 `SHA256SUMS`；安装器校验二进制、保留身份/策略，并由 systemd 托管。
- Agent 安装后的服务具有 `NoNewPrivileges`、`PrivateTmp`、`ProtectHome`、`ProtectSystem=strict` 和有限写目录。
- API `/healthz` 会触发数据库查询；API 启动 revision 门能阻止落后或未接管的数据库运行。

### 2.2 审计确认的缺口

- 审计开始时的备份只是迁移前安全垫，没有原子成品、manifest、校验和、环境/版本绑定、自动 `pg_restore --list`、恢复执行器或真实 CI 门；M6.1 首片已补齐并于 2026-07-27 生产验证。
- 审计开始时没有通用恢复命令；M6.1 首片现提供只面向显式隔离项目和空目标的 CLI，仍禁止在线 `--clean` 覆盖。
- 审计开始时 FastAPI 和 Web 页脚都硬编码 `0.4.2-dev`；M6.1 首片已在本地改为镜像 ARG/label/runtime 身份和受保护 system-info。宿主机 Git HEAD 仍不能证明正在运行的镜像版本。
- 生产 API/Web 由本地源码构建，镜像没有统一不可变版本标签/摘要和构建 provenance；Caddy、PostgreSQL、Redis 使用 `2-alpine`、`16-alpine`、`7-alpine` 浮动标签。
- Agent 安装器从同一 Release 下载二进制和 SHA-256 文件，能发现传输损坏，但不能单独证明发布者真实性；升级会停止服务并替换当前二进制/配置，没有 last-known-good 自动回退和控制平面兼容检查。
- 审计开始时 CI 只有 Agent tag 发布和控制平面迁移接管；首片已增加真实备份恢复 PR/push 门，完整统一 CI、控制平面发布资产、SBOM 和签名仍属后续 M6.1c。
- API 测试曾读取工作区 `.env` 并被真实 GitHub 配置污染；首片已在测试入口显式中性化 GitHub 环境，同时保留“部分配置必须拒绝”的断言，仓库根目录回归通过。
- `.env.production.example` 的 M5 开关、诊断上下文预算和 M6 构建身份字段已补齐，并与生产 Compose 默认值核对。
- `/healthz` 继续只证明最小数据库感知健康；首片新增受管理认证的 system-info 展示 build/revision，后台能力和备份新鲜度仍不由公开健康端点承担。
- Web 尚无 manifest、service worker 或安装图标，当前不能按已安装 PWA 验收。
- PostgreSQL dump 包含 Agent credential hash、事件、证据、操作和审计数据，属于敏感备份；生产环境文件还包含管理令牌、Provider/GitHub/通知凭据和 M4 签名私钥，但当前没有明确的分层备份与恢复核对清单。

## 3. 威胁模型

| 威胁 | 可能后果 | 必须控制 |
| --- | --- | --- |
| 备份文件部分写入或静默损坏 | 需要恢复时才发现不可用 | 同目录临时文件、`pg_dump` 成功后 `pg_restore --list`、大小和 SHA-256 校验全部通过后原子改名 |
| 选择错误实例、数据库或环境 | 覆盖其他数据库或把测试数据恢复到生产 | 非秘密 `CONTROL_PLANE_INSTANCE_ID`、明确数据库名、目标 PostgreSQL 主版本和显式目标检查；默认失败关闭 |
| 覆盖非空数据库 | 丢失当前数据与审计历史 | 首版只允许恢复到空数据库；发现任何非系统对象即拒绝，不提供普通 `--force` |
| 应用/schema/数据库版本不兼容 | API 无法启动或数据语义错误 | manifest 记录运行版本、commit、Alembic revision、PostgreSQL major；首版只允许精确应用/revision和相同 PostgreSQL 16 major |
| 恶意或被篡改的备份/manifest | 注入错误数据库对象或伪造来源 | 只接受操作者控制目录中的普通文件，拒绝符号链接；校验 manifest schema、dump hash 和 archive list；SHA-256 只证明完整性，不宣称发布者真实性 |
| 凭据进入日志或摘要 | 管理令牌、Agent/GitHub/Provider/通知凭据泄露 | 命令不使用 `set -x`；摘要只输出固定字段、文件名、hash 和计数；不打印连接串、环境文件、SQL 正文或数据库内容 |
| 备份文件泄露 | 攻击者获得 credential hash、证据和审计数据 | 目录 `0700`、文件 `0600`；备份视为高敏感资产；首版不自动上传；离机复制必须由操作者使用独立加密存储 |
| 在线恢复与并发写入 | 部分新旧数据混合、审计丢失 | 恢复要求维护模式，停止 Caddy/Web/API 和控制面写入；只在隔离目标数据库完成后启动 API |
| 恢复成功被 `pg_restore` 退出码误判 | schema 或关键数据不完整 | 恢复后必须运行 revision/schema check、关键表计数/一致性验证和 API 健康检查；任一失败都不声明成功 |
| 旧镜像或旧脚本被误当成新发布 | 验证结果与实际代码不一致 | 版本身份嵌入构建产物并由运行时返回；备份 manifest 使用运行身份，不使用宿主机 Git HEAD 代替 |
| 远程文本或模型诱导维护操作 | 绕过管理员意图执行恢复 | 日志、仓库、Provider 输出只作为不可信数据；备份/恢复没有 Provider、Web 或 Agent 调用入口 |

## 4. 安装、升级、备份与恢复安全边界

### 4.1 控制平面安装与升级

- 安装必须使用显式版本，不以浮动 `latest` 作为可重复生产安装证明。
- 发布前必须验证 Compose/Caddy、配置完整性、数据库备份、迁移预览和目标版本身份。
- 数据库迁移保持显式单次执行；API entrypoint 继续只校验 revision，不自动升级。
- 应用回退与数据库恢复分离：应用启动失败优先回退到兼容的已知镜像；只有证明确有数据库结构/数据损坏才恢复数据库。
- 升级和回退必须有明确兼容矩阵，不能假设任意旧应用可读取新 schema，也不能把 Alembic downgrade 当作普通回退。

### 4.2 Agent 安装与升级

- 一次性注册令牌、独立 machine-id、身份文件和能力策略必须继续保留；升级不得静默扩大 evidence/operation/deploy 权限。
- 正式升级应固定 Release 版本并校验产物；`latest` 仅作为交互便利，不作为审计证据。
- 后续 M6.1 需要增加 last-known-good 二进制/配置、启动健康等待和失败回退设计；回退不得删除身份、幂等账本或 machine-id。
- 控制平面必须声明支持的 Agent 协议/版本范围；不兼容时先拒绝启用新能力，而不是让旧 Agent 领取未知任务。

### 4.3 备份

- 首片只备份 PostgreSQL；不把 `.env.production`、私钥或 Caddy 数据混入同一未加密包。
- 备份命令可对在线 PostgreSQL 执行，依赖 `pg_dump` 一致性快照；不得停止或修改 M4/M5 状态。
- 成品由 `dump + manifest.json + SHA256SUMS` 组成。manifest 仅包含固定非秘密字段：格式版本、实例 ID、UTC 时间、运行版本/commit、Alembic revision、PostgreSQL major、数据库名、dump 大小/hash 和固定 allowlist 关键表行数摘要；不允许按数据库内容动态扩展表名。
- dump 与关键表计数必须来自同一 PostgreSQL exported snapshot。在线备份可能如实包含备份开始时仍在途的 Operation；manifest 只记录固定表计数和 `active_operation_count`，金丝雀应避开计划中的 M4 操作窗口，但不能把“零在途”误当成备份正确性的前提。
- 任一导出、archive list、manifest 校验或 hash 步骤失败，临时文件必须保留为明确失败或清理，不能以正式备份文件名出现。
- 备份脚本输出有限审计摘要，不输出凭据、连接串、证据正文、操作输出或环境变量。

### 4.4 恢复

- 首片恢复只允许管理员在宿主机显式运行离线脚本，不提供 API、Web、Provider 或 Agent 入口。
- 操作者必须明确提供备份目录和目标实例 ID；脚本不得搜索并自动选择“最新”备份。
- 恢复前校验普通文件/目录边界、manifest schema、SHA-256、`pg_restore --list`、实例 ID、精确应用版本/commit、精确 Alembic revision和 PostgreSQL 16 major；目标数据库名、登录角色及所需 extension 可用性必须与来源约束匹配。
- 目标数据库必须为空；非空、未知或连接到错误 Compose 项目时立即拒绝。首片不提供在线 `--clean` 或隐式 drop/create。
- 使用 `pg_restore --exit-on-error --single-transaction --no-owner --no-privileges` 恢复；失败后目标数据库不得被当成可启动状态。
- 恢复后依次运行 revision、`app.schema check`、关键表行数/一致性校验和数据库感知健康检查。只有全部通过才生成成功摘要。
- 生产恢复演练必须先在隔离 PostgreSQL/Compose 目标完成；真实生产恢复只有在单独事故授权下执行。

## 5. 版本兼容与回退策略

### 5.1 首版兼容规则

| 对象 | M6.1 首片规则 |
| --- | --- |
| 备份格式 | `m6.1-control-plane-backup-v1`，未知版本拒绝 |
| 控制平面版本/commit | 备份与恢复工具的运行构建身份必须精确匹配 |
| Alembic revision | 必须精确等于备份 manifest；首片不在恢复过程中自动迁移 |
| PostgreSQL | source/target 均为 major 16；不承诺跨 major |
| Agent | 数据库会恢复 Agent 记录和 credential hash；各 VPS 本地身份不在控制平面备份中，Agent 重连后仍需按现有协议验证 |
| Redis | 不作为长期事实源，不从数据库备份恢复；重建后由应用重新形成缓存/协调状态 |
| Caddy | TLS/配置不属于数据库 dump；域名和 TLS 恢复按独立配置清单处理 |

### 5.2 应用回退

- 迁移前应用可直接回退到上一个已知版本。
- 迁移后只有兼容矩阵明确允许时才能回退应用；否则保留新 schema，修复前向问题。
- 数据库备份不是普通应用回退按钮。恢复数据库会丢弃备份时间点之后的状态，必须作为事故处置单独授权。
- 后续升级切片应为控制平面产物建立不可变版本、构建 commit、镜像摘要和 schema 支持范围，并在 preflight 中自动检查。

## 6. 密钥、配置和数据库备份规则

| 资产 | 是否进入数据库备份 | 规则 |
| --- | --- | --- |
| Agent credential hash、Agent/服务/事件/诊断/会话/Operation/审计 | 是 | 备份文件按高敏感数据保护；摘要只输出计数，不输出内容 |
| `ADMIN_API_TOKEN` | 否 | 由操作者在独立加密秘密存储中保管；恢复核对但不写入 manifest |
| M4 Ed25519 私钥 | 否 | 必须独立安全备份；丢失后不能继续签发新任务，不能从数据库推导 |
| Agent 侧公钥和本地策略 | 否 | 保存在各 VPS；升级/恢复不得自动改变 |
| GitHub App 私钥/Webhook Secret | 否 | 独立加密备份；数据库只恢复 binding/快照，凭据缺失时 GitHub 功能失败关闭 |
| Provider API Key、钉钉 Webhook/Secret | 否 | 独立加密备份；不得进入日志或备份摘要 |
| `deploy/.env.production` | 否 | 首片不复制进数据库包；单独加密、限制权限并记录恢复清单 |
| Caddy TLS 数据 | 否 | 可由 ACME 重建；若选择备份，必须与数据库包分离并说明敏感性 |
| Redis 数据 | 否 | 不是长期事实源；恢复后重建 |

数据库恢复完成但关键秘密缺失时，可以进行离线 schema/数据验证，但不得宣称控制平面已完整恢复。M4 签名配置缺失必须继续使确认入口失败关闭。

## 7. API、Web 与 Agent 职责边界

### API

- 提供只读、受管理认证保护的构建信息：控制平面版本、commit、构建时间、支持的 schema 和实际数据库 revision。
- `/healthz` 保持有限公开健康信息，不暴露 commit、数据库名、备份路径或秘密配置。
- 不提供备份或恢复写端点；不把恢复状态写成 M4 Operation。

### Web

- 在设置/系统信息或页脚展示服务端返回的真实 API/Web 版本、commit 和 schema 状态，明确数据采集时间。
- 首片只提供离线恢复说明和状态，不提供“一键恢复”、文件上传或数据库目标输入。
- PWA/移动审批属于 M6.2；移动端不得因为交互简化而省略 M4 独立确认、目标、风险和验证状态。

### Agent

- 不参与控制平面数据库备份或恢复，不接收备份路径、数据库凭据或恢复任务。
- 继续只通过出站连接报告自身版本/能力并领取 M4 签名任务。
- 控制平面恢复后，Agent 以原凭据重连；身份不匹配时按现有离线重绑定流程处理，不自动重注册。

## 8. M6.1 第一个纵向切片

首片冻结为：**可验证的控制平面 PostgreSQL 备份与离线恢复基础**。

### 8.1 预计修改

#### 脚本与配置

- 新增独立备份/恢复脚本和共享的安全路径/manifest 校验逻辑；不把恢复塞进 Web 或 M4。
- `deploy/control-plane-release.sh preflight` 与一次性 `adopt_database()` 都改为调用统一备份实现；`adopt` 必须继续在 `stamp head` 前保留 create_all 库备份，只有原子备份验证通过才继续。
- `deploy/compose.production.yaml`、API/Web Dockerfile 和 `.env.production.example` 增加非秘密实例 ID 与不可变构建版本/commit 注入，并补齐当前已使用的配置开关示例。
- 备份目录仍默认为 `/var/backups/vps-agent-console`，但所有目标使用已验证的绝对路径和普通文件检查。

#### API 与 Web

- API 新增受管理认证保护的只读系统版本端点；构建身份来自镜像构建参数，不从请求或宿主机工作树推断。
- Web 用该端点替换硬编码 `0.4.2-dev`，展示 API/Web build、commit、实际/期望 schema；不增加备份/恢复按钮。
- 公共 `/healthz` 保持最小响应，避免泄露内部版本和数据库信息。

#### 测试与 CI

- 脚本单元测试覆盖路径、symlink、manifest、hash、错误环境、非空目标、版本/revision/PG major 不匹配和日志无凭据。
- 真实 PostgreSQL 16 集成测试执行：迁移空库到 head -> 写入关键测试数据 -> 备份 -> 校验 archive/manifest/hash -> 恢复到新的空数据库 -> `app.schema check` -> 关键表计数和选定记录一致性验证。
- 负向集成验证：损坏 dump、篡改 manifest、非空目标、错误实例 ID、错误 revision 均失败关闭且不覆盖现有数据。
- 新增 PR/push 恢复门；完整 API/Web/Go/Compose 统一 CI 属于后续 M6.1c。测试不得访问生产或使用真实秘密。API 测试从仓库根目录执行也必须 hermetic，现有“部分 GitHub 配置必须拒绝”断言不得被删除或绕过。

#### 文档

- 更新 `deploy/README.md`、根 README、架构、路线图和项目状态；提供备份、inspect、隔离恢复演练和事故恢复的明确分界。
- 记录 manifest schema、兼容矩阵、秘密恢复清单和失败后的最短安全路径。

### 8.2 首片不修改

- Go Agent、Agent 协议和生产 Agent 策略。
- M4 v1/v2 签名任务、状态机和回滚语义。
- 数据库 schema；预计不需要 Alembic 新迁移。
- GitHub 写、Runbook 执行、Web SSH、对象存储和自动清理。

### 8.3 首片完成门

- 备份只能以验证完成的原子目录/文件组出现，manifest 和 SHA-256 可复核。
- 恢复默认拒绝错误实例、错误版本/revision/PG major、非空数据库、symlink 和损坏包。
- 真实 PostgreSQL 16 的备份→新空库恢复→schema check→关键数据一致性闭环可重复通过。
- stdout/stderr、测试日志和摘要不包含数据库连接串、管理令牌、Agent/GitHub/Provider/通知凭据或证据正文。
- API/Web 展示的运行 commit 与实际构建产物一致，不再硬编码 `0.4.2-dev`。
- 没有新增 Web/API/Provider/Agent 恢复入口，没有改变任何 M4 Operation/Transition。
- 本地实现、独立审计和用户确认均已完成；提交 `38b8d40` 后生产金丝雀只做了新备份和隔离恢复验证，未对现有生产数据库执行覆盖恢复。

## 9. 测试矩阵

| 层级 | 必测内容 |
| --- | --- |
| 静态/契约 | Shell 语法与 lint、manifest 严格 schema、API/Web 类型、Compose config、Caddy validate |
| API/Web | 构建信息认证、实际/期望 revision、硬编码版本移除、错误/不可用状态、公共 health 不泄露内部信息 |
| 备份正向 | custom dump、archive list、原子改名、权限、大小/hash、manifest、有限行数摘要 |
| 恢复正向 | 空 PostgreSQL 16、single transaction、schema check、关键表计数/选定数据一致 |
| 恢复负向 | 非空目标、错误实例、版本/commit/revision/major 不匹配、损坏 dump/hash、symlink、未知 manifest 字段 |
| 安全 | 日志无 secret/URL query/正文；Provider/Web/Agent 无恢复入口；Operation/Transition 数量不变 |
| 回归 | API pytest、Web Vitest/ESLint/build、Go test/vet、开发/生产 Compose、Alembic head/schema check |
| 真实集成 | 临时 PostgreSQL/Compose；所有容器、卷和测试凭据隔离，完成后只清理明确的临时目标 |

## 10. 生产金丝雀边界

只有用户再次明确授权后才能执行：

1. 先确认生产当前运行版本、commit、Alembic revision、Provider 和功能开关；部署后显式调用新的受管理认证 `system-info`，核对返回 commit 与所构建镜像一致，同时确认公开 `/healthz` 仍只返回最小健康信息；不使用本文件中的历史值代替实时检查。
2. 在没有计划内 M4 Operation 执行的时段只执行一次新的在线一致性备份，验证 manifest、hash、archive list、权限和日志；备份仍允许如实捕获偶发在途状态，不修改生产数据。
3. 把备份复制到隔离、临时 PostgreSQL 16 目标，使用空数据库执行恢复。
4. 对隔离目标运行 schema check、关键表计数/一致性核对；不得让生产 Agent 连接该隔离控制面。
5. 核对生产 Operation/Transition、Agent 策略、GitHub binding 和 Provider 配置没有非预期变化。
6. 保留有限审计摘要；不得记录或回显备份正文、连接串和秘密。
7. 金丝雀不授权停止生产控制面、不授权覆盖生产数据库，也不授权自动删除旧备份。

真实生产数据库恢复只在事故处置中、基于指定恢复点和单独授权执行，不属于正常 M6.1 金丝雀。

## 11. 分阶段实施顺序

1. **M6.1a 运行身份与备份包**：构建版本/commit、系统信息端点、原子 dump、manifest、hash、archive 校验。
2. **M6.1b 严格离线恢复**：空目标门、兼容性门、single-transaction restore、schema/关键数据验证和真实 PostgreSQL CI。
3. **M6.1c 发布与升级可靠性**：不可变控制平面镜像、依赖镜像固定、统一 CI、Agent last-known-good 升级/回退和版本兼容矩阵。
4. **M6.1d 秘密与灾备运行手册**：配置/密钥清单、加密离机副本、恢复演练频率、RPO/RTO 和人工审计。
5. **M6.2 PWA 与移动体验**：manifest/service worker/图标、移动只读事件与 M4 审批；不新增写权限。
6. **M6.3 通知与引导式配置**：统一通知适配器、模板、测试消息、失败/重试和秘密不回显。
7. **M6.4 协作与开源评估**：先定义单实例本地身份、角色、审批 actor 和分发安全基线；SaaS 继续冻结。
8. **最后阶段：Web SSH/实时终端/限时高风险会话**，单独威胁建模和验收。

## 12. P0 / P1 / P2 风险清单

### P0：M6.1 恢复代码前必须关闭（首片本地已关闭，待独立审计）

1. **本地已关闭：**恢复执行器和真实恢复门已落地，不再把 `pg_dump` 存在等同于可恢复。
2. **本地已关闭：**build/commit/schema 身份来自镜像参数和受保护端点，不使用宿主机 Git HEAD 代替。
3. **本地已关闭：**备份使用原子成品、严格 manifest、hash、archive 校验和实例/版本绑定。
4. **本地已关闭：**恢复默认拒绝非空数据库、错误实例、错误版本/revision/PG major 和 symlink/损坏包；Linux symlink 负向用例将在新增 CI 首次运行时再确认。
5. **设计与代码已关闭：**配置/密钥与数据库责任分层，恢复摘要不声明数据库包以外的秘密已恢复。
6. **代码已关闭：**备份/恢复只有管理员宿主机 CLI，没有 Web、Provider、Agent 或自然语言入口；日志和摘要只含固定非秘密字段。

### P1：M6.1 完成前关闭

1. **本地已关闭、CI 待首次运行：**真实 PostgreSQL 备份→恢复→schema/关键数据一致性工作流已通过，并已加入 PR/push 门。
2. **部分关闭：**构建身份已强制显式注入；完整控制平面 CI、不可变发布镜像和生产依赖镜像固定仍在 M6.1c。
3. **仍开放：**Agent last-known-good、失败回退和协议兼容矩阵属于 M6.1c。
4. **本地已关闭：**`.env.production.example` 已补齐 Compose 的诊断预算、M5 开关和 M6 build 身份字段，Compose config 通过。
5. **本地已关闭：**测试入口已隔离工作区 GitHub 环境，仓库根目录回归保留部分配置拒绝断言并全绿。
6. **仍开放：**备份加密、离机副本、真实性/签名策略、RPO/RTO 和定期恢复演练运行手册属于 M6.1d。
7. **部分关闭：**公开 health 与受保护 build/schema 信息已分离；后台能力和备份新鲜度仍待后续状态设计。

### P2：后续产品化增强

1. 对象存储、保留策略、自动轮换和备份状态通知。
2. 控制平面镜像签名、SBOM、provenance 和漏洞扫描。
3. PWA 离线壳、推送与移动审批可用性。
4. 更多通知通道、模板市场和引导式接入。
5. 团队协作、个人 actor、RBAC 与双人审批评估。
6. Web SSH/实时终端和限时高风险会话。

## 13. M6 完成定义

M6 只有在以下条件全部满足后才可标记完成：

- 控制平面和 Agent 有可重复的固定版本安装、升级、兼容检查、失败回退和审计流程。
- PostgreSQL 备份、配置/密钥清单、隔离恢复和真实演练满足已定义 RPO/RTO；不能只证明 dump 命令成功。
- 当前运行的 API/Web/Agent/数据库 revision 可从产品和发布资产中准确核对。
- PWA 与移动端只读/审批体验不弱化 M4 的确认和验证边界。
- 新通知通道复用统一的秘密、脱敏、去重、重试和恢复语义。
- 团队协作若进入范围，actor 身份、权限和审计语义已明确；否则明确留在后续。
- Web SSH/高风险会话若未完成独立安全门，必须继续标记为未实现，不能阻塞其他已冻结的 M6 子阶段，也不能被偷渡进产品化范围。
- API/Web/Go/Compose/迁移/备份恢复测试、独立安全审计和经授权生产金丝雀均通过，文档与实际运行状态一致。
- SaaS、多租户、注册、计费和跨租户控制平面仍保持冻结。

## 14. 2026-07-27 生产金丝雀记录

M6.1 首片生产金丝雀在用户明确授权下执行并通过：

- 部署：生产 `git pull` `5d0fab9 -> 38b8d40`，`docker compose build api web`（注入 build version/40 位 commit/UTC build time），`preflight`（生成新原子备份包 `control-plane-pre-migration-20260727T131115Z` + 迁移 SQL 预览）、`migrate`（no-op，head 仍 `0017`）、`up -d`、`reload-caddy`、`postflight` 全部通过。
- 构建身份：`/api/v1/system-info`（受管理认证）返回 `commit_sha=38b8d40e76ea1c30497bbfa0f17d2b87aaa27977`、`version=0.6.1`、`instance_id=ops-ymast-shop`、`schema_current=true`、`alembic_revision=expected=["0017_m5_runbook_drafts"]`；公开 `/healthz` 仍只返回 `{"status":"ok","service":"api"}`。
- 备份包 inspect：`backup manifest is compatible` + `checksum, archive and compatibility checks passed`。
- 隔离恢复：`COMPOSE_PROJECT_NAME=vps-agent-restore-canary-*`、`RESTORE_ISOLATED_TARGET=yes`、`RESTORE_CONFIRM_INSTANCE_ID=ops-ymast-shop`、空目标 -> `restore target is empty and compatible` -> `pg_restore --exit-on-error --single-transaction --no-owner --no-privileges` -> `database revision and schema match the application`；审计摘要 `schema_current=true`、`key_table_counts_match=true`、`active_operation_count=0`。
- 数据一致性：恢复后 `ops=13/trans=81/agents=5`，与生产基线一致。
- 零生产副作用：生产 `ops/trans` 前后均 `13/81` 不变；M5 开关与 Provider 未变；生产 api 日志无连接串/令牌/密码/dump 正文。
- 收尾：隔离恢复项目（容器/卷/镜像）已清理；首份 M6.1 原子备份包保留于 `/var/backups/vps-agent-console/`（0700/0600）。

M6.1 无 feature flag（构建身份 always-on，backup/restore 为 CLI 工具），新代码 `38b8d40` 留作生产运行基线；若需回退则代码回滚到 `ff4f5bc`（无迁移，DB 不受影响）。M6.1 首片完成；下一阶段 M6.2 PWA/移动审批。
