# MV1000 根分区自动扩容

## 布局

镜像保持约 32 MiB 启动分区 p1 + 256 MiB 初始 ext4 根分区 p2。完整刷入后，首次启动将 p2 扩展到实际 eMMC 末端的 1 MiB 边界，并在线扩展 ext4；8 GB 标称 eMMC 上根分区约 7.2 GiB，`df` 扣除元数据后约 7 GiB。p1、MBR 磁盘签名、p2 起始扇区和文件系统 UUID 都保持不变。

这不是 extroot，不创建 p3，不把其他文件系统覆盖到 `/`。正常使用 `rootfs_mb=256` 即可，扩容容量由设备实际扇区数决定。

## 启动流程

- `files/etc/uci-defaults/99-grow-rootfs` 调用 `/usr/libexec/mv1000-grow-rootfs`。
- 从 `/proc/self/mountinfo` 的设备号定位实际根分区，只接受 MV1000 的非可移除 eMMC、ext4、MBR、仅 p1/p2 的布局；不猜测 mmcblk0/mmcblk1。
- `/lib/mv1000-rootfs.sh` 保存原 MBR，使用 `sfdisk -N 2` 仅扩大 p2，回读验证引导字节、签名、p1 及分区边界。
- `partx -u --nr 2` 通知内核。若容量未刷新，通过启动末尾的 `S99mv1000-rootfs-reboot` 额外重启一次；下次继续，不反复重启。
- `resize2fs` 扩展根文件系统。成功后 UCI defaults 脚本按 OpenWrt 机制移除；失败时保留日志与重试入口。

状态、日志和原 MBR 保存于 `/etc/mv1000-rootfs/`。分区操作失败时仅在尚未扩大文件系统的阶段恢复原 MBR；文件系统已经扩大后绝不能恢复旧的小分区表。

## 为什么还要改构建过程

实际旧固件的 `make_ext4fs` resize inode 在在线扩容时触发 `reserve_backup_gdb: reserved block ... not at offset ...`，不能只在旧系统安装 resize2fs 后直接执行扩容。

`scripts/patch-image-build.py` 在 OpenWrt 的 ext4 生成步骤后加入 `scripts/prepare-rootfs-ext4.sh`：在构建主机对**未挂载的 root.ext4** 去除 `resize_inode`，运行 e2fsck 修正其保留块和位图，再校验干净。之后继续原有 sdcard/gzip/fwtool 元数据和校验和生成流程。首次启动脚本拒绝对未经此处理的 resize_inode 文件系统做在线扩容。

固件显式安装 `resize2fs`、`sfdisk`、`partx-utils`、`blkid`。`e2fsprogs` 本身不包含 resize2fs。

## 从旧 /mnt/data 布局刷入

先把配置、节点、状态及需要的 `/mnt/data` 文件备份到电脑，然后通过 U-Boot 恢复页刷入本次构建的完整 `.img`。新镜像仅含 p1/p2 的分区表，原 p3 区域会纳入新根文件系统，原数据不能作为保留内容依赖。

如果保留旧分区布局升级，p3 仍在，脚本会报告 `skipped-layout` 并保留它，绝不自动删除已有分区。挂载配置 `/etc/config/fstab` 也不会被脚本整体重写。

后续升级仍应使用带此扩容流程的固件。MV1000 的 legacy-sdcard 升级器可能因分区布局变化整盘写入镜像，备份流程与普通重刷相同；`sysupgrade` 的保留配置不等于保留整个扩大的根文件系统。刷入新镜像后重新扩容。

## 验证

```sh
df -h /
cat /etc/mv1000-rootfs/status
cat /etc/mv1000-rootfs/log
block info
```

预期为 `complete`、根文件系统约 7 GiB，且无独立 data 分区。`failed` 时查看日志，先确认原因再重试 `/usr/libexec/mv1000-grow-rootfs`。

CI 在一次性 loop 磁盘上测试：在线扩容、无 journal、已有 p3 保留、拒绝未处理的文件系统、分区失败恢复、重启续跑、防重启循环、resize2fs 失败重试、幂等性、文件内容/UUID/启动分区保持，以及卸载后的 e2fsck。编译后还将**实际生成的固件镜像**放入模拟 7.28 GiB eMMC 重复验证；该步骤通过才上传镜像。模拟测试不能替代 MV1000 的实际启动验证。
