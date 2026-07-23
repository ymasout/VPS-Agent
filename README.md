# AI VPS 运维控制台

面向独立开发者和小团队的自托管运维控制台。项目采用 Next.js Web/PWA、FastAPI 控制平面、Go VPS Agent，以及 PostgreSQL、Redis 和 Docker Compose；M0、M1、M2 已完成，M3 上下文与 AI 诊断进行中，M4 安全处置核心完成（重启、部署、回滚均生产验证）。

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
- [M4 安全处置协议与验收](docs/M4_OPERATIONS.md)
- [M5 诊断与操作会话设计](docs/M5_CONVERSATION.md)

当前进度：M0 项目骨架、M1 机器可见和 M2 异常可通知已完成；M3 上下文与 AI 诊断进行中；M4 安全处置核心完成（重启、部署、回滚均生产验证）；M5 进行中，M5.1 事件只读会话已完成本地实现与真实 PostgreSQL 验证，尚未生产部署。拉源码/构建、清理和 Shell 为后续扩展。首个通知通道采用钉钉自定义机器人。原始项目计划书作为产品基线保留，实际进度以项目状态和路线图为准。

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
