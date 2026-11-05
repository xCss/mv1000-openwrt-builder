# GL-MV1000 旁路由：OpenWrt 通用固件（默认 honk）

本仓库默认从 OpenWrt 25.12.6 源码构建 **honk / sing-box 共用固件**：内核同时提供 honk 所需的 BPF/BTF/cgroup 能力，以及 sing-box 的 TUN、inet-diag、nftables TPROXY/socket 模块。预装 honk、LuCI、Vantage 及简体中文翻译，sing-box 程序按需安装；两套程序使用同一内核，切换时调整服务和 DNS 即可。

XDR5480 负责拨号和 DHCP，MV1000 作为单臂旁路由。honk 是默认代理路线，sing-box 是备用选择，见 [同一固件安装与切换](docs/proxy-switching.md)。另保留官方内核的 Image Builder 路线供 sing-box/OpenClash 使用，见 [备用固件说明](docs/alternative-firmware.md)。

honk 上游仍处于 beta 阶段。此前的 honk 镜像已实机验证刷机、真实 eBPF、国内直连和海外代理；新加入的 sing-box 共用依赖由 CI 检查，运行表现仍需刷入新镜像后验证。**早期 honk 镜像未包含 TUN 模块，不能仅安装 sing-box 就恢复 TUN 接管。**

## 1. 地址与接线

| 设备 | 地址 | 职责 |
| --- | --- | --- |
| XDR5480 | `192.168.1.4` | 拨号、DHCP、MV1000 的上游网关和 DNS |
| GL-MV1000 | `192.168.1.2` | 静态地址、旁路由代理；关闭 DHCP |
| 终端 | `192.168.1.100–254` | 启用旁路由时，网关和 DNS 指向 `.2` |

XDR 的 LAN 口接 MV1000 的 LAN 口（`lan0` 或 `lan1`），MV1000 的 WAN 口不接。MV1000 删除 WAN 接口，LAN 区启用 masquerade 和 MSS clamping。

## 2. 默认构建：honk.yml

在 GitHub Actions 中选择 **Build MV1000 universal firmware (honk default)**，点击 **Run workflow**。参数 `rootfs_mb` 默认 `256`，表示根文件系统大小，单位 MiB。

推送到 `main` 且修改以下任意路径时，也会自动构建通用固件：

- `honk/**`：内核配置、本地 honk 包、默认配置和启动脚本。
- `files/**`：两种固件路线共用的首次启动设置。
- `.github/workflows/honk.yml`：默认构建流程。

仅修改文档或 sing-box 相关文件不触发 honk 构建。三个 workflow 的职责如下：

| Workflow | 定位 | 触发方式 | 产物 |
| --- | --- | --- | --- |
| [honk.yml](.github/workflows/honk.yml) | 默认通用固件；自编内核 | 主线文件变更、手动 | MV1000 ext4 镜像、匹配的内核模块 APK、配置和日志 |
| [build.yml](.github/workflows/build.yml) | 备用固件；官方 Image Builder | 仅手动 | sing-box / OpenClash / 无代理镜像 |
| [singbox.yml](.github/workflows/singbox.yml) | 备用 sing-box 包 | 仅手动 | APK、arm64 二进制、校验文件 |

sing-box 包流程不再定时运行，也不再自动触发固件构建。三个 workflow 分别管理自己的缓存，互不调用。

### 镜像内容

- OpenWrt **25.12.6**，target `mvebu/cortexa53`，设备 profile `glinet_gl-mv1000`，内核 **6.12.112**。
- 内核启用 `BPF`、`CGROUP_BPF`、网络命名空间、`DEBUG_INFO_BTF`、ftrace 和所需的 nftables/NFQUEUE 模块。
- 预装 `kmod-tun`、`kmod-inet-diag`、`kmod-nft-nat`、`kmod-nft-fib`、`kmod-nft-tproxy`、`kmod-nft-socket` 及其依赖，支持后装 sing-box 的 TUN/auto_redirect 或手动配置 nftables TPROXY。模块安装本身不会开启流量接管。
- `honk-bin` 安装上游 **v0.1.0-beta.5** 的静态 aarch64 musl full 二进制；版本和 SHA256 固定在 [包定义](honk/honk-bin/Makefile)，本流程不编译 Rust。
- LuCI、包管理器、Vantage 主题与应用、简体中文翻译；默认界面语言为简体中文。
- Vantage 从上游 feed 编译，当前 feed 提交未固定；版本由构建时的 feed 决定。
- 预装 `v2ray-geoip`、`v2ray-geosite`、分区和 ext4 工具。
- `99-bypass-router` 设置 `.2` 静态地址、网关/DNS `.4`、关闭 DHCP/DHCPv6/RA，时区为 `Asia/Shanghai`。
- `99-data-partition` 在首次启动时使用 eMMC 尾部空闲空间创建 p3，挂载到 `/mnt/data`；脚本保留启动依赖的 MBR 磁盘签名。
- `/etc/mv1000-build-info` 标识固件类型、源码提交和构建运行 ID，用于寻找同次构建的镜像与模块包。

### 构建校验与缓存

`make defconfig` 后先验证设备 profile、中文语言选择和关键内核选项。主机工具与工具链编好后立即保存缓存，再编译内核、软件包和镜像；后面的镜像失败不会丢失已保存的工具链缓存。

发布镜像前检查最终内核配置、`vmlinux` 的 `.BTF` 段、honk 文件、TUN/inet-diag/TPROXY/socket 模块与 APK 文件清单、TUN 开机加载项、Vantage 目录和五个中文翻译文件。配置和构建日志另存为 `honk-build-config-<run_id>` artifact。

每次构建另上传 `mv1000-kernel-packages-<run_id>`，包含同次编译的 kernel/kmod APK、内核 ABI 标识和 SHA256。自编内核的模块不能与官方内核模块混用；即使 `uname -r` 相同，也须核对 ABI。这些包也不能直接补给先前 ABI 不同的 honk 镜像。

此前冷构建实测 **77 分 05 秒**；[前缀缓存命中构建](https://github.com/xCss/mv1000-openwrt-builder/actions/runs/41988345441)为 **42 分 01 秒**，其中工具链准备 15 分 12 秒、镜像 Build 20 分 22 秒。具体随 runner 和网络变化，该样本早于本次模块补充。缓存包含主机工具、交叉工具链、下载目录与准备阶段的 ccache；内核构建目录没有跨运行保存。

## 3. 分区与刷机

默认镜像包含两个 ext4 文件系统：

| 分区 | 文件系统大小 | 内容 |
| --- | --- | --- |
| p1 启动分区 | 32 MiB | Linux `Image`、设备树、`boot.scr` |
| p2 根分区 | `rootfs_mb`，默认 256 MiB | OpenWrt、honk、LuCI、配置 |
| p3 数据分区 | 首次启动使用剩余空间创建 | `/mnt/data` |

`rootfs_mb` 不包含启动分区。默认解压后的镜像实测为 **290.125 MiB**，包含分区对齐和填充；根分区可用容量会小于标称值。保持默认 `256` 适合已验证的 U-Boot 恢复流程，更大的镜像需自行验证上传限制。

本镜像的根分区直接可写，没有 squashfs overlay，也没有传统 `firstboot` 恢复出厂方式。刷机前先将配置和运行状态备份到另一台电脑；固件不包含个人节点、订阅、面板账户或后续设备上的配置修改。

1. 从成功运行的 `openwrt-25.12.6-mv1000-honk` artifact 下载 `*glinet_gl-mv1000-ext4-sdcard.img.gz`、`sha256sums`、软件包 manifest 和 `mv1000-build-info`，核对压缩包 SHA256。artifact 名保留 `honk` 以兼容原下载入口；它现在承载通用固件。
2. 用 7-Zip 等工具解压得到 **`.img`**。OpenWrt 在 gzip 数据后追加固件元数据，部分解压工具会提示尾部存在附加数据。
3. 电脑有线网卡设为 `192.168.1.3/24`，接 MV1000 的 LAN 口。使用 `.3` 可以避开新固件的 `.2` 地址。
4. 按住 Reset 上电，等待恢复模式就绪；访问 `http://192.168.1.1`，上传 `.img`，保持供电和网线，等待自动重启。
5. 重启后访问 `http://192.168.1.2`。独立接线时电脑保留 `.3`；接回 XDR 网络后可改回 DHCP。
6. 新固件默认 SSH 为 `ssh root@192.168.1.2`，端口 `22`；首次登录设置密码或密钥。已运行设备上的自定义 SSH 端口不属于镜像默认值。
7. 检查 `ubus call system board`、`ls -l /sys/kernel/btf/vmlinux` 和 `df -h / /mnt/data`。
8. 检查 `cat /etc/mv1000-build-info`、`ls -l /dev/net/tun`，并用 `apk info -e kmod-tun kmod-inet-diag kmod-nft-tproxy kmod-nft-socket` 确认共用模块。

固件不会自动写入设备。需要回原厂时，从 [GL 下载站](https://dl.gl-inet.com/router/mv1000/) 获取对应镜像，再走 U-Boot 恢复。

## 4. honk 首次配置

**新镜像中的 honk 默认关闭**，默认路由为直连。先在 `/etc/honk/config.dae` 添加节点、分组和分流，再启动服务：

```sh
/etc/init.d/honk start
logread -e honk
# 验证节点、DNS 和终端转发后再开启自启
/etc/init.d/honk enable
```

内置原生面板配置为 `http://192.168.1.2:9527/ui/`，首次访问创建管理员账户。Clash API 默认只监听 `127.0.0.1:9090`。图形面板里的“导入、修订历史”需要数据库配置模式；beta.5 的数据库模式不能同时启用 Clash API。

### 已验证的旁路由设置

以下是实机部署经验，需要按使用场景配置，**不是默认镜像已完成的个人配置**：

- `lan_interface: br-lan`，`wan_interface: auto`，用于 LAN 转发与路由器本机流量。
- 单臂旁路由关闭 `net.ipv4.conf.all.send_redirects`、`net.ipv4.conf.br-lan.send_redirects`，并确保 `net.ipv4.conf.all.rp_filter=0`。可写入 `/etc/sysctl.d/60-honk-single-arm.conf` 后用 `sysctl -p` 应用。
- 使用 MetaCubeX 完整地理库时，国内 DNS 和直连规则使用 `geosite:cn`。实测 `geolocation-cn` 不覆盖 B 站、QQ、淘宝，不能作为这些服务的完整国内列表。
- DNS 可由 dnsmasq 转发到 honk 的 `127.0.0.1:1053`；国内查询走 XDR `.4`，海外查询经代理走 DoH。XDR 自身 DNS 上游应保持运营商或独立上游，避免回指 `.2` 形成循环。
- `/usr/share/honk/*.dat` 可以使用包提供的链接；**不要在 `global.data_dir` 内创建指向系统地理库的软链接**，否则面板更新可能报 `replacement_failed`。更新器会在数据目录生成独立文件。
- 浏览器使用系统 DNS 才能遵循该 DNS 分流。Chrome 强制使用海外安全 DNS 会绕过 honk 的 DNS 选择，导致国内站点命中海外 CDN。
- `client_subnet: auto` 为可选的自动 ECS。当前 XDR/运营商上游测试中推断和报文添加正常，但未观察到提速，因此部署保持关闭。

默认配置不预置付费节点，也不保证所有 sing-box 参数都有 honk 对应项。beta.5 不支持 Hysteria2 `gecko` 混淆，迁移时需检查协议和传输参数。

## 5. 启用终端与排查

先用一台终端将网关和 DNS 指向 `.2`，测试国内直连和海外代理。验证通过后，在 XDR 的 DHCP 设置中下发网关 `192.168.1.2`、首选 DNS `192.168.1.2`，避免同时提供会绕过策略的备用 DNS，终端重新获取租约。当前方案未配置全网 IPv6 代理时，关闭 XDR 的 IPv6 下发。

```sh
# MV1000 上
ubus call system board
ls -l /sys/kernel/btf/vmlinux
/etc/init.d/honk running
logread -e honk
df -h / /mnt/data

# 终端上
nslookup www.baidu.com 192.168.1.2
nslookup www.google.com 192.168.1.2
curl https://www.gstatic.com/generate_204
```

| 现象 | 检查方向 |
| --- | --- |
| 国内站点变慢 | 国内 DNS/流量是否同时匹配 `geosite:cn`；浏览器是否启用海外 DoH；实际 CDN 地址是否在国内 |
| honk 运行但终端无代理 | 终端网关/DNS、接口绑定、单臂旁路由 redirect/rp_filter 设置 |
| 地理数据更新报 `replacement_failed` | 数据目录中是否有 `.dat` 软链接或文件冲突；查看更新操作和 syslog |
| UDP 跟踪不可用 | 当前实机存在可选 UDP 接收追踪降级；诊断证据可能不完整，需按业务测试 UDP |
| 新镜像没有个人配置 | 从独立备份恢复节点、账户和运行状态；设备后续修改不会自动进入仓库 |
| 安装 sing-box 提示内核模块依赖冲突 | 确认使用新通用镜像；模块须来自同次构建并匹配 ABI，不能强制安装官方 kmod |

需要暂时绕过 MV1000 时，终端或 XDR DHCP 的网关/DNS改回主路由对应设置。

## 参考

- [honk 项目与文档](https://github.com/daeuniverse/honk)
- [OpenWrt GL-MV1000 设备页](https://openwrt.org/toh/gl.inet/gl-mv1000)
- [OpenWrt 25.12.6 mvebu/cortexa53 下载](https://downloads.openwrt.org/releases/25.12.6/targets/mvebu/cortexa53/)
- [GL U-Boot 恢复说明](https://docs.gl-inet.cn/router/3/features/uboot/)
- [Vantage 主题与应用](https://github.com/anothaDev/luci-theme-vantage)
- [同一固件安装和切换 honk / sing-box](docs/proxy-switching.md)
- [备用 sing-box / OpenClash 固件](docs/alternative-firmware.md)
