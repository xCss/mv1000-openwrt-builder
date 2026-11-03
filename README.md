# GL-MV1000 旁路由（OpenWrt 25.12 + Nikki）构建与刷机

XDR5480 继续做拨号主路由，MV1000 只做旁路由代理。本仓库用 GitHub Actions + OpenWrt Image Builder 出包，把 LuCI 和代理插件直接打进镜像，刷完即可用。

## 1. 地址规划

| 设备 | 地址 | 角色 |
| --- | --- | --- |
| XDR5480 | `192.168.1.4` | 拨号、DHCP 服务器、默认网关 |
| GL-MV1000 | `192.168.1.2`（静态） | 旁路由，只跑代理 |
| 终端 | `192.168.1.100–254`（DHCP） | 网关/DNS 指向 `.2` |

接线：XDR5480 的 LAN 口 → MV1000 的 LAN 口（lan0 或 lan1 都可以）。MV1000 的 WAN 口不接（刷机时也必须不接）。MV1000 关闭 DHCP、删除 WAN 接口，避免和主路由冲突。

## 2. 插件选型（2026-11 核实）

| 方案 | 版本 | 25.12 apk | 依赖 | 适用性 |
| --- | --- | --- | --- | --- |
| **Nikki** | v1.26.2（mihomo-meta 1.19.32 随包） | ✅ `aarch64_cortex-a53` | 全部在官方源：firewall4、curl、yq、ip-full、kmod-tun、kmod-dummy、kmod-nft-socket、kmod-nft-tproxy、kmod-inet-diag | **推荐**。包内含 mihomo 内核，不联网下载内核；内存占用小；原生 nftables，适配 fw4 |
| OpenClash | v0.48.002 | ✅ `luci-app-openclash-0.48.002.apk` | dnsmasq-full、bash、ruby、ruby-yaml、kmod-tun、unzip、ip-full | 功能最全但重；内核默认首次启动才从 GitHub 下载（国内常失败）；会替换 dnsmasq 为 dnsmasq-full |
| PassWall | 26.10.29-1 | ✅ 提供 apk | 还需要 chinadns-ng、dns2socks、microsocks、tcping、lyaml、luci-compat 等，来自其自有 feed | 非 Clash 方案；出包要多挂一个 feed，折腾成本高 |

MV1000 是双核 A53 1GHz / 1GB RAM，代理吞吐大约 100–300 Mbps（协议不同差异大），别指望跑满千兆；直连（走绕过规则）可以接近千兆。

## 3. GitHub Actions 出包

### 3.1 仓库准备

把本目录推到自己的 GitHub 仓库（公开/私有均可），默认分支 `main`。Actions 里运行 **Build MV1000 firmware**：

- `plugin`：`nikki`（默认）/ `openclash` / `none`
- `rootfs_mb`：默认 `256`。镜像会按这个大小生成 ext4 根分区，省去刷机后手动扩容。**如果 U-Boot 上传大文件失败，可改 192 甚至 160 重跑；只有在确实需要更多空间时才用 512/1024。**

产物：`openwrt-25.12.6-mvebu-cortexa53-glinet_gl-mv1000-mv1000-<plugin>-ext4-sdcard.img.gz`。打 tag 推送时会自动发 Release。

### 3.2 镜像里做了什么

- 基于 `openwrt-imagebuilder-25.12.6-mvebu-cortexa53`，profile `glinet_gl-mv1000`（内核 6.12.112）。
- 内置 `luci` + 中文语言包 + 包管理器；Nikki 及其内核 `mihomo-meta` 直接打进 rootfs。
- `files/etc/uci-defaults/99-bypass-router` 首次启动写入：LAN 静态 `192.168.1.2`、网关/DNS 指向 `.4`、关闭 DHCP/DHCPv6/RA、删除 WAN、LAN 区开启 masquerade + MSS clamping、时区 `Asia/Shanghai`。
- 因为 Nikki 的 apk 未签名（其官方安装脚本也用 `--allow-untrusted`），构建时关闭了 Image Builder 的签名校验；官方包仍从 `downloads.openwrt.org` 走 HTTPS 拉取。
- 用的是 **ext4** 系统镜像：根分区直接可写，没有 overlay，刷完不用再手动扩容；代价是没有 `firstboot` 恢复出厂，重装只能 U-Boot 重刷或提前导出配置。
- 选 `openclash` 时会预置 `mihomo` 内核到 `/etc/openclash/core/clash_meta`，避免首启时联网下载。

### 3.3 为什么不用源码全量编译

整棵 OpenWrt 源码编译需要 20–30 GB 磁盘和数小时，托管 Runner 撑不住。Image Builder 3–5 分钟出同版本官方包，只有确实要改内核/驱动时才值得上自建 Runner 做全量编译。

## 4. 刷机（U-Boot 网页恢复）

> 刷机会清空 MV1000 原有系统；GL 原厂固件可从 <https://dl.gl-inet.com/router/mv1000/> 重新刷回。

1. 下载 artifact，**解压成 `.img`**（Windows 用 7-Zip，或 `tar -xzf xxx.img.gz`）。不要上传 `.gz`，也不要上传 `initramfs-kernel.bin`。
2. 电脑网卡设静态 `192.168.1.2 / 255.255.255.0`，用网线接 MV1000 的 **LAN 口**，WAN 口不接，先断开其他 `192.168.1.x` 网络。
3. 按住 Reset（↻）不放，插 USB 电源；等 Power 与 WAN 灯常亮后松开。
4. 浏览器打开 `http://192.168.1.1`（不要 https），选 `.img` 上传。页面会卡住是正常的，等 3–10 分钟（256 MB 镜像约 5 分钟），设备自动重启。
5. 电脑网卡改回自动获取，访问 `http://192.168.1.2`，SSH `root@192.168.1.2`（无密码，先 `passwd` 设密码）。
6. 确认 `df -h /` 显示根分区约等于 `rootfs_mb`。

如果上传到固定大小就中断：说明该 U-Boot 对大文件有限制，用 `rootfs_mb=256` 重新出包再刷。

## 5. XDR5480 设置

在「路由设置 → DHCP 服务器」：

1. 带机量选「普通」，DHCP 服务器选 **开**（不要「自动」，否则不能自定义网关）。
2. 地址池改为 `192.168.1.100` – `192.168.1.254`，把 `.2` 和 `.4` 让出来。
3. 网关填 `192.168.1.2`；首选 DNS 填 `192.168.1.2`；备用 DNS 留 `0.0.0.0`。
4. 地址租期先改成 `2` 分钟，等终端续租生效后再改回 `120`（或原来的 2880）。
5. 关闭 IPv6（否则终端走 IPv6 会绕过旁路由）。

切换前先用一台电脑手动设静态 IP `192.168.1.103`、网关/DNS `192.168.1.2` 验证代理可用，再改全局 DHCP。

## 6. Nikki 配置

1. 「网络 → Nikki → 配置文件 → 订阅」添加订阅链接，点「更新」，然后在「插件配置」里选中该配置文件并勾选「启用」。
2. 「代理配置」：启用；TCP 模式 `TPROXY`；UDP 模式 `TPROXY`；开启 IPv4 DNS 劫持；IPv6 代理关闭。
3. 「局域网代理」：启用，入站接口 `br-lan`；「访问控制」加一行全部留空的规则（匹配所有流量）。
4. 需要国内直连可开「绕过 → 绕过中国大陆 IP」，也可交给订阅自带的规则。
5. 「网络 → DHCP/DNS」里关闭 **DNS 重定向**，否则会和 Nikki 的 DNS 劫持打架。
6. 保存并应用，看日志确认 mihomo 启动、无 `Too many open files`。

> 路由器自身流量默认不代理，保持关闭即可，避免 mihomo 出站再被自己劫持。升级订阅后手动「重载」或「重启」。

## 7. 验证与排错

```sh
# 旁路由上
nft list ruleset | grep -i nikki      # 规则是否生成
ps | grep mihomo                      # 内核是否在跑
logread | tail -50

# 终端上（网关/DNS 都应是 192.168.1.2）
curl -s https://api.ipify.org         # 应显示代理出口 IP
nslookup google.com 192.168.1.2
```

常见问题：

- **终端没网、旁路由正常**：检查 XDR 的网关/DNS 是否真的下发成 `.2`（终端 `ipconfig /all` 看租约），必要时重启终端网卡。
- **部分 App 仍显示国内 IP**：浏览器 DoH/DoT、或应用自带 DNS 会绕过劫持；在 App 内关掉安全 DNS。
- **IPv6 泄漏**：XDR 的 IPv6 必须关闭，或确认 Nikki 的 IPv6 劫持已开。
- **Nikki 启动失败**：多半是订阅格式不含 `proxies`/`proxy-providers`，或本机时间不对（NTP 未同步）。

## 8. 回滚

- 想回 GL 原厂：从 GL 下载站取 MV1000 的 `.img`，用同样的 U-Boot 流程刷回。
- 想临时恢复上网：XDR 的 DHCP 网关改回 `0.0.0.0`（自动）或 `192.168.1.4`，DNS 改回自动。
- 旁路由刷坏：U-Boot 恢复不依赖系统，随时可以重刷。

## 参考

- OpenWrt 设备页：<https://openwrt.org/toh/gl.inet/gl-mv1000>
- 25.12.6 固件/Image Builder：<https://downloads.openwrt.org/releases/25.12.6/targets/mvebu/cortexa53/>
- Image Builder 文档：<https://openwrt.org/docs/guide-user/additional-software/imagebuilder>
- GL U-Boot 恢复：<https://docs.gl-inet.cn/router/3/features/uboot/>
- Nikki：<https://github.com/nikkinikki-org/OpenWrt-nikki>
- OpenClash：<https://github.com/vernesong/OpenClash>
- PassWall：<https://github.com/Openwrt-Passwall/openwrt-passwall>
