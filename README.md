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

当前进度：M0 项目骨架、M1 机器可见、M2 异常可通知、M3 上下文与 AI 诊断和 M5 诊断与操作会话体验均已完成；M4 安全处置核心完成（重启、部署、回滚均生产验证）。M3 的真实仓库文件诊断引用与 `http_json` Provider 两项收尾生产门已于 2026-07-26 通过。M6.1“可验证的控制平面备份与离线恢复基础”已由 codex 实现、Claude 审计通过，提交 `38b8d40` 推送至 main，并于 2026-07-27 通过生产金丝雀（在线备份 + 隔离恢复，零生产副作用）。M6.2 PWA、移动只读和 M4 独立审批已完成生产验证。M6.3a/b 已完成生产验证；M6.3c+d 已由 codex 实现、Claude 审计通过（P0 revision 长度超 varchar(32) 已修复），提交 `ece22d5`+`1073969` 推送至 main，三个 CI 全绿，并于 2026-07-29 通过生产金丝雀（迁移 0019 + 多通道视图 + backfill + 零副作用；Telegram 实发留待管理员启用该通道时验证）。生产现运行 `1073969`，迁移 head 为 `0019_m6_multichannel_notify`，仅启用钉钉；M6.3 完成。M6.4 协作与开源分发已完成第一轮设计审计，代码实现尚未开始。没有 Agent 协议或 M4 状态机变更。拉源码/构建、清理和 Shell 为后续扩展。原始项目计划书作为产品基线保留，实际进度以项目状态和路线图为准。

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

M1 已提供 Agent 安全注册、认证上报、基础资源和 Docker/systemd/HTTP 状态采集，以及真实 Fleet/详情页面。M4 已开始提供独立 Ed25519 签名、确认、Agent 本地稳定身份解析、幂等执行、健康验证和审计；远程 Shell 始终不在本轮范围内。
