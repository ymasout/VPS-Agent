# M7.3 与 Agent 通知防抖收尾验证

日期基线：2026-09-30，Asia/Shanghai。仅本地未提交修改；未 commit、push、部署或修改生产配置，没有开始 M7.4。

## 当前状态

**本轮收尾门通过**：日期边界已修复；真实 PostgreSQL 相关测试 53 passed，其中新增 10 项并发/新进程场景另连续复跑两次全部通过；API 最终镜像构建、健康、HTTP 与 schema 验证通过。隔离资源及远端目录已清理，五个生产容器前后白名单字段完全一致。所有修改仍未提交，GitHub CI 尚未执行当前快照，通知防抖未部署。

本记录更新此前“日期输入 P3 待修”的当前结论；之前的 Web 最终镜像门仍为通过，见 [Web 镜像记录](./M7_3_IMAGE_GATE_2026-09-30.md)。历史审计条目保留原时点含义。

## 工作区与源码身份

- 开始时 `main` 与本地 `origin/main` 引用对齐，HEAD `86f4adf028ec720c1dfedbe32037fb39d453cfe1`。25 个已跟踪修改、15 个未跟踪文件，无暂存；已跟踪 diff 为 356 insertions / 165 deletions，diff check 通过，仅 LF/CRLF 提示。
- 保留所有既有 M7.3 和通知防抖成果，未改 Operation 写契约、身份模型、Agent 协议、数据库结构；没有新增依赖或迁移。
- 本轮代码增量：`operation_inventory.py` 的 UTC 越界拒绝；`test_operation_inventory.py` 增加 8 项回归；新增 `test_agent_notification_debounce_postgres.py` 的 10 项并发/新进程场景；`control-plane-migrations.yml` 显式执行该文件。
- 首轮构建归档 `dist/m73-api-closeout-20260930.tar.gz`：380 个源码/文档文件，2,394,586 字节，SHA-256 `912c13cd960d4b52053a8d639ff944b881bf13edd4f3702253c782be14a7437d`。包含当前 dirty 源码和新增文件，排除真实环境文件、Git 元数据、依赖和构建缓存；只包含受版本管理的示例环境文件。
- 逐文件 SHA-256 保存在 `dist/m73-api-closeout-manifest.json`。后续收尾文档不属于该已冻结构建包；最终清单及一致性核对见下文。
- 测试镜像 tag：`vps-agent-api:m73-api-20260930-912c13cd`；revision label 明确标记 `86f4adf-dirty-912c13cd960d`，不是正式提交身份。

## 日期问题复现与修复

新增 HTTP 回归先在旧实现执行：6 项失败。两端边界分别用于 since/until，4 项抛出 `OverflowError: date value out of range`；同样的两个游标日期在 SQLite 下被接受，未在 SQL 前拒绝。

- `0001-01-01T00:00:00+01:00` 转 UTC 下溢。
- `9999-12-31T23:59:59-01:00` 转 UTC 上溢。

现通过共同 UTC 归一化函数处理，since/until 转换失败返回固定 `422 / invalid operation time range`，游标解析/归一化失败返回固定 `422 / invalid operation cursor`，不执行 SQL。无时区仍解释为 UTC；合法偏移日期归一化为同一时刻。额外 2 项验证合法偏移/无时区游标与筛选指纹、分页的等价性。列表测试 `21 passed`。

## PostgreSQL 测试设计与证据边界

复用 `M6_TEST_DATABASE_URL` 和现有依赖，每项使用随机独立 schema，仅创建 Agent/Event/Delivery 三表，结束删除自身 schema。数据库来自独立临时 PostgreSQL 容器，不连接生产库。没有真实发送：通知适配器被测试替身替换。

10 项覆盖（发送先行场景为两渠道 × 三结果）：

1. 扫描持有 Agent 行锁时，另一扫描通过 SKIP LOCKED 跳过；释放后多扫描竞争仅保留每渠道一条逻辑投递，91 秒只有事件、180 秒才建投递。
2. 恢复事务先持有事件锁，领取 pending firing 的任务实际在 PostgreSQL 等待；恢复提交后抑制 firing 及孤立 resolved。
3. 同样的恢复/领取竞争用于已有超时失败的 firing 重试，保存尝试次数及错误，只放行对应渠道恢复。
4. 分别由钉钉/Telegram 先持久化 sending，暂停外部发送；第二 worker 不重复发送，恢复只配对已尝试渠道。
5. 上述两渠道各覆盖成功、超时、拒绝；恢复后旧失败投递不重新发送，未尝试渠道不发孤立恢复。

同步依赖 asyncio Event、数据库 `pg_blocking_pids` 实际锁等待与有界超时；10ms 轮询只用于观察数据库等待条件，不靠任意 sleep 猜测顺序。连接池 dispose 后用新连接读取/重试验证持久化状态；这不是操作系统强杀进程或外部渠道 exactly-once 证明。独立 schema 的三表测试也不替代完整迁移门，迁移/最终镜像需分别验证。

## 本地验证

| 命令 | 本轮实际结果 |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest -q apps/api/tests` | 416 passed、28 skipped、3 warnings；28 包括新增 10 项 PostgreSQL 环境门，不能记为通过；3 项仍为 Alembic path_separator 弃用提示 |
| `.venv/Scripts/python.exe -m ruff check apps/api` | 通过 |
| `pnpm check` | ESLint、41 个 Web 测试文件 / 142 passed、Next.js production build 通过 |
| 两套 `docker compose ... config --quiet` | 本机 docker 命令不存在，均未执行成功；隔离 VPS 两套解析均退出 0，未重装本地 Docker |
| `git diff --check` | 通过，仅换行提示 |

日志保存在本地忽略目录 `dist/m73-closeout-api-local-final.log`、`dist/m73-closeout-web-local.log`、`dist/m73-closeout-diff-check.log`。

## VPS 隔离与资源收尾

执行前只读检查：8 CPU、约 6.3 GiB 可用内存、62 GiB 空闲磁盘，load average 0.57/0.31/0.43。生产 API/Web revision 实际仍为 `30c32491350b099463bd376b7aa8d772c07f306f`。五个生产容器均 running，API/Web/PostgreSQL/Redis healthy，重启次数均 0，Caddy 没有 healthcheck。

- 精确远端目录：`/tmp/vps-agent-m73-api-20260930-912c13cd`。
- 独立 builder / 内部网络：`m73-api-20260930-912c13cd`；builder 实测 memory 与 swap 均 3221225472，CPU quota/period 200000/100000，单并发构建。
- 测试容器名：`m73-api-20260930-912c13cd-pg`、`m73-api-20260930-912c13cd-tests`，运行门使用 `m73-api-20260930-912c13cd-runtime`。
- PostgreSQL 限额 0.5 CPU / 512 MiB、tmpfs 数据目录；测试 worker 1 CPU / 768 MiB，运行门 0.5 CPU / 384 MiB。网络 internal，无宿主机发布端口，无生产卷挂载，使用虚构测试凭据。
- 测试辅助镜像 `vps-agent-api:m73-api-20260930-912c13cd-tests`；不替代最终运行镜像验证。

已取回全部证据；按准确名称/标签删除 pg/tests/retest/finaltests/runtime 五个测试容器、内部网络、专用 builder 及其缓存、三个测试镜像。测试 schema 残留为 0，标签查询容器/网络为空，仅剩原默认 builder。校验证据包与 realpath 后删除精确远端目录；未执行全局 prune，官方基础镜像缓存保留。五个生产容器的 ID、镜像、StartedAt、RestartCount、状态、健康及 revision 前后逐字段完全一致。

## 当前限制与后续

未获得本轮提交、推送或部署授权，GitHub CI 尚未对当前 dirty 快照执行。通知阈值默认 180 秒，真实离线/Operation 前置检查仍为 90 秒；通知扫描通常 180–210 秒加排队耗时，已开始网络发送无法撤回，超时不能证明渠道没收到。

本次范围内具备提交前技术条件，但尚无提交授权，不代表 CI 全绿或生产已启用防抖。应获授权提交推送、检查 CI，再经授权部署与观察；随后进入 M7.4。历史 Web 镜像结果沿用同日独立证据，本轮 Web 源码未修改。


## 最终源码、PostgreSQL 与 API 镜像结果

- 最终构建包 `dist/m73-api-final-20260930.tar.gz`：381 文件、2,400,909 字节，SHA-256 `541410acf03ca8a01c86faecddc3608254cc0c964fbfd30eee3d17ebc4f99791`。逐文件清单 `dist/m73-api-final-manifest.json`；当前 apps/、CI、deploy/、根 Compose 与示例配置均与最终清单一致。收尾报告在源码包冻结后更新，不改变测试过的应用代码。
- 最终镜像 tag `vps-agent-api:m73-api-20260930-912c13cd-final`；ID **`sha256:52d2485540c1836c9563e9c5e2f4bb89ace28ffd1d8d54014a4b5420529c591b`**；revision label `86f4adf-dirty-541410acf03c`，版本 `audit-m73-dirty`，构建时间 `2026-09-30T04:53:06Z`（北京时间 12:53:06）。按仓库 Dockerfile 和固定基础 digest 构建，不是正式提交镜像，验证后已删除。
- PostgreSQL **16.14**。独立空库执行 create_all adoption fixture、verify-adoption、stamp head、upgrade head、schema check 与 retained-data assert 均通过，head 保持 `0020_m6_named_approval`。三表并发测试和完整 schema 门分别验证，无新迁移。
- 最终测试文件：新增 debounce PostgreSQL、既有 M6 notification-tests/multichannel/named-approval 三个 PostgreSQL 文件、Operation 列表及 SQLite 防抖文件。结果 **53 passed、0 skipped、1 warning**，其中 15 项真实 PostgreSQL 测试；新增 10 项又连续复跑两次，分别 **10 passed / 10 passed**。最终测试容器退出 0。
- 第 10 项使用全新 Python 解释器，只传数据库/schema：扫描不重复建单，恢复继续依据持久化的渠道尝试记录配对，没有继承父进程 Python 状态。这验证进程重建后的数据语义，不是发送途中操作系统强杀的演练，也不证明外部渠道 exactly-once。
- 远端唯一 warning 为 Starlette 的 TestClient/httpx 弃用提示，未为此新增依赖。本轮未运行全部 M3/M5 PostgreSQL 门，不能把本地其他环境跳过项记为通过。
- 最终 API 容器启用正常数据库 startup/schema 验证（没有跳过初始化），原 healthcheck 达到 **healthy**，RestartCount **0**，运行用户 **10001:10001**，限额 **0.5 CPU / 384 MiB**，无公开端口。
- 最终镜像内实际 HTTP 验证 `/healthz`、真实 PostgreSQL 空 Operation 列表、六个越界 since/until/cursor 返回固定 422、合法 +08:00 日期返回 200、默认离线 90 秒/通知 180 秒、没有外部通知凭据；输出 `FINAL_API_IMAGE_HTTP_GATE_PASSED`。`python -m app.schema check` 通过。

## 失败过程与修正

保留失败证据，不把首轮失败省略为一次通过：

1. 首轮真实测试 **45 passed、7 failed**。测试冻结通知时钟却未同步 ORM defaults/onupdate，新 sending 被误判为陈旧；锁观察事务复用统计快照，漏看新连接的锁等待。统一测试时钟并用 AUTOCOMMIT 观察后 9 项通过，再补新进程场景完成最终三轮验证。没有因此改写业务通知实现。
2. 首轮执行后本机 ssh-agent 停止，取证/清理一度阻塞；用户解锁后复用原隔离环境续跑。没有重建生产服务。
3. 首轮 API HTTP 检查漏写健康响应中既有的 `service: api` 字段而断言失败；按 `test_health.py` 修正验证脚本后通过，没有修改健康接口。
4. 开发 Compose 初次解析因构建包不含真实 `.env` 而失败，其 `env_file: .env` 为既有要求。仅在隔离目录复制 `.env.example` 为 `.env` 后，两套原解析命令均退出 0；未读取或复制生产环境文件，也未运行 compose up。

## 生产未变化与证据保留

| 生产容器 | 镜像 ID（前后相同） | 状态 / 重启次数 |
| --- | --- | --- |
| API | `sha256:1f4423716da7a9850afe748d886d1c0962b1cbf756955a1072f96ebb5550244f` | healthy / 0 |
| Web | `sha256:8cfc603ae7c822959c56cc02c47103cd04bb53ef59333da396fe373da1cac3c7` | healthy / 0 |
| PostgreSQL | `sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777` | healthy / 0 |
| Redis | `sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2` | healthy / 0 |
| Caddy | `sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648` | running（无 healthcheck） / 0 |

API/Web StartedAt 仍分别为 `2026-09-08T10:33:55.206318793Z` / `2026-09-08T10:34:06.502342318Z`，revision 均为 `30c32491350b099463bd376b7aa8d772c07f306f`。完整五容器 ID 和时间见 `production-before.json` / `production-after.json`，脚本逐字段比较完全相同。收尾可用内存约 6.25 GiB、空闲磁盘 62 GiB。

原始证据包 `dist/m73-api-evidence-20260930.tar.gz` SHA-256 **`96b780dc2d1e516cf8e500894a575b1ecbd4b4a659d8ce8eca046249190f3b1e`**。本地/远端 hash 一致，解包到 `dist/m73-api-evidence-20260930/`，含构建、失败与最终测试日志、schema/HTTP/Compose 结果、资源限制、生产前后白名单快照和资源清理日志。取回校验后，远端精确目录已删除，返回 `VERIFIED_TEST_DIRECTORY_REMOVED`。源码包与清单保留在本地忽略目录，不携带生产凭据。
