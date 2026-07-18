# AI VPS 运维控制台

面向独立开发者和小团队的自托管运维控制台。项目采用 Next.js Web/PWA、FastAPI 控制平面、Go VPS Agent，以及 PostgreSQL、Redis 和 Docker Compose；M0、M1、M2 已完成，M3 上下文与 AI 诊断正在实现。

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

当前进度：M0 项目骨架、M1 机器可见和 M2 异常可通知已完成；M3 上下文与 AI 诊断进行中。首个通知通道采用钉钉自定义机器人。原始项目计划书作为产品基线保留，实际进度以项目状态和路线图为准。

产品终局不是要求用户逐台维护配置文件，而是“一条命令接入 VPS、自动发现服务、通过自然语言提出运维目标、按权限完成诊断或受控操作，并自动验证和审计”。M3 已增加 Docker 稳定身份、显式本地诊断策略、自动证据源目录和 Web 单服务确认；手工证据源配置只作为兼容入口。正式接入体验见路线图与 M3 诊断文档。

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

M1 已提供 Agent 安全注册、认证上报、基础资源和 Docker/systemd/HTTP 状态采集，以及真实 Fleet/详情页面。当前仍不提供任务签名、远程 Shell 或受控操作执行。
