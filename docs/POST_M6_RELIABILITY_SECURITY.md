# M6 后续可靠性与公开发行安全加固设计

状态：**设计冻结，尚未实现。** M6 已于 2026-08-02 收口；本文保留 M6.1c/M6.1d 名称只为延续既有追踪，
不重新打开 M6，也不把以下缺口描述为已完成。任何提交、推送、正式发行、生产升级、生产备份或恢复仍需分别授权。

审计基线：仓库 `main`/`784365a4a97e737ac52839a05f952d286b03313c`；v0.6.1 tag/运行制品 commit
`8746182c5dcd357f7d17f3b9140302d117945354`；生产 API/Web 为 digest-pinned v0.6.1，数据库 revision
`0020_m6_named_approval`，Principal flags OFF。生产状态会变化，实施或金丝雀前必须重新核对。

## 1. 目标与范围

后续工作尽量合并为两个实现批次：

1. **批次 A：M6.1c + 公开发行安全加固。** 完成 Agent last-known-good 安全升级/失败回退、生产对已签名
   release bundle 的验证与暂存，以及依赖/源码/OCI 持续漏洞扫描和发行证明回归。
2. **批次 B：M6.1d 灾备闭环。** 建立数据库、配置、密钥、Caddy 状态和 Redis 的权威性分类，生成加密离机副本，
   冻结 RPO/RTO，完成隔离恢复演练与有限审计摘要。

两个批次可连续实现并统一做本地/CI 审计，但生产门必须分开：Agent 升级金丝雀、控制平面 bundle 升级金丝雀、
灾备只读/隔离恢复演练不能合并成一次授权。

## 2. 非目标与既有安全边界

- 不增加 Web/API/Provider 触发主机升级、数据库恢复、密钥导出或 release 发布的入口。
- 不实现自动生产升级、自动数据库恢复、自动应用回滚或无人值守 Agent Fleet 批量升级。
- Agent 升级不得新增或扩大 evidence、restart、deploy capability；普通升级必须逐项保留既有策略。
- Agent 的本地失败回退只恢复安装器刚替换的二进制、配置和 systemd unit，不是 M4 应用回滚，不能创建或确认 Operation。
- 不回退 Agent identity、machine-id 或 operation ledger，避免身份漂移和已执行任务重放。
- release workflow 不获得生产凭据；候选、公开发布和生产部署继续是三份独立授权。
- 灾备脚本不接受任意路径、任意命令、在线数据库覆盖或 `--force`；真实生产恢复仍是事故级单独授权。
- Web SSH、实时终端、SaaS、多租户、注册、计费和 GitHub 写继续不在范围内。

## 3. 真实基线与已确认缺口

### 3.1 已存在能力

- `scripts/install-agent.sh` 会校验 `SHA256SUMS`，对 v0.6.1+ 固定 Sigstore certificate identity/issuer 验证 Agent 二进制，
  并保留既有身份和策略配置。
- v0.6.1 release bundle 已确定性生成 `deploy/release/images.env` 和 `release-manifest.json`，五个运行镜像均为精确 digest；
  bundle、checksum 和 manifest 均有签名资产。
- `deploy/control-plane-backup.sh` 生成原子 PostgreSQL dump/manifest/SHA256SUMS，并与版本、commit、实例、revision、
  PostgreSQL major 和固定关键表计数绑定；隔离空库恢复已通过真实生产备份演练。
- Source Distribution 已执行 Gitleaks、REUSE、依赖许可证和源码 SBOM；Formal Release 已生成 Agent/OCI SBOM、
  Sigstore keyless bundle、OCI provenance，并验证候选镜像签名。

### 3.2 真实缺口

- Agent 安装器当前在验签后直接 `systemctl stop` 并覆盖 `/usr/local/bin/vps-agent`；没有进程锁、previous generation、
  启动稳定性门或失败自动恢复。配置和 unit 也会在成功证明前被覆盖。
- 安装器只证明目标二进制来自受信发行者，不校验“当前版本 → 目标版本”升级路径是否在兼容矩阵内。
- v0.6.1 生产金丝雀手工生成了宿主机 `deploy/release/images.env`，没有从已签名 bundle 自动验证、解包并暂存；
  发行资产本身不缺该文件。
- PostgreSQL 包不包含 `.env.production`、M4 私钥、Principal token、GitHub/Provider/通知凭据或 Caddy 状态；目前没有
  加密离机副本、恢复点目录、保留规则、量化 RPO/RTO 或定期完整演练。
- Redis 只用于 GitHub webhook 共享限速计数，属于可重建的暂态状态；其 AOF 卷不应被误称为权威灾备数据。
- 当前 CI 没有 Dependabot、CodeQL、OSV/同类依赖漏洞门或 OCI 漏洞扫描；现有 SBOM、许可证和签名不能证明制品没有已知漏洞。

## 4. 威胁模型

### 4.1 Agent 升级

- 下载中断、签名/校验通过后磁盘写失败、断电或并发运行两个安装器，造成部分替换。
- 新二进制能输出版本但无法稳定启动、读取旧配置、连接控制平面或声明原 capability。
- 恶意或误操作升级到不支持的版本，或普通升级静默启用 restart/deploy 能力。
- 回退恢复旧 identity/ledger，导致重复注册、nonce/幂等状态漂移或任务重放。
- previous generation 中的 `agent.env` 泄露 credential、公钥策略或本地允许路径。

### 4.2 灾备

- 只有数据库 dump，却丢失 M4 私钥、管理/Principal token、GitHub App 私钥或通知/Provider 凭据，恢复后服务无法安全运行。
- 明文备份被窃取；备份篡改、截断、版本错配或拿错实例；恢复演练只检查命令退出码。
- 将 Redis/Caddy 暂态状态误当作数据库权威状态，或把旧密钥恢复到仍在运行的原实例造成双活。
- 备份/恢复日志泄露环境变量、连接串、Webhook、token、私钥或数据库正文。
- 未定义 RPO/RTO 和演练频率，事故时才发现离机副本过期或解密私钥不可用。

### 4.3 公开发行

- 已签名产物仍包含已知高危依赖/基础镜像漏洞；SBOM 与实际 digest 不一致。
- 扫描器、Action 或规则使用漂移版本；不可信 PR 获得写权限、OIDC 或包凭据。
- 漏洞 allowlist 无负责人/截止时间，永久掩盖风险；扫描输出泄露私有路径或秘密。
- candidate 扫描失败后仍提升 SemVer 或公开 Release；已发布不可移动坐标被“修复性覆盖”。

## 5. 批次 A：M6.1c Agent 与 release 安全

### 5.1 Agent 事务式升级

安装器增加单机互斥锁，并按以下固定顺序执行：

1. 下载目标二进制、checksum 和 Sigstore bundle；在停止服务前完成 checksum、固定 identity/issuer 和目标 `--version` 校验。
2. 读取当前二进制版本；仅允许 release 元数据明确列出的升级来源。未知来源、降级或跨越未验证版本默认拒绝；
   显式本地回退只允许 previous generation。
3. 在安装器专属 `0700` 目录创建 previous generation，保存当前二进制、`agent.env`、unit、版本、SHA-256 和有限 manifest；
   二进制/unit 为 `0755/0644`，含秘密的环境文件固定 `0600`。拒绝 symlink 和目录逃逸。
4. 新二进制先写同文件系统临时文件，`fsync` 后原子改名；配置和 unit 同样暂存后原子替换。任何输出不得打印配置值。
5. `daemon-reload`、启动服务并验证目标二进制版本、`systemctl is-active` 和连续稳定窗口。生产金丝雀还需由控制平面确认
   同一 Agent ID 上报目标版本、原 capability 集合且无新增写能力。
6. 本地门失败时自动恢复 previous binary/config/unit，重新加载并启动旧服务；回退成功后仍以非零退出码结束，输出固定审计码。
   回退失败必须保留两代文件和有限故障摘要，不循环重试、不下载另一版本。
7. identity、machine-id、operation ledger 和用户数据目录永不进入 generation 回退包；成功升级后只保留一个受管 previous generation。

### 5.2 已签名 release bundle 的生产暂存

- 增加管理员 CLI，输入明确的 release archive/checksum/Sigstore bundle，固定 GitHub workflow identity/issuer，拒绝 symlink、
  绝对路径、重复文件、未知 manifest 版本和 archive 解包逃逸。
- 解包到新的 `0700` 暂存目录，核对 archive SHA-256、签名、version/tag/commit/schema、五个 digest、
  `images.env == release-manifest.json`，再原子更新“待部署版本”指针；不得自动运行 Compose。
- `release-check` 只接受该已验证暂存目录。preflight/migrate/release-up/postflight 和生产授权链不变。
- 旧的已知可用暂存目录保留用于应用级回退；SemVer tag、candidate tag 和宿主机源码都不能代替记录的 digest。

### 5.3 持续公开发行安全门

- 增加 Dependabot：GitHub Actions、Python、npm 和 Go module 分组更新；只开 PR，不自动合并。
- 增加 CodeQL：Python、JavaScript/TypeScript、Go；PR/push 只读权限，定期全量扫描，不授予包写或 OIDC。
- 增加锁文件/依赖漏洞扫描，并对 candidate 的 API/Web 多架构 digest 执行 OCI 漏洞扫描；扫描工具固定版本与 checksum。
- release publish job 必须依赖候选漏洞门、现有签名验证和 SBOM/digest 一致性检查。失败时不创建/移动 SemVer、不公开 Release。
- Critical/High 默认失败关闭。例外只能是仓库内精确 advisory/package/version allowlist，包含理由、负责人、到期日和替代缓解；
  过期例外自动失败。扫描结果不得包含环境变量或完整私有路径。
- 已发布 tag 不移动。新发现漏洞通过安全公告和新 patch release 修复；定期扫描只报告，不回写旧制品。

## 6. 批次 B：M6.1d 灾备闭环

### 6.1 数据分层

| 层级 | 内容 | 备份/恢复规则 |
| --- | --- | --- |
| A 权威数据库 | PostgreSQL 原子备份包 | 复用现有 dump/manifest/hash；离机前整体加密；只恢复到严格兼容的隔离空目标 |
| B 权威秘密/配置 | `.env.production` 中固定 allowlist、M4 私钥、Principal/admin token、GitHub/通知/Provider 凭据 | 独立加密包；不进入数据库包、日志、Web 或 Agent；恢复后逐项核对并按事故决定是否轮换 |
| C 可重建状态 | Caddy 证书/账户状态 | 默认依靠 DNS/证书重签；如备份 Caddy 卷，必须独立加密且不得覆盖正在运行实例 |
| D 暂态状态 | Redis webhook 限速计数/AOF | 不作为权威恢复前提；新实例可空启动，文档说明短时限速状态会丢失 |

### 6.2 加密与离机规则

- 仅接受显式 allowlist 的固定文件和逻辑字段，不递归收集宿主机目录；拒绝 symlink、设备文件、宽权限输出和未知字段。
- 使用离线保存私钥的 recipient-based 加密；生产主机只持有公钥。明文暂存目录为 `0700`、文件 `0600`，成功加密和校验后
  只清理脚本创建且已验证位于专属临时根下的目标。
- 外层 manifest 只保存格式版本、实例 ID、创建时间、应用 version/commit/revision、PostgreSQL major、密文大小/hash、
  固定组件状态和工具版本；不保存秘密值、连接串或可变远程路径。
- 至少两份离机副本位于不同故障域；上传、保留和删除第一版保持管理员显式操作，不在脚本中实现任意对象存储 URL 或自动删除。
- 解密私钥不得保存在生产控制面、仓库、CI secret、Agent 或备份包中；每次演练先证明离线密钥可用。

### 6.3 RPO/RTO 与演练

- 建议初始目标：数据库 RPO 24 小时、配置/密钥“每次变更后立即备份”、控制平面 RTO 4 小时。正式写入运行手册前由所有者确认。
- 每月执行 manifest/hash/解密抽检；每季度在隔离 PostgreSQL/Compose 完成全链：解密 → DB restore → schema check →
  关键表一致性 → 配置/密钥存在性核对 → API/Web health/system-info。隔离控制面不得让生产 Agent 连接。
- 演练只使用专用域名/网络/实例 ID 和临时凭据；真实 M4 私钥、管理 token、GitHub/通知凭据只验证“可恢复”，默认不连接外部服务。
- 审计摘要仅记录恢复点 ID、版本/revision、各门布尔值、计数是否匹配、耗时、RPO/RTO 是否满足和稳定错误码。

## 7. 测试矩阵

| 范围 | 必测项 |
| --- | --- |
| Agent 单元/沙箱 | checksum/签名/版本错误、并发锁、symlink、断电式部分文件、策略不扩权、previous 权限、成功升级、启动失败自动回退、回退失败保留现场 |
| Agent 真实 systemd | v0.4.2 → 下一版本、同 ID/同策略、控制面看到目标版本；坏二进制/坏配置回退后旧版本重新 online |
| release bundle | 签名与 hash、archive traversal/symlink/重复项、manifest/images.env 一致、错误 commit/schema/digest、原子暂存、release-check 只读 |
| 发行安全 | Dependabot 配置、CodeQL 三语言、已知漏洞夹具失败、allowlist 过期失败、OCI digest 扫描、SBOM/digest 不一致失败、PR 无写权限/OIDC |
| 灾备包 | allowlist、权限、无明文残留、错误 recipient、篡改/截断、错误实例/revision/PG major、缺失秘密、日志无凭据 |
| 完整灾备 | 临时 PostgreSQL/Compose 解密恢复、schema/关键数据、空 Redis、外部集成禁用、RPO/RTO 计时和有限摘要 |
| 回归 | API/Web/Go、迁移双向/单 head、Recovery/Web/release Compose/Source Distribution、REUSE、`git diff --check` |

## 8. 生产与发行验证边界

### 8.1 Agent 金丝雀

- 只选择一台非关键 Agent；记录版本、identity、策略/capability、最近报告和 previous generation hash。
- 先验证成功升级，再使用受控的启动失败夹具验证本地自动回退；不得让失败夹具执行任何 M4 任务。
- 前后核对 Agent ID、能力、Operation/Transition 和告警副作用；完成后保留有限升级审计，不记录 `agent.env`。

### 8.2 控制平面 bundle 金丝雀

- 先在隔离 Compose 验证签名 bundle 暂存和 `release-check`；生产只在另一份授权下沿用 preflight 备份、migrate、
  release-up、reload-caddy、postflight。
- 不因 bundle helper 自动迁移、自动部署或自动回退；当前生产数据库不得作为 restore 测试目标。

### 8.3 灾备金丝雀

- 生产阶段只生成一份新的 DB 包和加密配置/秘密包并复制到已批准离机介质；不停止控制面、不解密到生产普通目录。
- 恢复只在隔离临时目标执行。真实生产恢复、密钥轮换、删除旧副本和启用外部通知/GitHub 均需新的事故授权。

## 9. P0/P1/P2

### P0

- 自动回退恢复 identity/operation ledger，导致身份漂移或任务重放。
- 灾备包、升级 generation、CI artifact 或日志泄露私钥/token/数据库正文。
- 未验证签名/manifest/digest 就部署，或扫描失败仍发布 SemVer。
- 恢复脚本可覆盖非空/错误实例生产库，或清理未验证的宽路径。

### P1

- Agent 只检查进程存活，不核对版本、稳定窗口和 capability 不扩权。
- release bundle 已包含 `images.env`，实现却另造第二套不一致的 digest 来源。
- 没有可用的离线解密密钥、没有真实隔离全恢复、RPO/RTO 只写目标不计时。
- 漏洞 allowlist 没有到期日，或扫描器/Action 可漂移。

### P2

- Fleet 分批升级编排、自动暂停、升级进度 UI。
- 远程对象存储适配、自动保留/轮换和备份新鲜度通知。
- 多平台 Agent、可复现构建更强证明和历史版本持续兼容实验室。

## 10. 完成定义

- 批次 A：Agent 成功升级和失败回退均在真实 systemd 隔离环境通过；普通升级不改变 identity/ledger/capability；
  签名 bundle 可安全暂存且不自动部署；依赖/CodeQL/OCI 漏洞门与现有发行门共同失败关闭。
- 批次 B：数据库和固定秘密/配置生成可解密、可校验的离机副本；隔离完整恢复满足经确认的 RPO/RTO；Redis/Caddy
  权威性和密钥轮换决策明确；生产库未被覆盖。
- 两批均通过独立安全审计、真实 Linux/PostgreSQL/Compose 验证和现有 CI；文档只记录实际证据。
- 提交、推送、正式发行、生产 Agent 金丝雀、控制平面升级和灾备生产演练继续逐项取得明确授权。
