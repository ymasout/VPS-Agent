# M3 收尾计划：真实仓库证据与诊断 Provider

本文冻结 M3 从“进行中”到“已完成”的最后范围。M3 已有 Docker/systemd 有限取证、GitHub App 白名单快照、双端脱敏、结构化诊断、真实引用、失联诊断和生产闭环；收尾不重新开发诊断平台，只补齐尚缺的生产证据与真实模型门。

当前状态：**M3 收尾完成，两项生产金丝雀于 2026-07-26 通过，M3 标记为完成。**

## 1. 完成门

M3 只剩两个必须关闭的生产门：

1. 真实 GitHub 白名单文件以 `repository_file` 证据进入一个真实 M3 `DiagnosticRun`，诊断事实或推断引用对应 `EvidenceItem`，并形成 `DiagnosticCitation`。
2. M3 自身的 `DIAGNOSTIC_PROVIDER=http_json` 在生产非关键事件上完成一次受控真实模型调用；M5 Conversation Provider 的金丝雀不能替代该证明。

同时必须证明：

- Provider 只收到本轮有界、已脱敏的证据，不获得工具权限；
- Provider 未知引用、超时、HTTP 错误、超大响应、非法 JSON 和非法 schema 受控失败；
- 诊断请求不创建 Operation、不领取 Operation、不访问任意路径，也不改变 M4 状态机；
- 金丝雀前后 Operation/Transition、GitHub 文件与绑定保持预期不变；
- 验证后恢复 `DIAGNOSTIC_PROVIDER=deterministic`。

## 2. 非目标

- 文件日志或任意文件系统路径读取；
- 自动诊断调度和通用持久任务队列；
- 整仓同步、向量数据库、复杂 RAG 或全仓搜索；
- GitHub 写、Shell、重启、部署、回滚或自动修复；
- 修改 M4 签名、确认、领取、执行、验证或审计协议；
- 为收尾升级全部 Fleet Agent。

这些能力保留为后续增强，不阻塞 M3 完成。

## 3. 审计发现与本地加固

真实 Provider 金丝雀前需要补齐以下与 M5 同级的基础门：

- `DIAGNOSTIC_PROVIDER` 只允许 `deterministic|http_json`；选择 `http_json` 时启动期要求 `DIAGNOSTIC_API_URL`。
- `DIAGNOSTIC_MAX_CONTEXT_BYTES` 默认 128 KiB，限制发送给 Provider 的证据正文总量。
- 服务端按固定优先级选择证据：事件/状态、指标、部署版本、仓库文件、有限日志；问题或证据正文不能扩大作用域。
- 预算裁剪只影响 Provider 上下文，不删除已持久化证据；诊断结果在 `missing_evidence` 标记发生过省略或截断。
- HTTP Provider 响应上限 256 KiB；超时、非 2xx、连接失败、非法 JSON 分别保存固定错误码，不保存响应正文或底层异常。
- `DiagnosticResult` 及嵌套事实、推断和建议使用 `extra="forbid"`；Provider 不能夹带工具调用或未知字段。
- 事实和推断只能引用实际发送给本轮 Provider 的 evidence ID；未知引用整轮失败。
- Provider 异常不把凭据、URL 查询串、响应正文或证据正文写入 `error_detail`。

本切片不新增数据库迁移或 Agent 协议。

## 4. Provider 契约

请求仍由控制平面主动发送到管理员配置的固定 URL：

```json
{
  "model": "ops-diagnostic",
  "instructions": "固定只读诊断指令",
  "evidence": [
    {
      "evidence_id": "UUID",
      "type": "repository_file",
      "source": "GitHub owner/repo · README.md",
      "untrusted_content": "bounded and redacted content"
    }
  ]
}
```

响应可直接返回 `DiagnosticResult`，也可包装为 `{ "result": DiagnosticResult }`。结构固定为 summary、facts、inferences、recommendations、missing_evidence；没有 tool calls、命令或操作参数字段。

受控失败码：

| 错误码 | 条件 |
| --- | --- |
| `provider_timeout` | 请求超时 |
| `provider_http_error` | 非 2xx 或网络失败 |
| `provider_response_too_large` | 响应超过 256 KiB |
| `provider_invalid_json` | 响应不是合法 JSON |
| `provider_invalid_schema` | JSON 不符合严格诊断结构 |
| `provider_unknown_citation` | 引用未发送或不存在的 evidence ID |
| `provider_internal_error` | 其他未预期 Provider 失败的固定墓碑 |

## 5. 仓库证据真实性

生产证明必须沿现有唯一链路产生：

`AlertEvent -> ServiceInstance -> DeploymentVersion -> Repository -> enabled GitHubRepositoryBinding -> GitHubRepositoryFile -> EvidenceItem(repository_file) -> DiagnosticResult -> DiagnosticCitation`

要求：

- 事件、实例、仓库和诊断属于当前组织；
- Binding 当前启用，文件来自控制平面已有白名单快照；
- evidence 的 metadata 记录 repository/path/commit/head，不把仓库正文写入日志；
- 二次脱敏后再进入 Provider；
- 诊断引用必须指向本轮真实 `EvidenceItem.id`；
- 不触发 GitHub 同步，金丝雀只读取已存在快照。

## 6. 本地测试矩阵

- 配置拒绝未知 Provider，`http_json` 缺 URL 启动失败。
- HTTP Provider 正常结构通过。
- timeout、HTTP/连接错误、超大响应、非法 JSON 产生固定失败码。
- 严格 schema 拒绝额外 `tool_calls`。
- 上下文总预算生效，仓库证据不会被低优先级大日志先挤出。
- 未知 evidence 引用失败关闭。
- Provider 失败只保存固定详情。
- 真实 PostgreSQL 验证仓库快照进入 `EvidenceItem(repository_file)`，确定性 Provider 引用它并生成 `DiagnosticCitation`。
- PostgreSQL 测试前后 Operation 数量不变。
- API、Web、Go、Ruff、ESLint、构建和 Compose 回归通过。

新增 PostgreSQL 门控使用 `M3_TEST_DATABASE_URL`；没有该变量时常规测试跳过。

## 7. 兼容推广门

以下两项建议在扩大 Agent 覆盖前补证，但不阻塞 M3 完成：

1. 旧 Agent 未显式配置 `AGENT_EVIDENCE_POLICY` 时升级后仍保持 `disabled`。
2. 存在真实旧容器身份数据时，验证 container ID 到稳定 service key 的事件与映射迁移。

若当前生产没有可安全复现的旧数据，保留为版本推广检查项，不为制造证据而修改生产身份。

## 8. 生产金丝雀边界

只有用户明确授权后执行：

1. 备份、部署、postflight；本切片无迁移。
2. 保持 M4 能力与全部会话写交接开关关闭，记录 Operation/Transition 基线。
3. 选择已有 GitHub 映射和仓库白名单快照的非关键服务事件。
4. 先用 deterministic Provider 触发一次诊断，确认存在 `repository_file` EvidenceItem、事实/推断引用和 DiagnosticCitation。
5. 配置国内可达的临时 `http_json` 网关，仅对同一非关键范围触发一次新诊断。
6. 验证严格结构、真实引用、脱敏和日志；Provider 失败时不得改用不受控输出。
7. 前后核对 Operation/Transition、GitHub 文件/binding 和 Agent 策略无非预期变化。
8. 恢复 `DIAGNOSTIC_PROVIDER=deterministic`，移除临时凭据或适配器，执行 postflight。

不得把自然语言建议当作写授权，不得通过本次金丝雀确认或执行任何 M4 Operation。

## 9. M3 完成判定

两个生产门通过并同步 `README.md`、`PROJECT_STATUS.md`、`ROADMAP.md` 与 `M3_DIAGNOSTICS.md` 后，M3 可以标记为完成。文件日志、自动调度、完整仓库同步、独立任务队列和两项兼容推广门继续进入后续 backlog，不应让已闭合的 M3 长期保持“进行中”。

## 10. 2026-07-26 本地进度

- README 的 M5 残留状态已修正。
- Provider 配置、预算、严格 schema、引用和失败处理加固已实现。
- API `206 passed, 9 skipped`；Web `67 passed`；Ruff、Python compile、ESLint、Next.js production build、Go test/vet 和开发 Compose 配置通过。
- 新增 `test_m3_closeout_postgres.py`，用于验证真实 PostgreSQL 仓库证据与引用链及 Operation 零副作用。
- Docker Desktop 恢复后，新增门控已在临时 PostgreSQL 16 单独通过：空库迁移到 `0017_m5_runbook_drafts`，真实 `repository_file` 进入诊断且完成脱敏，确定性 Provider 的事实引用形成 `DiagnosticCitation`，Operation 数量不变，`python -m app.schema check` 通过；临时容器已删除。
- 未提交、未推送、未部署，未触发生产诊断或 Provider 调用。

2026-07-26 生产金丝雀结果：部署 ff4f5bc（M3 加固代码，无迁移）+ postflight。完成门1：对 m4-deploy-bad 事件 6b112ab3 触发 deterministic 诊断 -> completed，EvidenceItem(repository_file, path=README.md) + DiagnosticCitation 引用，ops/trans 13/81 不变。完成门2：配置 DIAGNOSTIC_PROVIDER=http_json + 临时 DeepSeek 适配器，触发诊断 -> failed/provider_timeout（DeepSeek >30s 超时受控），provider:http_json 不回退 deterministic，error_detail 固定字符串无凭据，ops/trans 不变。还原 DIAGNOSTIC_PROVIDER=deterministic。M3 标记为完成。
