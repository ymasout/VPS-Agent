# M6.4d 正式发行与开源分发设计

当前状态：**v0.6.1 已于 2026-08-01 正式公开发行。** tag `v0.6.1` 指向 commit `8746182`，
Formal Release workflow 四阶段（review → draft → candidate → publish）全部成功，四条 CI 全绿，
PVR 已启用并通过 create-draft 门，Release `isDraft=false`、`isPrerelease=false`、32 个资产。
API 镜像 `ghcr.io/ymasout/vps-agent-api:v0.6.1`（manifest digest
`sha256:7bc0fb29ffcfadc3ff8f76dff066301fa301e525ab361c5bb63a9a1a9661373c`）与 Web 镜像
`ghcr.io/ymasout/vps-agent-web:v0.6.1`（manifest digest
`sha256:e05136ea7fee0a8a36155294403350f5b620d7043368982b810034834407af13`）均已公开可匿名拉取。
生产尚未切换到正式镜像；生产升级仍是独立授权事件。

## 1. 设计时基线与当前实现状态

- 正式公开仓库为 `https://github.com/ymasout/VPS-Agent`，默认分支 `main`，仓库已公开。
- GitHub 已有 Agent `v0.2.2`–`v0.4.2` Release；v0.6.1 起新增正式控制平面镜像和统一产品 Release。
- Agent Go module 已改为 `github.com/ymasout/VPS-Agent/apps/agent`，所有内部 import
  已同步，正式发行 CI 已验证。
- `Source Distribution` CI 已固定 Action commit，执行 Gitleaks、REUSE、依赖许可证、源码 SPDX
  和安全 archive，但产物仅保留 14 天，不创建 Release。
- 旧 `Release Agent` 已在本地改为手动 review-only 候选验证；正式 workflow 使用固定
  Action commit、最小权限、candidate-then-promote、SBOM 与 Sigstore keyless 验证，已于 v0.6.1
  四阶段全成功。
- API/Web/Agent 构建基础镜像及 release Compose 的 Caddy/PostgreSQL/Redis 已固定 digest；API/Web
  以非 root 运行。本地临时 registry 的 digest-only Compose 已完成空库迁移到 `0020`、schema、
  health 和 build identity 验证；现有生产 Compose 仍保持源码构建，未被自动切换。
- GitHub Private Vulnerability Reporting 在设计时为 disabled；已在发行前启用并实测，SECURITY
  不再含未关闭 blocker。

## 2. 目标与非目标

目标：

1. 从一个受保护、指向已审计 main commit 的 SemVer tag 重复构建源码包、Agent 二进制和
   API/Web OCI 镜像。
2. 每类产物同时提供 SHA-256、SPDX/CycloneDX SBOM、发布者真实性证明和 commit/tag 绑定。
3. 提供不含秘密的 release Compose/bundle、版本兼容矩阵、CHANGELOG 和安装/升级/回退手册。
4. 在全新临时主机完成安装，再从当前支持基线升级，并执行备份→隔离恢复→schema check。
5. 正式发行仍需用户单独授权；workflow 不自动部署生产、不自动迁移真实数据库。

非目标：商业镜像仓库、自动更新、遥测、SaaS、多租户、公开注册、Web SSH、自由 Shell、自动
确认/执行/回滚，以及任意旧版本到最新版的无条件跨版本恢复。

## 3. 冻结发行身份

- 仓库与源码坐标：`github.com/ymasout/VPS-Agent`。
- Agent Go module：`github.com/ymasout/VPS-Agent/apps/agent`。
- OCI 镜像：`ghcr.io/ymasout/vps-agent-api` 与 `ghcr.io/ymasout/vps-agent-web`。
- 版本：monorepo 使用统一 `vMAJOR.MINOR.PATCH` tag；首个正式 M6 候选建议为尚未使用且与当前
  控制平面展示一致的 `v0.6.1`。Agent 二进制使用同一版本，兼容能力另由矩阵表达，不再让
  tag 同时具有“仅 Agent 发行”这一隐含语义。
- 镜像至少发布不可变 digest；SemVer tag 只是可读别名。生产 bundle 必须记录并默认使用
  digest，不能只依赖 `latest`。
- 签名采用 GitHub Actions OIDC 的 Sigstore keyless/cosign bundle，不引入长期私钥 secret；
  workflow 与验证文档固定 certificate identity 和 issuer。

## 4. 发行资产

一个正式 Release 至少包含：

- commit 绑定的源码 tar.gz、manifest、SHA256SUMS、源码 SPDX 和依赖许可证清单；
- `linux/amd64`、`linux/arm64` Agent、安装器、每个二进制 SBOM；
- API/Web 多架构 OCI manifest、镜像 digest 清单、镜像 SBOM 与 provenance；
- cosign 签名/attestation 验证说明和离线可保留的 bundle；
- release Compose/bundle、Caddy 配置、生产 env 示例、兼容矩阵、CHANGELOG 和升级/回退说明。

Release workflow 先在 CI artifact/本地临时 registry 中构建和验证全部产物，再创建 draft
Release。GitHub Release 与 GHCR 不具备跨服务事务，不能虚构“绝对原子发布”：取得 publish
授权后，先以 `candidate-<commit>` 临时标签推送已验证 digest、签名并回拉验证，再把**同一 digest**
提升为 SemVer 标签并发布 Release。发布前必须先验证两个候选 digest、签名、draft 和两个 SemVer
标签均不存在；GitHub/GHCR 不提供跨包事务，若外部故障仍造成单侧 SemVer 标签，Release 必须保持
draft，流程停止并进入显式事故审计，不得自动移动、覆盖或重试已有标签。候选标签不属于正式发行，
保留或清理由管理员审计后显式处理，不自动删除。正式 publish 仍是独立人工动作。

## 5. 供应链安全边界

- 所有 GitHub Actions 固定完整 commit；job 最小权限，构建默认 `contents:read`，只有最终
  draft Release/包推送 job 获得 `contents:write`/`packages:write`，签名 job 才有
  `id-token:write`。
- tag 必须是规范 SemVer、指向 main 可达 commit、对应四条现有 CI 全绿；版本、OCI label、
  Agent `--version`、manifest 和 Release 名必须一致。
- 正式 Git tag 与 SemVer 镜像标签均为不可移动坐标；同名已存在时失败关闭。候选标签只能由
  受信 workflow 写入，不能被安装文档、release bundle 或生产 Compose 引用。
- 发行只使用 committed clean tree；继续复用 M6.4a denylist、秘密扫描、symlink 拒绝和
  许可证失败关闭。
- 基础镜像和发布工具固定 digest/版本；生成的镜像以非 root、最小运行文件和既有 healthcheck
  运行。不能把 `.env`、数据库、备份、日志、签名私钥或生产配置复制进 layer/asset/SBOM。
- checksum 只能证明完整性；真实性必须由 keyless signature/provenance 验证。验证命令在干净
  主机实跑，不能只生成未验证的签名文件。

## 6. 安装、升级、兼容与回退

- 全新安装只使用 release bundle 与 digest-pinned 镜像，生成本机秘密后执行 migration、
  schema check、`/healthz` 和受管理 system-info 核对。
- 升级继续复用 `control-plane-release.sh preflight -> migrate -> up -> postflight`，preflight
  必须先生成 M6.1 原子备份。生产不由 workflow 自动升级。
- 首个正式矩阵至少验证：全新 `v0.6.1`；当前生产基线 `0d75342 + 0020` 到正式版本；Agent
  `v0.4.2` 与新控制平面的报告、证据、restart/deploy 协议兼容。更老 Agent 只有经实际测试后
  才列为 supported，不能从历史文档推断。
- 应用回退只允许回到兼容当前 schema 的上一镜像 digest；数据库恢复仍是显式离线事故操作，
  只接受对应备份 manifest/commit/schema 兼容门，不能自动覆盖生产库。
- Agent 安装器继续先校验 checksum 再原子替换；M6.4d 增加签名验证和 last-known-good 手工
  回退说明，不自动扩大 capability。未知 env policy 仍失败关闭，但必须产生清晰 warning，
  并在启用前核对实际上报 capability。

## 7. 测试与发行演练

1. 本地/CI：现有 API、Web、Go、Ruff、ESLint、migration、Recovery、Caddy、REUSE、Gitleaks、
   dependency license 全部继续通过。
2. 发行负向门：脏树、非 SemVer、tag/版本/commit 不一致、未固定 Action/镜像、缺 SBOM/签名、
   伪造资产、秘密文件、错误 license、错误架构全部失败。
3. OCI：拉取 digest，核对 label、非秘密 layer、healthcheck、amd64/arm64 manifest，并用 cosign
   验证签名和 provenance。
4. 干净主机：release-only 安装→schema check→system-info；从支持基线升级；备份→隔离恢复→
   关键表一致性；应用 digest 回退。所有演练使用临时/隔离数据库。
5. Agent：两个架构校验版本与签名；安装/升级保留身份；错误连字符 env 明确 warning 且 capability
   保持 disabled；正确下划线值才声明对应能力。
6. GitHub：启用并测试 Private Vulnerability Reporting 后再更新 SECURITY；draft Release 资产齐全
   且验证通过后，才由用户明确授权 publish。

## 8. 一次连续实施方案

M6.4d 不再拆独立 d1/d2/d3/d4，按一次本地批次连续完成：

1. 正式坐标/版本与 contributor 文档；Go module、CHANGELOG、兼容矩阵、统一 `make release-check`。
2. 将 review-only source workflow 抽成可复用构建；重写 pinned、最小权限的正式 draft-release
   workflow，构建 Agent、源码包、API/Web 镜像、SBOM、checksums、signatures/provenance。
3. 增加 digest-pinned release Compose/bundle和安装/升级/回退说明；补 Agent 非法 policy warning。
4. 本地与 Ubuntu CI、真实 OCI、干净临时主机安装/升级/恢复演练统一完成后进行一次独立审计。
5. 用户单独授权后创建 tag/draft Release；核对所有资产与签名后再次授权 publish。生产升级仍需
   另一份明确授权，不与公开发行合并。

## 9. P0/P1/P2

P0：发行夹带秘密/生产数据；tag 与 commit/镜像不一致；许可证范围错误；签名主体可被非预期
workflow 冒充；release bundle 默认使用漂移 tag。

P1：Private Vulnerability Reporting 未启用却宣称私密通道；候选资产被误称或引用为正式发行；
失败后仍创建/移动 SemVer 标签；SBOM/签名未被实际验证；Go module/镜像/版本坐标不一致；
不兼容 schema 回退；旧 Agent 支持范围过度承诺。

P2：只支持单架构控制平面；基础镜像未固定 digest；贡献者无法在干净 checkout 复现；CHANGELOG
和兼容矩阵漏记 breaking change；Agent 无效策略仅静默 disabled。

## 10. 完成定义

- 正式坐标、版本、镜像和签名 identity 唯一且机器可验证。
- draft Release 的源码、Agent、OCI、SBOM、checksum、signature/provenance 和文档全部齐全；
  release-only 干净主机演练通过。
- Private Vulnerability Reporting 已启用并实测，SECURITY 不再含未关闭 blocker。
- 正式 tag/publish、生产升级均分别取得用户明确授权；没有自动部署或数据库覆盖。
- README、ROADMAP、PROJECT_STATUS、ARCHITECTURE 与 M6 总文档只在证据完成后标记 M6.4d/M6
  完成；Web SSH 仍是独立后续设计。
