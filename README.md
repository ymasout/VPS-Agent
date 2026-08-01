# AI VPS 运维控制台

面向独立开发者和小团队的自托管运维控制台。项目采用 Next.js Web/PWA、FastAPI 控制平面、Go VPS Agent，以及 PostgreSQL、Redis 和 Docker Compose；M0、M1、M2 已完成，M3 上下文与 AI 诊断已完成，M4 安全处置核心完成（重启、部署、回滚均生产验证），M5 诊断与操作会话已完成（M5.1–M5.7 均通过生产金丝雀）。

## 目录

```text
apps/
  web/       Next.js App Router 前端
  api/       FastAPI 控制平面
  agent/     Go 轻量 Agent
docs/        架构与开发约定
```

## 项目文档

- [系统架构](docs/ARCHITECTURE.md)
- [项目状态](docs/PROJECT_STATUS.md)
- [实际开发路线图](docs/ROADMAP.md)
- [Web UI 初步规划](docs/WEB_UI_PLAN.md)
- [Agent 发布、安装与升级](docs/AGENT_INSTALLATION.md)
- [开发命令速查](开发命令速查.md)
- [M3 只读诊断协议与配置](docs/M3_DIAGNOSTICS.md)
- [M3 收尾：真实仓库证据与诊断 Provider](docs/M3_CLOSEOUT.md)
- [M4 安全处置协议与验收](docs/M4_OPERATIONS.md)
- [M5 诊断与操作会话设计](docs/M5_CONVERSATION.md)
- [M5.2 GitHub 白名单仓库知识检索设计](docs/M5.2_REPOSITORY_KNOWLEDGE.md)
- [M5.3 会话到安全操作计划交接设计](docs/M5.3_OPERATION_HANDOFF.md)
- [M5.2.2 仓库上下文对话设计](docs/M5.2.2_REPOSITORY_CONVERSATION.md)
- [M5.5–M5.7 收尾统一设计](docs/M5_COMPLETION_PLAN.md)
- [M6 自托管产品化设计](docs/M6_PRODUCTIZATION.md)
- [M6.3 通知、模板与引导式配置设计](docs/M6_NOTIFICATIONS.md)
- [M6.4 协作与开源分发评估](docs/M6_COLLABORATION_OPEN_SOURCE.md)
- [M6.4b 可信 Principal 与有限只读角色](docs/M6_PRINCIPAL_READONLY.md)
- [M6.4c 角色授权与具名 M4 审批设计](docs/M6_NAMED_APPROVAL.md)
- [M6.4d 正式发行与开源分发设计](docs/M6_RELEASE_DISTRIBUTION.md)
- [正式发行流程](docs/RELEASE_PROCESS.md)
- [发行兼容矩阵](docs/RELEASE_COMPATIBILITY.md)
- [版本变更记录](CHANGELOG.md)
- [许可证范围](LICENSING.md)
- [安全报告政策](SECURITY.md)
- [贡献指南](CONTRIBUTING.md)

当前进度：M0–M5 已完成，M4 的重启、部署与显式回滚均通过生产验证。M6.1a/b 备份恢复基础、M6.2 PWA/移动体验、M6.3 多通道通知、M6.4a 源码发行门、M6.4b Principal 只读授权和 M6.4c 具名 M4 审批均已完成相应审计、CI 与生产门；M6.4d 正式发行也已完成。v0.6.1 已于 2026-08-01 正式公开发行（tag `v0.6.1`、32 资产、PVR 已启用、四条 CI 全绿、GHCR API/Web 公开可拉取），生产已于同日完成升级金丝雀并切换到 digest-pinned release 镜像（commit `8746182`）。M6.1c Agent 安全升级/失败回退与 M6.1d 灾备运行手册仍属 M6 可靠性收尾，因此 M6 整体尚未完成。详细证据见项目状态与路线图。生产现运行 `8746182 + 0020`、Principal flags OFF；任何生产操作前仍须实时核对。拉源码/构建、清理、Web SSH 与任意 Shell 仍不在当前范围。原始项目计划书作为产品基线保留，实际进度以项目状态和路线图为准。

产品终局不是要求用户逐台维护配置文件，而是“一条命令接入 VPS、自动发现服务、通过自然语言提出运维目标、按权限完成诊断或受控操作，并自动验证和审计”。M3 已增加 Docker 稳定身份、Docker/systemd 显式本地诊断策略、自动证据源目录、Web 单服务确认、GitHub App 授权仓库白名单快照，以及控制平面主动检测的 VPS 失联/恢复事件和机器级只读诊断；手工证据源配置只作为兼容入口。正式接入体验见路线图与 M3 诊断文档。

## 快速开始

1. 复制 `.env.example` 为 `.env`。
2. 启动依赖：`docker compose up -d postgres redis`。
3. 构建 API 并显式执行一次迁移：`docker compose build api`，然后运行 `docker compose run --rm --no-deps api alembic -c /app/alembic.ini upgrade head`。
4. 执行 `docker compose up --build`。
5. 打开 Web `http://localhost:3000`，API 文档位于 `http://localhost:8000/docs`。

已有的、由旧版 `create_all` 建立且没有 `alembic_version` 的开发库不能直接盖章：先运行 `docker compose run --rm --no-deps api python -m app.schema verify-adoption`，通过后再依次执行 `alembic stamp head` 和 `alembic upgrade head`。API 启动入口不会自动迁移数据库。

停止环境：`docker compose down`。查看日志：`docker compose logs -f`。

## 本地开发与检查

- Web：`pnpm install && pnpm dev:web`
- API：`python -m pip install -r apps/api/requirements-dev.txt`，在 `apps/api` 显式运行 `python -m alembic -c alembic.ini upgrade head` 后再运行 `uvicorn app.main:app --reload`
- Agent：在 `apps/agent` 运行 `go run ./cmd/agent`
- 全部测试：`make test`；完整检查：`make check`
- 源码发行候选检查：`make source-check`；依赖许可证与 REUSE 检查：先安装 `reuse[charset-normalizer]==6.2.0`，再运行 `make license-check`

## 许可证

本仓库采用按目录划分的双许可证：控制平面、Web 和默认范围为
`AGPL-3.0-only`；`apps/agent/**`、Agent 安装脚本及 Agent 发布工作流为
`Apache-2.0`。精确范围以 [REUSE.toml](REUSE.toml) 和
[LICENSING.md](LICENSING.md) 为准，第三方依赖仍受各自许可证约束。

M1 已提供 Agent 安全注册、认证上报、基础资源和 Docker/systemd/HTTP 状态采集，以及真实 Fleet/详情页面。M4 已开始提供独立 Ed25519 签名、确认、Agent 本地稳定身份解析、幂等执行、健康验证和审计；远程 Shell 始终不在本轮范围内。
