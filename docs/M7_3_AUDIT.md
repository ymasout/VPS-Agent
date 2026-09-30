# M7.3 独立复核与镜像门记录

2026-09-30 收尾完成：日期边界 P3 已修复；PostgreSQL 相关 53 项通过（新增 10 项并发/新进程测试另复跑两次全部通过），API 最终镜像健康、HTTP、schema 与两套隔离 Compose 解析通过。测试资源已清理，五个生产容器前后完全一致。本地 API 416 passed / 28 skipped / 3 warnings，Web 142 项与 lint/build 通过；环境跳过不记作数据库通过。未提交、推送、部署，CI 尚未执行当前快照，未开始 M7.4。详见 [本轮收尾证据与限制](./M7_3_API_CLOSEOUT_2026-09-30.md)；下文旧状态保留为历史。

2026-09-30 后续：用户明确授权 VPS 隔离验证后，Web 最终镜像和真实 Caddy 门已通过，生产服务未替换；见 [最终镜像证据](./M7_3_IMAGE_GATE_2026-09-30.md)。下文是 09-29 审计时点的阻塞记录，不再代表 Web 镜像门当前状态；日期输入 P3 与 PostgreSQL 门仍待处理。

日期：2026-09-29。对象：`main` 的 `86f4adf028ec720c1dfedbe32037fb39d453cfe1` 加现有未提交 M7.3 修改，不代表已提交或生产版本。

## 结论

源码与应用层复核未发现 P0/P1 或 Operation 授权、确认、执行契约回归。发现一项 P3 输入边界问题，尚未修复；最终 Linux 镜像门仍阻塞，不能宣称全部验收门通过。本轮只增加审计记录，保留既有实现，不提交、推送或部署。

复核覆盖只读列表的授权依赖、摘要字段、筛选及 keyset 分页；动作归一化与未知类型降级；具名确认空正文、maker-checker、离线/过期/刷新停滞禁用和核对状态重置；既有确认及回滚端点未变。客户端控件不是授权边界，最终仍由原有 API 与 Agent 策略强制。

## 发现与限制

- **P3：极端时间筛选返回 500。** `apps/api/app/operation_inventory.py` 中 `since/until.astimezone(UTC)` 未处理越界。通过现有 `test_operation_inventory.py` 的真实 HTTP/SQLite fixture 复现：`since=0001-01-01T00:00:00+01:00` 或 `until=9999-12-31T23:59:59-01:00` 均抛出 `OverflowError: date value out of range`。建议转换失败返回固定 422，补两端边界及游标时间回归。普通日期筛选不受影响，不涉及授权绕过。本轮为审计，未擅自修实现。
- 分页总数不是跨请求快照；机器/身份筛选仍使用稳定 ID。这是已有交付限制。
- 本轮未重跑浏览器夹具；桌面/移动交互结果沿用前次记录，不冒充新的独立行为验证。

## 本轮独立复跑

| 命令 | 结果 |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest -q apps/api/tests` | 390 passed，18 skipped，3 warnings；警告为既有 Alembic path_separator 弃用提示 |
| `.venv/Scripts/python.exe -m ruff check apps/api` | All checks passed |
| `pnpm check` | ESLint、Web Vitest 41 文件 / 142 项、Next production build 全通过 |
| `git diff --check` | 通过，仅既有 LF/CRLF 提示 |

18 项环境相关跳过不等于 PostgreSQL 集成通过。没有新增依赖、迁移或安全开关修改。

## 最终镜像门阻塞

尝试启动本机 Docker Desktop 后，后台在初始化 Inference manager 时失败，无法访问运行时端点 `C:/Users/Admin/AppData/Local/Docker/run/dockerInference`，错误为 `The file cannot be accessed by the system`；Linux engine 未就绪。该对象显示为零字节 reparse point；未删除、重命名或重置它，亦未执行 factory reset、prune、WSL unregister 或数据卷清理。

备用检查：本地 Ubuntu-22.04 WSL 没有独立 dockerd、Podman 或 BuildKit，仅能找到 Desktop 提供的 Docker 客户端。因此本轮没有成功构建/运行最终镜像，也没有新镜像 digest 或容器健康证明。相同启动症状见 [Docker 上游问题 #625](https://github.com/docker/desktop-feedback/issues/625)，该报告不是已验证的修复方案。

解除阻塞后，应在本地可用 Linux 引擎或经授权的 CI 构建环境，对同一代码快照执行 `.github/workflows/control-plane-web.yml` 的真实 Caddy Principal 集成、最终 standalone 镜像构建/启动、manifest/service worker/offline/icon 四资产检查，并确认容器 healthcheck。Windows `next build` 不替代该门。不得使用生产主机临时代跑，也不得把先前提交的 CI 结果归给当前未提交修改。

## Agent 失联/恢复通知排查结论

这是另一个问题，未修改通知逻辑或生产参数。用户报告多台机器反复失联/恢复；尚未读取生产日志，不能确定共同根因或实际生效参数。

- 代码默认上报间隔 `AGENT_REPORT_INTERVAL=30s`，离线阈值 `AGENT_OFFLINE_AFTER_SECONDS=90`，巡检间隔 `AGENT_AVAILABILITY_SCAN_INTERVAL_SECONDS=30`。
- Agent 超时即进入 firing；第一份恢复上报即 resolved。持续离线不会每次巡检都新建通知，但恢复后再超时会创建新事件，因而网络/采集抖动可能反复发送一对消息。
- `ALERT_PENDING_OBSERVATIONS` 是服务告警的待确认观测次数，不作用于 Agent 失联；通知测试冷却时间也不是普通告警冷却。
- 多机同一时间发生应优先检查控制平面/Caddy、共享链路及负载；不同时间发生则按机器核对采集耗时、上报失败与网络。Agent 上报前先采集，采集延迟或失败也可能使报告变旧。
- 不建议单独拉长上报间隔。先保留 30 秒上报，依据真实上报间隔分布评估将离线阈值从 90 秒调整到约 180 秒；代价是真实离线更晚被发现。该数字是候选值，不是已确认的生产配置。
- 后续可独立设计恢复稳定窗口与抖动通知合并；保留真实在线状态和全部事件审计，不把延迟恢复通知等同于伪造健康，不改变 Operation 新鲜度/健康验证门。生产读取、参数调整与通知功能实现应分别明确范围。
