# GL-MV1000 OpenWrt 通用固件

面向 GL-MV1000 单臂旁路由，**默认使用 honk，支持后装 sing-box 并在同一固件内切换**。

基于 OpenWrt **25.12.6**，预装 honk **v0.1.0-beta.5**、LuCI、Vantage 和简体中文。自编内核包含 BPF/BTF、TUN、inet-diag、nftables TPROXY 等两套程序所需的能力。

## 构建与下载

在 [GitHub Actions](https://github.com/xCss/mv1000-openwrt-builder/actions/workflows/honk.yml) 选择 **Build MV1000 universal firmware (honk default)** → **Run workflow**。`rootfs_mb` 默认 `256` MiB，建议保持默认。

| Workflow | 用途 | 触发方式 |
| --- | --- | --- |
| [honk.yml](.github/workflows/honk.yml) | 默认通用固件，预装 honk | 手动；`main` 上 `files/**`、`honk/**` 或本 workflow 变更 |
| [singbox.yml](.github/workflows/singbox.yml) | 按需构建 sing-box APK | 仅手动 |
| [build.yml](.github/workflows/build.yml) | 备用官方内核固件，选择 sing-box / OpenClash / 无代理 | 仅手动 |

成功构建后，在 **Artifacts** 下载 `openwrt-25.12.6-mv1000-honk`，内含镜像、SHA256、包清单和构建信息。配置日志与同次编译的内核模块包另存为 `honk-build-config-<run_id>`、`mv1000-kernel-packages-<run_id>`。

## 接线与地址

以下以常见的 `192.168.1.0/24` 网段为例，实际使用时按你的网络调整，并为旁路由预留未占用的地址。

| 设备 | 地址 | 职责 |
| --- | --- | --- |
| 主路由 | `192.168.1.1` | 拨号、DHCP、MV1000 的上游网关和 DNS |
| MV1000 | `192.168.1.2` | 旁路由，关闭 DHCP |
| 终端 | 主路由分配 | 启用代理时，网关和 DNS 指向 `.2` |

主路由的 LAN 口接 MV1000 的 LAN 口，MV1000 的 WAN 口不接。首次启动会关闭 MV1000 的 DHCP，并将 eMMC 剩余空间挂载到 `/mnt/data`。镜像的网络默认值见 [首次启动脚本](files/etc/uci-defaults/99-bypass-router)，刷机后需按实际网络调整网关和 DNS。

## 刷机

**先把配置和状态备份到电脑。**镜像不含个人节点、订阅和账户；根分区为可写 ext4，不提供传统 `firstboot` 恢复出厂功能。

1. 下载 `*glinet_gl-mv1000-ext4-sdcard.img.gz`，按 `sha256sums` 校验后解压为 **`.img`**。部分解压工具会提示 gzip 尾部附有 OpenWrt 元数据。
2. 断开 MV1000 与主路由的连接，电脑有线网卡设为 `192.168.1.3/24`，直连 MV1000 的 LAN 口，避免恢复地址与主路由冲突。
3. 按住 Reset 上电进入 [U-Boot 恢复模式](https://docs.gl-inet.cn/router/3/features/uboot/)，访问 `http://192.168.1.1`，上传 `.img` 并等待重启。
4. 重启后访问 `http://192.168.1.2`；SSH 默认端口 `22`，首次登录设置密码或密钥。
5. 在 LuCI 的 **网络 → 接口 → LAN** 中，将 IPv4 网关和自定义 DNS 改为主路由实际地址（本例 `192.168.1.1`），保存应用后接回主路由，电脑改回 DHCP。若网段不同，LAN 地址也需一并调整。

检查设备、数据分区和通用固件标识：

```sh
ubus call system board
df -h / /mnt/data
cat /etc/mv1000-build-info
ls -l /sys/kernel/btf/vmlinux /dev/net/tun
```

## 启用 honk

**honk 默认关闭，初始规则为直连。**先在 `/etc/honk/config.dae` 配置节点、DNS 和分流，再启动：

```sh
/etc/init.d/honk start
logread -e honk
# 验证终端代理和 DNS 后开启自启
/etc/init.d/honk enable
```

面板地址：`http://192.168.1.2:9527/ui/`，首次访问创建管理员。Clash API 默认监听 `127.0.0.1:9090`。honk 仍处于 beta 阶段，节点参数以 [上游文档](https://github.com/daeuniverse/honk) 为准。

单臂旁路由还需应用以下设置；接口名应与 honk 的 `lan_interface` 一致：

```sh
cat > /etc/sysctl.d/60-honk-single-arm.conf <<'EOF'
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.br-lan.send_redirects = 0
net.ipv4.conf.all.rp_filter = 0
EOF
sysctl -p /etc/sysctl.d/60-honk-single-arm.conf
```

部署时注意：

- 使用 MetaCubeX 完整地理库时，国内 DNS 和直连规则用 `geosite:cn`；浏览器使用系统 DNS。
- 若配置 honk DNS 监听 `127.0.0.1:1053`，再将 dnsmasq 上游指向 `127.0.0.1#1053`；主路由 DNS 保持独立上游，避免循环。
- 地理库更新由 honk 管理，勿在其数据目录中创建 `.dat` 软链接。

先让一台终端的网关和 DNS 指向 `.2`，验证国内访问、海外代理与 DNS，再通过主路由 DHCP 下发给其他设备。当前方案未配置 IPv6 代理时，关闭主路由的 IPv6 下发。需要绕过旁路由时，将终端网关和 DNS 改回主路由（本例 `192.168.1.1`）。

## 更多操作

- [安装与切换 honk / sing-box](docs/proxy-switching.md)
- [备用固件与 sing-box 包构建](docs/alternative-firmware.md)
- [OpenWrt 设备说明](https://openwrt.org/toh/gl.inet/gl-mv1000) · [GL 原厂固件](https://dl.gl-inet.com/router/mv1000/)
