# M6.1d 灾备闭环运行手册

状态：**已实现并通过独立审计；备份/复制链路已于 2026-08-16 生产激活（age 工具链、root-owned 策略与双 public recipient、每日 systemd timer、本地 + 异地 SSHFS 双副本，沙箱全链实测通过）；仍待月度解密抽检与季度演练以证明真实 RPO/RTO 还原。**

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
/usr/local/libexec/vps-agent/control-plane-disaster-recovery.sh monthly-check <encrypted-package> <identity-file>
```

该命令不仅检查文件存在，还实际执行 age 解密、tar 全成员验证，并在 `0700` 临时根内工作；无论成功或异常均清理明文。季度应轮换使用两把 identity，以证明 1-of-2 可用性。

季度完整演练使用 `control-plane-drill.sh`，输入明确的数据库包、配置包、秘密包、离线 identity、独立实例 ID/凭据的隔离 env 和审计目录。源实例 ID 必须由 root-owned 策略独立提供，不能从待校验 manifest 回填。脚本只接受 `vps-agent-drill-*` 项目，使用 internal-only Compose 网络，强制清空通知、GitHub、外部 Provider、M4 签名、Principal/Caddy 写凭据和 Agent 操作密钥，不启动 Caddy、不包含 Agent；只保留演练专用 `ADMIN_API_TOKEN`。随后执行三类包解密、配置/秘密与当前可信策略源逐文件大小及 SHA-256 复核、数据库 24 小时 RPO 门、空 PostgreSQL 恢复、schema/关键数据检查、API/Web 启动、`/healthz` 和受保护 system-info。机器可读摘要分别记录三类包龄、数据库 `86400` 秒 RPO 门、配置/秘密变更驱动新鲜度与 `14400` 秒 RTO 门；数据库 RPO 或 RTO 未达标、配置/秘密与当前可信源不一致时命令失败，不输出会把三类语义混为一谈的总 `rpo_met`。

配置和秘密的承诺是“每次受控变更后立即备份”，不是按小时计算的 RPO。演练当前版本时必须与当前策略 allowlist 的源文件完全一致；若要演练历史配置包，必须先取得对应历史 checkout 和经授权的历史策略/源文件，不能拿当前 checkout 直接比较并宣称通过。

生产数据库、生产 Compose 项目、生产域名或真实 Agent 都不得作为演练目标。真实生产恢复仍是事故级单独授权。

## 生产激活记录（2026-08-16）

备份/复制链路已在生产主机激活，覆盖数据库包每日自动备份：

- 生产已安装 age v1.3.1、root-owned 策略与双 public recipient（0600）；副本根为本地盘 + 异地 SSHFS 挂载（备份 VPS）。
- 每日 systemd timer（`vps-agent-dr-database.timer`，daily + `RandomizedDelaySec=30m`）驱动 `run-database-backup`；沙箱实测 `ProtectSystem=strict` 下 pg_dump→age 加密→双副本全链 exit 0，`replicate` 返回 `warnings:[]`（两副本不同设备）。
- 异地挂载经 fstab + `x-systemd.automount` 持久化（`reconnect` + ServerAlive keepalive）。
- 配置与秘密包仍按变更显式执行，不依赖每日 timer。

激活期间处理的三个宿主机运维坑（非代码，供复跑参考）：

1. SSHFS 无 `reconnect` 会在空闲掉线后挂起不报错（卡在 `os.chmod`），需 `reconnect` + `ServerAliveInterval`/`ServerAliveCountMax`。
2. systemd 单元名里字面连字符必须转义 `\x2d`（如 `/mnt/vps-agent-backup-b` → `mnt-vps\x2dagent\x2dbackup\x2db.mount`），用 `systemd-escape --path` 计算，否则 `grep` 原名会漏掉转义单元。
3. fuse 经 `mount -t fuse.sshfs -o` 不能传 `user_id=0,group_id=0`（报 `fuse: unknown option`），root 挂载默认即 0，直接删除。

对应代码修复 `c2a6a80`：`run-database-backup` 从 policy 派生 ENV/COMPOSE 路径，不再硬编码 `/opt/vps-agent/current`。

## 当前外部阻断与授权边界

- 上述激活只覆盖“持续备份”，不覆盖“真实还原证明”：月度解密抽检与季度演练仍未执行，需管理员临时接入离线 identity（季度演练另需隔离 env），仍需单独授权。
- 设备 ID 不同只证明两副本在不同设备，不能单独证明物理异地；真实故障域仍需外部存储证据（备份 VPS 的物理位置/所有权）单独确认。
- 未经单独授权，仍不得执行季度演练、生产恢复，或把私钥放入生产/备份主机；本地/CI 证明不能替代生产 RPO 新鲜度或季度 RTO 证据。
