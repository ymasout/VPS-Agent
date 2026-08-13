# M6.1d 灾备闭环运行手册

状态：**本地实现，待独立审计与 CI；尚未配置真实异地存储、生产 recipient 或执行生产/季度演练。**

本文描述管理员宿主机上的离线灾备工具。它没有 API、Web、Provider、Agent 或 M4 Operation 入口，不能覆盖生产数据库，也不会自动删除任何备份。

## 数据边界

- PostgreSQL：先复用 `control-plane-backup.sh` 产生的原子 `postgres.dump + manifest.json + SHA256SUMS`，再整体用 age 加密。
- 配置：只收集策略文件 `files.config` 中列出的普通文件。默认示例只含生产 Compose 与 Caddyfile；Caddy TLS/ACME 数据不打包，由隔离环境重新签发。
- 秘密：独立包，只收集 `files.secrets` 中列出的生产环境文件。与数据库包独立轮换和验证。
- Redis、日志、缓存、构建产物和整个 Caddy 数据卷不进入权威包。

所有输入都按不可信数据处理：拒绝 symlink、非普通文件、相对路径、重复逻辑名、未知 policy/manifest 字段、超限文件、archive 路径穿越、绝对路径、反斜杠、链接、特殊文件、重复项和 hash/size 不一致。

## age 固定工具链与双 recipient

`deploy/install-age.sh` 只下载官方 `FiloSottile/age` v1.3.1 `linux-amd64` 资产，固定 archive SHA-256 `bdc69c09cbdd6cf8b1f333d372a1f58247b3a33146406333e30c0f26e8f51377`。安装时验证 checksum、版本与二进制 hash，生成 `age.verified.json`；运行时拒绝 PATH 中工具、错误版本、marker 漂移或二进制 hash 漂移。恢复运行时不联网下载。

两把 X25519 identity 必须分别在离线设备上生成并以 `0600` 保存；生产只安装两行 public recipient 到 `/etc/vps-agent/backup-recipients.txt`。一个密文同时发给两位 recipient，任一 identity 均可独立解密。私钥不得进入仓库、CI secret、生产 policy、备份包或日志。

## 配置与执行

1. 将 `deploy/disaster-recovery-policy.example.json` 复制到 `/etc/vps-agent/disaster-recovery.json`，填入真实 instance/build/revision、固定源文件与两个已挂载目标根目录；随后运行 `install-disaster-recovery.sh`，把定时入口和灾备工具复制为 `/usr/local/libexec/vps-agent` 下的 root-owned 固定副本并安装 timer。
2. 两个 `failure_domain` 与解析后的目标根必须不同。脚本还比较两个目标根的设备 ID；相同时在机器结果与审计中记录 `replica_targets_share_device` 告警，但不同真实故障域仍须由管理员和外部存储证据确认。脚本在复制后重验 ciphertext、manifest 和 SHA256SUMS，并以同文件系统改名发布；已存在副本拒绝覆盖。
3. 数据库每日执行：`control-plane-backup.sh disaster-recovery`，随后 `control-plane-disaster-recovery.sh database <绝对包路径>`。systemd timer 提供这一固定链并用 `flock` 防重入。
4. 配置或秘密每次受控变更后分别显式执行 `control-plane-disaster-recovery.sh config` 与 `... secrets`，并核对两个副本结果。它们不依赖每日 timer。
5. 第一版没有保留期删除。容量不足必须告警并由管理员处理，不能自动删除本地包或异地副本。

## 月度抽检与季度演练

月度抽检必须由管理员临时接入其中一把离线 identity 并显式运行：

```text
/opt/vps-agent/current/deploy/control-plane-disaster-recovery.sh monthly-check <encrypted-package> <identity-file>
```

该命令不仅检查文件存在，还实际执行 age 解密、tar 全成员验证，并在 `0700` 临时根内工作；无论成功或异常均清理明文。季度应轮换使用两把 identity，以证明 1-of-2 可用性。

季度完整演练使用 `control-plane-drill.sh`，输入明确的数据库包、配置包、秘密包、离线 identity、独立实例 ID/凭据的隔离 env 和审计目录。源实例 ID 必须由 root-owned 策略独立提供，不能从待校验 manifest 回填。脚本只接受 `vps-agent-drill-*` 项目，使用 internal-only Compose 网络，强制清空通知、GitHub、外部 Provider、M4 签名、Principal/Caddy 写凭据和 Agent 操作密钥，不启动 Caddy、不包含 Agent；只保留演练专用 `ADMIN_API_TOKEN`。随后执行三类包解密、配置/秘密与当前可信策略源逐文件大小及 SHA-256 复核、数据库 24 小时 RPO 门、空 PostgreSQL 恢复、schema/关键数据检查、API/Web 启动、`/healthz` 和受保护 system-info。机器可读摘要分别记录三类包龄、数据库 `86400` 秒 RPO 门、配置/秘密变更驱动新鲜度与 `14400` 秒 RTO 门；数据库 RPO 或 RTO 未达标、配置/秘密与当前可信源不一致时命令失败，不输出会把三类语义混为一谈的总 `rpo_met`。

配置和秘密的承诺是“每次受控变更后立即备份”，不是按小时计算的 RPO。演练当前版本时必须与当前策略 allowlist 的源文件完全一致；若要演练历史配置包，必须先取得对应历史 checkout 和经授权的历史策略/源文件，不能拿当前 checkout 直接比较并宣称通过。

生产数据库、生产 Compose 项目、生产域名或真实 Agent 都不得作为演练目标。真实生产恢复仍是事故级单独授权。

## 当前外部阻断与授权边界

- 仓库只实现两个目标根/挂载点的适配边界；尚未选择存储提供商、真实位置或凭据，因此不能宣称“两份真实异地副本”已完成。
- 未经单独授权，不得安装生产 recipient、复制生产包、执行季度演练、提交/推送，或执行任何生产恢复。
- 本地/CI 证明不能替代真实故障域、生产 RPO 新鲜度或季度 RTO 证据；设备 ID 相同会告警，但设备 ID 不同也不能单独证明物理异地。
