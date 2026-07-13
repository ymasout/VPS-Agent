# 项目状态

最后同步：2026-07-14
当前阶段：**M0 已完成，M1 进行中**

## 1. 当前结论

项目已完成 M0 骨架并进入 M1 真实环境验收。控制平面已通过 Caddy/HTTPS 部署，首台真实 VPS 已完成安全注册、持续上报以及在线/离线验证；当前继续完善服务状态语义并扩展到更多 VPS。

## 2. M0 已完成

### 项目结构

- 建立 `apps/web`、`apps/api`、`apps/agent` Monorepo 目录。
- 建立 pnpm workspace、统一根目录脚本和 Makefile 命令。
- 增加 `.env.example`、`.gitignore`、`.dockerignore` 和 EditorConfig。
- 增加中文开发命令速查文档。

### Web

- 创建 Next.js + TypeScript App Router 应用。
- 提供 M0 首页和响应式基础样式。
- 配置 ESLint、Vitest 和生产构建。
- 配置多阶段 Docker 镜像及 standalone 运行模式。

### API

- 创建 FastAPI + Pydantic 控制平面。
- 提供 `/healthz` 健康检查。
- 提供 `/api/v1/agents/heartbeat` 开发心跳接口。
- 建立环境配置和结构化 JSON 日志。
- 建立 pytest 与 Ruff 检查。

### Agent

- 创建 Go Agent、配置加载和 HTTP 客户端。
- 实现周期性出站心跳、超时和结构化日志。
- 支持系统终止信号和优雅退出。
- 配置 Go 多阶段构建和 distroless 运行镜像。

### 基础设施

- Docker Compose 包含 Web、API、Agent、PostgreSQL 和 Redis。
- PostgreSQL、Redis 和 API 配置健康检查。
- PostgreSQL 与 Redis 使用持久化数据卷。
- 修复 Windows `node_modules` 污染 Linux Web 镜像的问题。

## 3. 已完成验证

| 检查项 | 结果 |
| --- | --- |
| FastAPI pytest | 4 项通过 |
| Python Ruff | 通过 |
| Web Vitest | 1 项通过 |
| Web ESLint | 通过 |
| Next.js 生产构建 | 通过 |
| Go `go test ./...` | 通过，含 systemd 状态解析单元测试 |
| Web Docker 镜像 | 构建通过 |
| API Docker 镜像 | 构建通过 |
| Agent Docker 镜像 | 构建通过 |
| PostgreSQL/Redis 镜像 | 拉取成功 |

## 4. M0 已知限制

- Agent 心跳接口没有正式身份认证，不能暴露到不可信网络。
- 心跳只写入结构化日志，尚未持久化 Agent/VPS 状态。
- API 尚未建立数据库模型、迁移框架和 Redis 任务层。
- Agent 尚未采集 CPU、内存、磁盘或服务状态。
- Web 首页展示的是骨架状态，不是真实 VPS 数据。
- Go Agent 尚无单元测试。
- 尚未在 3 台真实 VPS 上完成验收。

## 5. 当前阶段：M1 机器可见

状态：**进行中**

### 已实现

- PostgreSQL Agent、注册令牌、资源快照和服务状态模型。
- SQLAlchemy 异步数据层与 Alembic M1 基线迁移。
- 管理令牌保护的注册令牌签发接口。
- 一次性注册令牌消费、Agent 独立凭证签发与 Bearer 认证。
- Agent 身份文件以 `0600` 权限持久化，重启后复用同一身份。
- Linux CPU、内存、根磁盘采集。
- Docker 容器、systemd 服务和配置化 HTTP 健康检查采集。
- 资源快照持久化、服务当前状态更新和在线/离线计算。
- Fleet 首页真实 VPS 总览和 VPS 详情页。
- Docker Compose 开发 Agent 自动注册及端到端上报。

### 已验证

- Compose Agent 首次注册返回 201，随后认证上报返回 200。
- 重启 Agent 后使用持久化身份继续上报，没有创建重复机器。
- 已消费注册令牌重放返回 401。
- 无效 Agent Bearer 凭证返回 401。
- Fleet API 返回在线机器、真实资源快照、5 个 Docker 服务和 1 个 HTTP 健康检查。
- Web 首页和详情页均返回 200。
- API 4 项测试、Web 测试/检查/构建和 Go 全包编译通过。
- 生产控制平面已通过 Caddy 提供 HTTPS 和管理页面基础认证。
- 首台真实 VPS 以 systemd 服务运行 Agent，并验证停止后离线、恢复后重新上线。
- 真实主机发现 171 个 systemd 服务；采集器已改用 ACTIVE 作为主状态并保留 SUB 说明，避免将正常 inactive/dead 项误报为故障。
- 详情页已改为服务概览、异常优先和按类型折叠展示，首页不再只显示无意义的服务总数。
- GitHub Release 工作流已支持自动测试、Linux amd64/arm64 构建、SHA-256 校验和 Release 产物上传。
- 一键安装器已支持架构识别、校验下载、交互式令牌输入、systemd 托管、身份保留升级和注册后令牌清理。
- 首个正式版本 `v0.2.2` 已由 GitHub Actions 发布；Release 中的 amd64/arm64 二进制、安装器和 SHA-256 校验均已重新下载验证。

### 尚未完成的验收

- 接入并稳定运行 3 台真实或测试 VPS。
- 将修正后的 Agent 发布到真实主机并复核 systemd 运行、停止和失败三类状态。
- 使用 `v0.2.2` Release 安装器完成剩余两台 VPS 的实机安装验证。
- 再接入 2 台真实或测试 VPS，完成 3 台稳定运行验收。
- 继续增加 Go 采集器和客户端边界测试。

完整计划交付：

- 一次性 Agent 注册令牌与绑定。
- 可轮换的 Agent 身份凭证。
- 心跳持久化、在线/离线判断与断线恢复。
- VPS 主机信息以及 CPU、内存、磁盘采集。
- Docker 容器与 systemd 服务状态采集。
- HTTP 健康检查。
- Web Fleet 首页展示真实 VPS。
- VPS 详情页展示资源和服务状态。

关键验收：

- 至少 3 台真实或测试 VPS 稳定接入。
- Agent 重启后恢复同一身份，不产生重复 VPS。
- 无效、过期、已使用令牌无法注册。
- 首页和详情页稳定显示真实资源与服务状态。
- Agent 失联能根据最后心跳正确显示离线。

## 6. 文档维护规则

- 架构或协议发生变化时更新 `ARCHITECTURE.md`。
- 每个里程碑开始和完成时更新本文件。
- 范围、状态或验收条件变化时更新 `ROADMAP.md`。
- 原始项目计划书作为产品基线保留，不用实际进度覆盖原文。
