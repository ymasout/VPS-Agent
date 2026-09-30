# 2026-09-30 CI 安全门收尾

对象：M7.3 提交 `48c1249cfc0020e14b36d072b5e16cdddac40d41` 的失败检查。没有部署、生产配置变化、数据库迁移或 M7.4 实现。

## 原因与修复

- Source Distribution 在 Gitleaks 步骤失败：收尾报告第 18、63、77 行的临时 Docker 镜像标签被 generic-api-key 规则误判。核对它们仅为已删除测试镜像的名称，不是凭据；沿用仓库 `.gitleaksignore` 约定，仅增加对应 commit/file/rule/line 三个精确指纹，不禁用规则或忽略整个文档。
- Vulnerability Scan 报告 13 个受影响包条目、56 条漏洞记录，涉及直接/传递依赖及重复来源。没有将告警关闭或降级，改为更新修复版本并重新解析锁文件。

| 依赖 | 原版本 | 修复版本 |
| --- | --- | --- |
| Next.js 与对应 ESLint 包 | 15.5.21 | 15.5.24 |
| Vitest / mocker | 3.2.6 | 4.1.11 |
| sharp | 0.35.3 | 0.35.4 |
| brace-expansion 1.x / 5.x | 1.1.18 / 5.0.9 | 1.1.21 / 5.0.12 |
| js-yaml | 4.3.1 | 4.3.2 |
| PyJWT | 2.13.0 | 2.14.0 |
| AnyIO | 原为未固定的传递依赖 | 显式固定 4.14.2 |

Vitest 3.x 没有该漏洞补丁，因此升级测试工具大版本；现有 41 个文件 / 142 项测试无需改写即可通过。AnyIO 是既有运行时依赖，显式固定避免解析出受影响版本。应用安全契约、身份模型、Agent 协议不变。

上游依据：[Vitest 公告](https://github.com/advisories/GHSA-82fw-gwwq-j7x9)、[Next.js 公告](https://github.com/advisories/GHSA-2xp9-vwfh-vxw4)、[AnyIO 公告](https://github.com/advisories/GHSA-82r6-8w77-94w6)，其余修复版本来自本提交 OSV 检查日志。

## 本地实际验证

- 安装修复依赖后 API：416 passed、28 skipped、3 个既有 Alembic 弃用警告；环境跳过不是 PostgreSQL 通过。
- `pnpm install --frozen-lockfile`、`pnpm check`：ESLint、41 文件 / 142 passed、Next.js 15.5.24 production build 通过。
- Ruff、源码发布检查、415 个依赖许可证检查通过。
- 与 CI 同版本、校验下载 SHA-256 的 Gitleaks 8.24.3：扫描原失败提交，加入精确误报指纹后退出 0，no leaks found。
- 与 CI 同版本、校验下载 SHA-256 的 OSV Scanner 2.4.0：显式扫描同四个清单（pnpm lock、API requirements/dev requirements、Agent go.mod），退出 0，No issues found。未扫描本机忽略目录或旧验证归档。
- 原提交的 Migrations、Web、Recovery 与 CodeQL 工作流已成功；修复后的 CI 需要按新提交重新检查，不沿用旧结果。

原始本地日志位于忽略目录 `dist/ci-security-*.log`。原 M7.3 镜像验证绑定此前源码/依赖快照，不能作为此次依赖升级后的最终镜像证明；更新后镜像门由新提交 CI 重新验证。尚未部署到生产。
