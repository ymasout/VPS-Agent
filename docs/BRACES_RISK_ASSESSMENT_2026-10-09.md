# braces 风险评估（2026-10-09）

范围：`GHSA-vfj7-8cjw-p6xm` / `braces@3.0.3`，应用依赖基线 `02f2d929e18f734a6fbea4144770ec852608d78b`。评估检查提交 `7ff5c2ce1249828e61c47996e6f6d8093f1bf4ba` 只新增 CI 最终镜像依赖检查，不修改应用依赖、安全例外或生产配置。

## 当前处置：用户已批准限期例外

2026-10-09 用户明确授权“设置例外，并留下一个提醒”。新增 `security/braces-exception.json` 和 `scripts/vulnerability_gate.py`，例外仅匹配该 GHSA、npm/braces/3.0.3 和根 pnpm-lock.yaml，2026-11-08 00:00 Asia/Shanghai（2026-11-07 16:00 UTC）到期，到期瞬间不再接受。没有永久忽略、整个包忽略或别名泛化。

OSV 使用显式空配置产生完整 JSON，原始告警保留在 CI 日志；后处理仅接受精确匹配，输出 ACCEPTED RISK 和到期时间至步骤摘要，不称漏洞已修复。扫描器异常、报告异常、新漏洞/其他包/其他版本/其他清单均阻断。lockfile、根/Web package.json、ESLint 配置和 Web Dockerfile 的 LF 归一化 SHA-256 绑定本次评估；任一变化要求重评，不自动更新指纹。最终镜像开发依赖排除门继续独立执行；不能只凭漏洞策略通过就认为所有 CI 已通过。

12 项独立标准库测试通过：精确命中、到期前后与时区边界、批准前、同包新漏洞、包/版本/生态变化、清单变化、指纹变化、CRLF、扫描器错误、干净结果、状态不一致和缺损记录。真实 OSV 未过滤报告退出 1（仅该漏洞），策略评估退出 0并明确打印风险。CI 另用真实 requests==2.19.1 验证扫描器和策略均拒绝非例外漏洞。

已创建本会话提醒“复核 braces 安全例外”（automation id: braces）：每天 09:00 只读检查；无变化时保持安静，出现补丁/前提变化、11 月 7 日或到期后提醒，不自动续期。提醒不替代 CI 到期控制，桌面任务能否及时运行不影响下次 CI 的时间判断。定时扫描仍每周执行，过期后下一次推送、手动或定时扫描恢复阻断，不表示到期时主动停止生产。

未修改生产配置或部署，未开始 M7.4。以下为批准前的评估过程。

## 上游与复现

[公告](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) 当前没有补丁版本，npm 查询最新仍为 3.0.3。[上游 issue](https://github.com/micromatch/braces/issues/70) 描述递归 AST 遍历缺少深度限制，不能预测补丁发布时间。

本机 Node 22.15.0，使用独立子进程、128 MiB V8 堆上限、5 秒超时进行有限探测；未向网站、生产服务或网络发送攻击输入。

- 5,000 层、10,003 字符输入被既有长度门拒绝（SyntaxError），不作为栈溢出证据。
- 4,000 层目录配置探测未复现，不能据此判定安全。
- 4,990 层、9,983 字符输入分别触发 `braces.compile`、`braces.expand` 和 Next ESLint `getRootDirs` 的 `RangeError: Maximum call stack size exceeded`。测试捕获异常并正常退出；证实真实缺陷及配置调用链可达，不证明远程请求可达。
- 默认 settings 的 `getRootDirs` 正常返回当前目录。

## 项目输入边界

`pnpm why braces` 只显示开发依赖链：`@next/eslint-plugin-next@15.5.27 → fast-glob@3.3.1 → micromatch@4.0.8 → braces@3.0.3`；eslint-config-next 同时引用该插件。

审阅已安装源码：插件内 fast-glob 唯一引用位于 `dist/utils/get-root-dirs.js`，由 `no-html-link-for-pages` 使用；只有配置 `settings.next.rootDir` 为字符串或数组时才进入 glob。之后经 fast-glob 的 pattern expansion、micromatch.braces 进入 braces.expand。

仓库 `apps/web/eslint.config.mjs` 未设置 rootDir；对 `app/page.tsx` 执行 `eslint --print-config` 后有效配置也没有 rootDir。应用源码搜索未发现直接引用 braces/micromatch/fast-glob。该已识别入口读取仓库 ESLint 配置，不读取 HTTP 请求、Agent 上报或用户提交的业务字段。

能修改 ESLint 配置的贡献者可让构建失败；配置本身是可执行 JavaScript，已有代码执行能力。此处主要残余风险为开发/CI 可用性，不能将“开发依赖”概括为所有使用方式均安全。未来配置、依赖链或应用调用变化均使本评估失效。

## 最终镜像证据

Web Dockerfile 为多阶段构建，runtime 只复制 Next standalone、静态资源及 public；不会整体复制 build node_modules，并移除基础镜像全局 npm/corepack/yarn。

新增 `scripts/check_web_runtime_dependencies.mjs`：在实际最终镜像中遍历 `/app` 包清单，跟随符号链接且防止重复遍历，拒绝 braces、micromatch、fast-glob、eslint 和 Next ESLint 插件；缺少入口、零清单、解析/访问失败均不放行。它证明列出的独立包未包含于应用包树，不是通用 SBOM 或任意改名/内嵌代码的全量审计。

本地正反夹具：干净包树通过，放入 braces@3.0.3 后明确失败。CI 使用只读、无网络、丢弃 capabilities 的临时容器运行同一脚本；原漏洞扫描工作流保持不变。

[本轮 Web CI](https://github.com/ymasout/VPS-Agent/actions/runs/37921466616) 已成功，绑定检查提交 `7ff5c2ce1249828e61c47996e6f6d8093f1bf4ba`，输出 `WEB_RUNTIME_DEV_DEPENDENCIES_ABSENT: 139 package manifests inspected`。镜像 ID 为 `sha256:af14273549ba936cfc163580280d56f3fa2552134b0bc6d2701020212abb27d4`。Caddy Principal 与静态资产门同时通过。该结论针对 CI 构建的当前源码镜像，不代表既有生产镜像已检查或更新。

[同提交漏洞扫描](https://github.com/ymasout/VPS-Agent/actions/runs/37921466505) 仍失败，仅有 braces 一项 High，证明没有通过镜像检查绕过源码告警。本地 CI 日志保存在 `dist/braces-assessment-web-ci.log` 和 `dist/braces-assessment-osv-ci.log`。

## 批准前处置建议（历史）

最终镜像证据已通过，评估建议有条件接受本依赖在受控开发工具链中的风险，允许继续 M7.4 开发，无需无限等待补丁。若希望解除安全扫描阻断，应另外批准并实现精准、限期例外：只覆盖此漏洞和已评估版本，最长 30 天，其他漏洞继续阻断，保留原始告警并明确“存在已接受风险”。到期或评估前提变化自动恢复阻断；发布前重新核实上游与依赖树。

尚未添加任何例外，扫描仍应失败。没有将该漏洞标为误报或已修复；没有新增业务依赖/迁移，没有访问生产、部署、修改生产配置或启动 M7.4。本轮本地探测脚本及夹具位于忽略目录 dist，不提交生成产物。更新依赖后的 API 最终镜像门仍是独立事项，不由本评估替代。
