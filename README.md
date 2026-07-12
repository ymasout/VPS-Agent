# AI VPS 运维控制台

面向独立开发者和小团队的自托管运维控制台。本仓库是 M0 项目骨架：Next.js Web/PWA、FastAPI 控制平面、Go VPS Agent，以及 PostgreSQL、Redis 和 Docker Compose 开发环境。

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
- [开发命令速查](开发命令速查.md)

当前进度：M0 项目骨架已完成，M1 机器可见进行中。原始项目计划书作为产品基线保留，实际进度以项目状态和路线图为准。

## 快速开始

1. 复制 `.env.example` 为 `.env`。
2. 执行 `docker compose up --build`。
3. 打开 Web `http://localhost:3000`，API 文档位于 `http://localhost:8000/docs`。

停止环境：`docker compose down`。查看日志：`docker compose logs -f`。

## 本地开发与检查

- Web：`pnpm install && pnpm dev:web`
- API：`python -m pip install -r apps/api/requirements-dev.txt`，然后在 `apps/api` 运行 `uvicorn app.main:app --reload`
- Agent：在 `apps/agent` 运行 `go run ./cmd/agent`
- 全部测试：`make test`；完整检查：`make check`

M0 仅提供连通性、健康检查、结构化日志和 Agent 心跳契约，不包含生产认证、任务签名或受控操作执行。
