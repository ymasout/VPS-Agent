# 生产部署

生产环境由 Caddy 对外提供 80/443，Web、API、PostgreSQL 和 Redis 仅在 Docker 内部网络通信。

## 启动

```bash
cd /opt/vps-agent-console
cp deploy/.env.production.example deploy/.env.production
chmod 600 deploy/.env.production
# 编辑真实域名、密码哈希、数据库密码和管理令牌
nano deploy/.env.production
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml config
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml build
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml up -d
```

## 检查

```bash
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml ps
docker compose --env-file deploy/.env.production -f deploy/compose.production.yaml logs -f caddy api
curl https://你的域名/healthz
```

浏览器访问域名时使用 `CADDY_ADMIN_USER` 和生成哈希前的原始密码登录。

首页“接入新机器”功能由 Web 服务端通过内部网络调用 API。`ADMIN_API_TOKEN` 同时注入 Web 和 API 容器，但不会出现在浏览器 JavaScript 或页面源码中；能够通过 Caddy 登录的用户视为控制平面管理员，可以创建一次性 Agent 注册令牌。

`/agent-downloads/*` 是无需登录的 Agent Release 下载中转，仅允许固定的安装器、校验文件和 amd64/arm64 二进制。它用于目标 VPS 无法稳定连接 GitHub CDN 时从控制平面同域下载公开产物。
