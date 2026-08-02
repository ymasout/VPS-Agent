# M6 后续可靠性与公开发行安全加固设计

状态：**批次 A 已完成本地实现、首轮验证和独立代码/安全审计，并已在本地提交，尚未推送。批次 B 仍仅有设计。** M6 已于 2026-08-02 收口；
本文保留 M6.1c/M6.1d 名称只为延续既有追踪，不重新打开 M6，也不提前把批次 A 标记为发布或生产完成。任何提交、推送、
正式发行、生产升级、生产备份或恢复仍需分别授权。

审计基线：仓库 `main`/`e40f07f6f9fd12cd2e4d01225625e8a4813720f9`；v0.6.1 tag/运行制品 commit
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

1. 下载目标升级元数据、二进制、checksum 和各自 Sigstore bundle；在改变任何本地文件前完成 checksum、固定
   identity/issuer、严格元数据和目标 `--version` 校验。
2. 读取当前二进制版本；仅允许已验签升级元数据明确列出的精确来源版本。未知来源、降级或跨越未验证版本默认拒绝；
   显式本地回退只允许 previous generation。
3. 在安装器专属 `0700` 目录创建 previous generation，保存当前二进制、`agent.env`、unit、版本、SHA-256 和有限 manifest；
   二进制/unit 为 `0755/0644`，含秘密的环境文件固定 `0600`。拒绝 symlink 和目录逃逸。
4. 在旧进程仍运行时，把新二进制写入同文件系统临时文件，对文件和父目录执行 `fsync` 后原子改名；配置和 unit
   同样暂存后原子替换。切换前写入不含秘密的 durable transaction journal。任何输出不得打印配置值。
5. `daemon-reload` 后只执行一次 `systemctl restart`，验证目标二进制版本、`systemctl is-active` 和本地连续 30 秒稳定窗口。
   本地安装器不因控制平面或网络暂时不可达而回退。生产金丝雀另需等待至少两个新鲜报告且跨度不少于 60 秒，确认同一
   Agent ID 上报目标版本、原 capability 集合且无新增写能力。
6. 本地门失败时自动恢复 previous binary/config/unit，重新加载并启动旧服务；回退成功后仍以非零退出码结束，输出固定审计码。
   回退失败必须保留两代文件和有限故障摘要，不循环重试、不下载另一版本。
7. identity、machine-id、operation ledger 和用户数据目录永不进入 generation 回退包；成功升级后只保留一个受管
   previous generation。每个 generation 仅允许一个二进制（最大 128 MiB）、一个环境文件（最大 1 MiB）、一个 unit
   （最大 256 KiB）和固定 manifest；替换 previous 前先验证空间足以同时容纳 current、candidate、previous 和 64 MiB 余量。

#### 5.1.1 升级兼容元数据

- 源码真相位于 `release/release.json` 的新字段 `agent_upgrade_from`，值为 canonical SemVer 的精确、去重、升序数组，
  例如 v0.6.1 首次发行使用 `["0.4.2"]`，仅表达可升级到当前目标版本的来源。不使用范围、通配符、`latest` 或隐式
  “同 minor 兼容”；`supported_agent_versions`
  继续只表达控制平面协议兼容，不能被安装器误作升级来源。
- Formal Release 从该字段和当前 release 坐标确定性生成独立资产 `agent-upgrade.json`：

  ```json
  {
    "format_version": "vps-agent-upgrade-v1",
    "repository": "github.com/ymasout/VPS-Agent",
    "target_version": "0.7.0",
    "target_tag": "v0.7.0",
    "commit_sha": "40-character-lowercase-sha",
    "upgrade_from": ["0.4.2"]
  }
  ```

- 生成器严格拒绝未知字段、非 canonical SemVer、目标出现在 `upgrade_from`、重复/未排序来源和与
  `release/release.json` 不一致的 tag/commit。该 JSON 与 Agent 二进制一起进入 `SHA256SUMS`，并生成独立 Sigstore bundle；
  draft/candidate/publish 各阶段均不得替换同名资产。
- 安装器先从请求的不可变 `vMAJOR.MINOR.PATCH` Release 下载并验证 `agent-upgrade.json`。当用户输入 `latest` 时，只允许
  用 latest 跳转发现元数据；验签并得到 `target_version` 后，后续 JSON、binary、checksum 和 signature 全部重新从精确
  `/releases/download/v<target_version>/` 路径下载，防止 latest 在流程中漂移。
- 新安装没有当前版本，不执行 `upgrade_from` 门；已有安装必须让当前 `--version` 精确命中数组。普通安装器不提供任意
  `--force`；旧版/降级只能走已验证 previous generation 的本地显式回退。

#### 5.1.2 中断恢复、保留和退出码

- transaction journal 固定记录 transaction ID、阶段、当前/目标版本与 hash、previous 路径和启动时 boot ID，不含环境值。
  journal 使用临时文件、文件/目录 `fsync` 和原子改名。每次安装器启动先恢复未完成事务，再开始新事务。
- 不再先停止旧服务：切换文件前旧进程保持运行。若安装器在 restart 前被 `kill -9`，旧进程继续运行；再次运行安装器时
  恢复 previous。若主机重启且存在未提交事务，由固定的 root-owned recovery oneshot 在 Agent 前比较 boot ID，并恢复
  previous 后再启动 Agent。该 helper 不读取或修改 identity/ledger，不访问网络。
- 只保留一个 previous generation。新的成功升级确认后，安装器只替换其专属受管 previous 目录；未知目录、非预期文件、
  symlink 或超出大小上限时失败关闭，不自动清理。
- 稳定退出码：`0=upgrade_succeeded`、`20=rejected_before_change`（下载/签名/版本/兼容/空间）、`21=upgrade_locked`、
  `30=activation_failed_rollback_succeeded`、`31=activation_failed_rollback_failed`、`32=interrupted_transaction_recovery_failed`。
  参数错误仍使用 `2`。固定单行 JSON 摘要只包含 audit code、版本、transaction ID、阶段和布尔结果。

### 5.2 已签名 release bundle 的生产暂存

- 增加管理员 CLI，输入明确的 release archive/checksum/Sigstore bundle，固定 GitHub workflow identity/issuer，拒绝 symlink、
  绝对路径、重复文件、未知 manifest 版本和 archive 解包逃逸。
- 解包到新的 `0700` 暂存目录，核对 archive SHA-256、签名、version/tag/commit/schema、五个 digest、
  `images.env == release-manifest.json`，再原子更新“待部署版本”指针；不得自动运行 Compose。
- `release-check` 只接受该已验证暂存目录。preflight/migrate/release-up/postflight 和生产授权链不变。
- 旧的已知可用暂存目录保留用于应用级回退；SemVer tag、candidate tag 和宿主机源码都不能代替记录的 digest。

#### 5.2.1 Archive 解包安全

- 第一版暂存 CLI 使用 Python 3.12+ 标准库 `tarfile`；运行前严格检查解释器版本，不兼容时失败关闭，不回退到 shell `tar`。
- archive 先完成外层 SHA-256 与 Sigstore 验证，再打开。先遍历全部 member、确认集合合法后才提取；只允许普通文件和目录，
  显式拒绝 symlink、hardlink、device、FIFO、sparse/未知类型、绝对路径、NUL、反斜杠、空段、`.`/`..`、重复规范路径和
  大小/文件数超限。所有 member 必须位于唯一顶层目录 `vps-agent-<version>/` 和固定 bundle allowlist 内。
- 使用 `tarfile.extractall(..., filter='data')` 作为第二层防护，但不能用它替代上述显式检查。目标由 `mkdtemp` 创建为 `0700`，
  父目录必须 root-owned、非 symlink 且不可被 group/other 写；忽略 archive owner/group/mode，落盘文件按固定 allowlist 重新设权。
- 每个目标以 `Path.resolve()` 验证仍位于新建根目录内；解包后再次拒绝任何 link、额外文件和 realpath 逃逸。校验全部通过后
  对文件/目录 `fsync`，再以同文件系统原子改名发布暂存目录；失败只清理本次创建且 realpath 已验证的临时根。

#### 5.2.2 生成 bundle 的必需产物

- `deploy/release/images.env` 由 candidate 的真实 OCI digest 生成，不能加入面向源码文件的 `REQUIRED_BUNDLE_FILES`，也不能
  在 Git 中放占位成品。实现时新增独立 `GENERATED_BUNDLE_FILES`/结果校验，要求 `images.env` 和 `release-manifest.json`
  在 archive 中恰好各一份。
- 构建器重新解析两份文件，要求五个变量的键集合、顺序和值与 manifest 完全一致且全为 canonical digest；测试必须篡改单个
  digest、增加/删除键、重复键和换行，证明 bundle 构建或暂存失败关闭。

### 5.3 持续公开发行安全门

- 增加 Dependabot：GitHub Actions、Python、npm 和 Go module 每周检查；每个 ecosystem 的 patch/minor 可分组，major
  必须独立 PR，安全更新不得因普通分组或更新数量上限被延后；只开 PR，不自动合并。
- 增加 CodeQL：Python、JavaScript/TypeScript、Go；PR/push 只读权限，定期全量扫描，不授予包写或 OIDC。
- 使用固定版本与 checksum 的 OSV-Scanner 扫描 Python/Node/Go 锁定依赖；使用固定版本与 checksum 的 Trivy 对 candidate
  API/Web digest 分别扫描 `linux/amd64` 和 `linux/arm64`，不得只扫描 runner 默认平台。漏洞数据库下载与扫描步骤不持有
  registry 写权限或 OIDC。
- release publish job 必须依赖候选漏洞门、现有签名验证和 SBOM/digest 一致性检查。失败时不创建/移动 SemVer、不公开 Release。
- Critical/High 默认失败关闭。例外只能是仓库内精确 advisory/package/version allowlist，包含理由、负责人、到期日和替代缓解；
  过期例外自动失败。扫描结果不得包含环境变量或完整私有路径。
- 批次 A 第一版不提供漏洞例外文件或忽略参数，所有命中均失败关闭；若未来确需例外，必须先实现并测试上一条的精确匹配、
  到期自动失败和审计字段，不能直接加入 OSV/Trivy 的宽泛 ignore ID。
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

#### 6.2.1 age 密钥管理仪式

- 第一版固定使用经版本/checksum 校验的 `age` 原生 X25519 recipient（`age1...`），不接受 SSH recipient、插件、口令模式、
  GPG 或运行时下载的未知二进制。
- 所有者在两台不连接生产控制面的离线设备上分别运行 `age-keygen`，生成两个独立 identity；identity 文件立即设为 `0600`，
  各自制作一份封存恢复副本并存放在不同物理故障域。第一版采用“任一 recipient 可解密”的 1-of-2 可用性模型；不引入
  Shamir/第三方 threshold 插件，避免重组实现和操作仪式本身成为新故障源。
- 只把两个 public recipient 通过受信可移动介质带到生产，管理员在独立通道核对完整 recipient/fingerprint。实际配置写入
  `/etc/vps-agent/backup-recipients.txt`，root-owned、`0644`、恰好一行一个 recipient、至少两个且无重复。仓库只提交
  `.example`，不提交实例实际 recipient；脚本不允许环境变量或命令行临时覆盖 recipient 文件。
- 每个密文必须同时加密给当前 key set 的全部 recipient，并在 manifest 记录非秘密 `recipient_set_id`（由排序后的 public
  recipients 求 SHA-256，不记录私钥）。季度演练分别证明两把 identity 都能独立解密同一测试包。
- 正常轮换每 12 个月一次，人员/设备丢失或疑似泄露时立即轮换。轮换先增加新 recipients、生成并双端解密一份新备份，
  再停止使用旧 key set；旧 identity 至少保留到其加密的所有备份过期或经显式授权重新加密并验证。两把 identity 均丢失时
  旧备份不可恢复，系统不保留生产后门或云端托管副本。

### 6.3 RPO/RTO 与演练

- 所有者已于 2026-08-02 确认：数据库 RPO 24 小时、配置/密钥每次变更后立即备份、控制平面 RTO 4 小时。
  数据库与秘密包至少保留两份加密异地副本并位于不同故障域；仅留在控制平面宿主机的副本不计入 RPO 达标证据。
- 每月执行 manifest/hash/解密抽检；每季度在隔离 PostgreSQL/Compose 完成全链：解密 → DB restore → schema check →
  关键表一致性 → 配置/密钥存在性核对 → API/Web health/system-info。隔离控制面不得让生产 Agent 连接。
- 演练只使用专用域名/网络/实例 ID 和临时凭据；真实 M4 私钥、管理 token、GitHub/通知凭据只验证“可恢复”，默认不连接外部服务。
- 审计摘要仅记录恢复点 ID、版本/revision、各门布尔值、计数是否匹配、耗时、RPO/RTO 是否满足和稳定错误码。

## 7. 测试矩阵

| 范围 | 必测项 |
| --- | --- |
| Agent 单元/沙箱 | checksum/签名/版本错误、并发 `flock` 互斥、symlink、previous 权限/大小/空间门、策略不扩权、成功升级、启动失败自动回退、回退失败保留现场；在 journal 各阶段以 `kill -9` 注入中断，重跑安装器并模拟跨 boot ID oneshot，证明旧进程持续或 previous 被恢复 |
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

## 11. 首次设计审计处置（2026-08-02）

| 审计项 | 处置 |
| --- | --- |
| P1 升级兼容格式 | 采纳并强化：源码 spec 增加精确版本数组，正式发行生成独立、签名的 `agent-upgrade.json`；安装器不依赖完整控制平面 bundle |
| P1 archive 解包 | 采纳：Python 3.12+、先验签、两遍 member 检查、拒绝所有 link/特殊类型、固定 allowlist、0700 临时根和原子发布 |
| P1 recipient 密钥仪式 | 采纳并调整：固定 age X25519、两个独立离线 recipient 和异地封存副本；第一版不用 Shamir 插件，避免引入新的恢复依赖 |
| P2 稳定窗口 | 采纳并区分：本地 30 秒；生产控制面至少两个新鲜报告且跨度不少于 60 秒 |
| P2 扫描工具 | 采纳：OSV-Scanner 扫依赖，Trivy 按两个平台扫描 candidate digest，均固定版本/checksum |
| P2 RPO/RTO | 已关闭：所有者于 2026-08-02 确认数据库 RPO 24 小时、配置/密钥变更后立即备份、控制平面 RTO 4 小时 |
| P2 `images.env` | 不按“源文件必需项”实现；它依赖 candidate digest，改为生成产物必需项和 manifest 严格一致性门 |
| P3 generation/Dependabot/退出码 | 已补一个 previous generation、大小/空间门、每 ecosystem 分组策略和固定退出码枚举 |

所有者随后于 2026-08-02 接受数据库 RPO 24 小时、配置/密钥每次变更后立即备份和控制平面 RTO 4 小时；
上表 P2 RPO/RTO 阻断输入已关闭，批次 B 仍须用真实异地加密副本与计时恢复演练证明达标。

复审观察项同步冻结：

- recovery unit 固定为首次安装即写入的 root-owned `vps-agent-upgrade-recovery.service`，`Type=oneshot`、
  `Before=vps-agent.service`；Agent unit 使用 `Requires=` 与 `After=`，回退失败会阻止 Agent 以未知文件集启动。普通启动无 journal 时只读退出。
- v0.6.1 的 `agent_upgrade_from` 初始值为 `["0.4.2"]`，不包含目标自身；当前
  `supported_agent_versions=["0.4.2","0.6.1"]` 继续表达控制平面协议兼容，二者不得自动互相生成。
- `age` 只从官方 `FiloSottile/age` GitHub Release 获取明确版本资产，并先用仓库固定的发布者校验材料与官方 checksum
  验证后进入管理员工具缓存；生产脚本不在备份执行时联网下载，也不接受 PATH 中未知版本的 `age`。

## 12. 批次 A 本地实现与审计记录（2026-08-02）

- Agent：新增独立签名的精确升级元数据、`flock` 互斥、原子 binary/env/unit transaction、previous manifest/hash 校验、
  一个 previous generation、30 秒本地稳定门、固定退出码，以及安装时写入的 root-owned boot-ID recovery oneshot。
  identity、machine-id 与 operation ledger 不进入 generation。
- Release：新增 Python 3.12+ 签名 bundle staging CLI；固定 archive allowlist、拒绝 link/traversal/特殊类型/额外目录，交叉核对
  `release-manifest.json`、`release/release.json` 与五个 digest，并让 release mode 只接受同一已验证 staged directory。
- 供应链：增加每生态 Dependabot、三语言 CodeQL、checksum-pinned OSV-Scanner、已知漏洞失败夹具，以及独立只读 Trivy job
  对 API/Web 的 amd64/arm64 candidate digest 扫描。扫描成功后才允许生成签名 candidate bundle；扫描 job 不持有 package write 或 OIDC。
- 本地证据：使用升级后全新依赖环境的 API 335 passed/15 skipped，Web 100 passed，Go test/vet、Web lint/build、Compose config、
  Ruff、shell 语法、release policy、`release-check` 与 `git diff --check` 通过；OSV-Scanner 2.4.0 真实复扫为 `No issues found`；
  WSL 真实 systemd 隔离测试通过互斥锁、成功升级、坏二进制失败回退、跨 boot oneshot 和 identity/ledger/策略保持。
- 为使新门在现有代码上真实转绿而非依靠 ignore，本批次同时升级到已修复的 FastAPI/PyJWT/Alembic/pytest、
  Next/React/Vitest 版本，并对 Next/ESLint 仍精确引入的易受影响传递依赖使用仓库锁定 override；升级后 API/Web 全量回归通过。
- P3 观察项：升级后的 FastAPI/Starlette 测试环境提示 `TestClient` 的 httpx 2 兼容路径及旧 `HTTP_422_UNPROCESSABLE_ENTITY`
  常量将在上游弃用；当前行为与全量测试均通过，后续应在依赖正式移除前完成适配，不作为批次 A 阻断项。
- 独立审计无 P0/P1；P2/P3 均已确认无需改动，FastAPI `0.116.1 -> 0.141.1` 的全量回归证据已明确保留。
- 尚未完成：推送后的 GitHub CodeQL/OSV/Source Distribution 实跑、下一正式版本的 candidate Trivy，
  以及经单独授权的 Agent 与 bundle 生产金丝雀。因此批次 A 当前只能称“本地已实现”，不能称“已发布/生产完成”。
