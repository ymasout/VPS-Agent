# M2 上线验证清单

> 历史归档：本文保留 M2 当时的生产验证事实和旧命令，不再代表当前部署流程。M4.1 起运行时已移除 `create_all`，数据库统一由显式 Alembic 步骤管理；当前命令见 [`deploy/README.md`](./README.md)。

> 适用范围：M2「异常可通知」从本地验证到生产控制平面的上线过程。
> 状态基线：M1 已在 4 台 VPS 上运行 Agent `v0.2.4` 并持续上报；M2 代码与测试已完成，尚未部署。

## 0. 范围与前提

- **M2 是控制平面（API）改动**。3 台外部 Agent VPS 不用动，继续跑 M1 `v0.2.4`，照常上报服务状态。告警状态机、钉钉发送、事件 API 全在控制平面。
- **建表机制**：API 启动时执行 `Base.metadata.create_all`（`app/main.py`），新增的 `alert_events`、`notification_deliveries` 会在容器重启后自动创建。Alembic 迁移（`0001`/`0002`）是 schema 基线记录，非运行时必需步骤。
- **#4 风险已基本消除**：生产 PG 从未建过 M2 表，`create_all` 会直接建出最终正确 schema（含 `notification_sequence`、`sequence`、`updated_at` 与新唯一约束）。无需担心旧迁移残留。
- 钉钉 Webhook 与加签密钥**只写服务器 `.env.production`，不发聊天、不进 Git**。

## 1. 本地 / staging 预演（不动生产）

目标：用真实 PostgreSQL + 测试钉钉机器人跑通完整闭环。

1. 起本地完整环境（`compose.yaml`，含真实 PostgreSQL）。
2. 启动新 API 代码，确认启动日志无错。
3. 验证表结构（psql 或客户端）：
   - `alert_events` 含 `notification_sequence` 列。
   - `notification_deliveries` 含 `sequence`、`updated_at` 列，唯一约束为 `(event_id, sequence, channel)`。
4. 在本地 `.env` 配**测试**钉钉机器人（不要用生产群）：
   ```text
   DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=...
   DINGTALK_SECRET=SEC...
   ```
5. 注册一个测试 Agent，让它上报一个"异常"服务（停一个容器 / 把 HTTP 健康检查 URL 指向会返非 2xx 的地址）。
6. 验证点：
   - 第 1 次异常上报：事件 `pending`，**无**通知。
   - 第 2 次异常上报：事件 `firing`，钉钉收到异常卡（含服务/机器/详情/链接）。
   - 继续重复异常上报：**不再**重复发卡（去重生效）。
   - 服务恢复：事件 `resolved`，钉钉收到恢复通知，**只一次**。
   - 静默到期重发：`POST /api/v1/events/{id}/actions` `{"action":"silence","silence_minutes":1}`，等过期后服务仍异常 → 重新 `firing` 并再发一次异常通知。
   - sending 回收：在通知发送过程中重启 API → 投递卡在 `sending` → 等 >120s 后下次上报触发重领 → 成功发送。
7. `python -m ruff check app/ tests/` 与 `python -m pytest -q` 全绿（当前基线 34 项）。

> 本地预演全部通过后再进入第 2 步。

## 2. 生产控制平面部署

1. **备份**：`pg_dump` 备份 PostgreSQL；记录当前 API 镜像 tag 与 `.env.production`。
2. **低峰期**操作。
3. 构建并拉取新 API 镜像。
4. 在服务器 `.env.production` 写入钉钉配置（其余用默认值即可）：
   ```text
   ALERT_PENDING_OBSERVATIONS=2
   DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=...
   DINGTALK_SECRET=SEC...
   NOTIFICATION_TIMEOUT_SECONDS=5
   NOTIFICATION_SENDING_STALE_SECONDS=120
   ```
   `CONSOLE_PUBLIC_URL` 已由 compose 通过 `CONTROL_PLANE_DOMAIN` 自动生成。
5. 确认 `deploy/compose.production.yaml` 的 `api` 服务已注入上述变量。
6. 只重启 API 容器（不动 postgres / redis / agent）：
   ```bash
   docker compose -f deploy/compose.production.yaml up -d --no-deps api
   ```
7. 启动后验证：
   - `curl https://你的域名/healthz` 返回 ok。
   - API 日志无异常，可见 `api.started`。
   - psql 检查 `alert_events`、`notification_deliveries` 两张新表已建且字段正确。

## 3. 关键风险与即时观测

- **核心风险**：`evaluate_service_alerts` 运行在 Agent 上报的同一事务内。若真实 PG 上告警逻辑抛异常，整份上报事务回滚 → Agent 收到 500 → 上报中断 → 机器显示离线。
- 部署后**立刻**观测：
  - API 日志中 `/agents/report` 持续返回 **200**（不是 500）。
  - Fleet 页 4 台机器保持在线、`last_seen_at` 持续刷新。
  - 一旦出现 500：立即按第 5 节回滚。

## 4. 生产杀手路径演练

1. 在某台 VPS 上停一个**非关键**容器或 systemd 服务（或将一个 HTTP 健康检查指向会失败的地址）。
2. 等待约 2 个上报周期（60–120s）→ 钉钉群收到异常卡。
3. 通过 `GET /api/v1/events`（受管理令牌）确认能看到 `firing` 事件。
4. 恢复该服务 → 钉钉收到恢复通知 → 事件转 `resolved`。
5. 演练 `POST /api/v1/events/{id}/actions` 的 `acknowledge` 与 `silence`。

## 5. 回滚预案

- **代码回滚**：拉起旧 API 镜像，`docker compose -f deploy/compose.production.yaml up -d --no-deps api`。
- **数据**：M2 仅新增两张表，不改动 M1 既有表。回滚旧镜像后新表留在库中无副作用（旧代码不读它们），**无需 downgrade**。
- 如确认彻底放弃 M2：`DROP TABLE notification_deliveries, alert_events;`（仅在确定不再使用时）。
- `.env.production` 中的钉钉密钥回滚后可保留或删除。

## 6. 验收标准

- [ ] 本地预演第 1 节全部验证点通过。
- [ ] 生产部署后 Agent 上报持续 200、4 台机器在线。
- [ ] 杀手路径：停服务 → 钉钉告警 → 恢复 → 恢复通知，全程无需 SSH。
- [ ] 静默到期重发、陈旧 sending 回收至少各验证一次。
- [ ] ruff 与 pytest 全绿。

## 7. 完成后

- 更新 `docs/PROJECT_STATUS.md`：把"真实 PostgreSQL / 钉钉验收"从 TODO 移到已完成。
- 将本次真实运行中发现的告警噪音、误报、钉钉格式问题记入后续改进。
