# Docker Desktop 启动故障：本机证据与安全处置顺序

检查日期：2026-09-29。仅诊断/建议，未执行清理、重装、重置或磁盘修复。

2026-09-30 更新：C 盘最新只读检查已约剩 12.2 GiB，下文 2.0 GiB 是此前读数；本轮未执行磁盘清理，空间改善不代表 `dockerInference` 启动故障已修复。项目 Web 镜像门已通过用户授权的 VPS 隔离测试完成，详见 [验证记录](./M7_3_IMAGE_GATE_2026-09-30.md)。

## 现场证据

- Docker Desktop `4.81.0.232925`；界面/CLI 的 `backend exited before becoming ready` 只是后台未就绪的汇总错误。
- 后台日志 `C:\Users\Admin\AppData\Local\Docker\log\host\com.docker.backend.exe.log` 在 2026-09-29 22:42（北京时间）明确报告：初始化 Inference manager 时，无法移除/访问 `C:\Users\Admin\AppData\Local\Docker\run\dockerInference`，错误为 `The file cannot be accessed by the system`，随后 backend crashed。
- 该端点是零字节 `Archive, ReparsePoint` 对象，修改时间为 2026-08-22。这支持异常/残留运行时端点的判断，但未确认其底层 reparse tag 或损坏原因。
- C 盘约 149.2 GiB，检查时仅剩 **2.0 GiB（约 1.35%）**。空间明显偏低，但本次明确错误不是磁盘已满，不能认定腾出空间就必然修复。
- Docker 数据盘实际存在于 `C:\Users\Admin\AppData\Local\Docker\wsl\disk\docker_data.vhdx`，文件逻辑大小 **22.03 GiB**；main 目录另有 `ext4.vhdx`。E 盘检查时约剩 **17.8 GiB**，不能假定足以完成完整普通文件备份，应先准备更大空间或外置盘。未复制、压缩、移动或删除这些文件。

相同端点启动失败在 [Docker 上游问题 #625](https://github.com/docker/desktop-feedback/issues/625) 有报告，目前看到的是问题描述而非已验证修复。不能把上游报告中对 VHDX 压缩的猜测视为本机根因，也不能声称某个新版本一定已修复。

## 建议顺序

1. **先恢复系统盘余量。** 建议至少准备 10–20 GiB 工作余量（工程建议，不是引用 Docker 官方最低要求），仅清理用户确认可删的文件/系统临时文件。不要为腾空间手工删除 Docker VHDX、数据目录或卷。腾空间后可在保存工作、退出 Docker 后重启 Windows，再验证；这只是排除空间与残留进程因素，不保证端点故障消失。
2. **涉及 Docker 修复前先备份。** 按 [Docker 官方不可启动时备份方法](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)，完全停止 Docker 后备份实际数据 VHDX；如需停止 WSL，应先保存其他发行版中的工作。备份目标需足够空间，不能直接占满当前 E 盘。备份完成并核验之前不做卸载/重置。
3. **再处理运行时端点故障。** 保留上述日志，先查询受支持更新/官方诊断建议；需要重装时按官方备份恢复流程进行。针对单一 `dockerInference` 对象的修复也应先确认对象类型和可恢复方案，不推荐直接执行未知 tag 的 reparse 删除、递归删 run 目录或手改文件系统元数据。不能保证更新/重装自动移除这个异常对象。
4. **仍失败则隔离问题。** 将有限、脱敏的诊断交给 Docker 支持，必要时在备份后用干净环境确认是否仅为旧用户运行时数据问题。上传诊断、卸载、重置、磁盘修复均需单独明确授权。项目最终镜像门可改在经授权的 GitHub Actions Linux runner 执行，不必占用生产 VPS 构建。

`Reset to factory defaults`、Clean/Purge、`wsl --unregister`、递归删除 Docker 目录和 `docker system prune --volumes` 都不是本轮建议直接执行的快捷修复；它们可能导致本地镜像、容器或持久化数据丢失。
