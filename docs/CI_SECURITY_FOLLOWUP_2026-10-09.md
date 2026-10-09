# 2026-10-09 CI 依赖安全复核

基线：`7960f4f97f607ac5b3dcb67c1404a213c38362f9`，开始时 main 与 origin/main 对齐且工作区干净。继续此前用户提交推送授权；没有部署或生产变更授权，本轮不访问生产 VPS、不进入 M7.4。

## 历史门与新告警

9 月 30 日修复提交的六组推送工作流全部成功：Vulnerability Scan `36676604275`、Source Distribution `36676603927`、Migrations `36676603969`、Web `36676603829`、Recovery `36676603791`、CodeQL `36676603771`。原用户报告的两项失败已关闭。

[10 月 6 日定时扫描](https://github.com/ymasout/VPS-Agent/actions/runs/37455285937) 对同一提交报告新的 Mako、PyJWT、source-map-js 和 braces 告警。10 月 9 日本地最新数据库扫描还发现 Next.js 与 sharp 新告警，因此同轮补齐其补丁。

## 本轮变更

| 依赖 | 原版本 | 更新版本 |
| --- | --- | --- |
| Mako | 1.3.12 | 1.4.3 |
| PyJWT | 2.14.0 | 2.15.1 |
| source-map-js | 1.2.1 | 1.2.2（pnpm override） |
| Next.js 及配套 ESLint 包 | 15.5.24 | 15.5.27 |
| sharp | 0.35.4 | 0.35.5 |

仅更新既有依赖版本和锁文件；没有新增功能依赖、迁移、Operation 写契约、身份模型或 Agent 协议变更。

补丁依据：OSV 2.4.0 实际扫描报告及上游 [Mako](https://github.com/advisories/GHSA-5639-2j2p-m4mx)、[source-map-js](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)、[Next.js](https://github.com/advisories/GHSA-4jqv-mc3x-m676)、[Next.js 另一告警](https://github.com/advisories/GHSA-mcj8-r9mp-w47p)、[sharp](https://github.com/advisories/GHSA-wq5f-xc86-pv6w) 公告。

## 未解决项

`braces@3.0.3`： [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)，深层嵌套模式可造成递归栈耗尽。截至本轮查询，公告 patched versions 为 None，npm 最新版本仍为 3.0.3。

`pnpm why braces` 确认来源为开发依赖 `@next/eslint-plugin-next@15.5.27 → fast-glob@3.3.1 → micromatch@4.0.8 → braces@3.0.3`，亦由 eslint-config-next 引用。开发依赖来源不等于漏洞已经修复；保留扫描失败，不添加忽略、不降低门槛。后续需要上游补丁或经验证的依赖替代方案，当前不能声明安全门全绿或具备部署放行条件。

## 验证与边界

- API：416 passed、28 skipped、3 个既有 Alembic 警告；本机未配置真实 PostgreSQL，跳过不算通过。
- Ruff 通过；依赖许可证检查 415 个包通过。
- `pnpm install --frozen-lockfile`、`pnpm check` 通过：ESLint、41 个测试文件 / 142 passed、Next.js 15.5.27 production build。
- OSV Scanner 2.4.0 显式扫描与 CI 相同的四个清单：退出 1，仅剩上述 braces 一项 High；所有本轮可更新的告警均已消失，没有忽略规则。
- 源码发布检查通过：383 个文件（382 个文本文件）；`git diff --check` 通过，仍有 LF/CRLF 提示。
- 本轮修复提交的 CI 状态需推送后确认，不将本地通过或历史 CI 结果算作新提交通过。

本地日志位于忽略目录 `dist/ci-security-oct-*.log`；没有将日志、凭据或生成产物提交。9 月的 API/Web 镜像验证属于旧依赖快照，不能证明本轮依赖组合；Web 镜像和 PostgreSQL 门以本轮提交 CI 为准。未重建 API 最终镜像，仍需在最终部署候选上验证。未连接生产、未部署、未修改生产配置。
