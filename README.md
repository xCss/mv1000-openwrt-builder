# GL-MV1000 旁路由（OpenWrt 25.12 + sing-box）构建与刷机

XDR5480 继续做拨号主路由，MV1000 只做旁路由代理。本仓库用 GitHub Actions + OpenWrt Image Builder 出包，把 LuCI、sing-box 和 Argon 主题直接打进镜像，刷完即可用。

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
| **sing-box（tiny）** | v1.14.4（CI 用 SDK 自编译） | ✅ `aarch64_cortex-a53` | 官方源：kmod-tun、kmod-inet-diag、ca-bundle | **推荐**。tiny 变体固定带 `gvisor/quic/utls/clash_api`，apk 约 11MB（mihomo-meta 是 20.6MB）；官方 feed 只到 1.13.21，CI 里升到上游最新版，顺带换掉旧 Go 标准库。没有 LuCI 应用，靠 JSON 配置 + Clash API 面板 |
| OpenClash | v0.48.002 | ✅ `luci-app-openclash-0.48.002.apk` | dnsmasq-full、bash、ruby、ruby-yaml、kmod-tun、unzip、ip-full | 功能最全但重；内核默认首次启动才从 GitHub 下载（国内常失败）；会替换 dnsmasq 为 dnsmasq-full |
| PassWall | 26.10.29-1 | ✅ 提供 apk | 还需要 chinadns-ng、dns2socks、microsocks、tcping、lyaml、luci-compat 等，来自其自有 feed | 非 Clash 方案；出包要多挂一个 feed，折腾成本高 |

主题固定打包 [luci-theme-argon](https://github.com/jerrykuku/luci-theme-argon) v3.1.2 的官方 apk（PIN 了 SHA256），其自带的 uci-defaults 会把 LuCI 默认主题切成 Argon。

sing-box tiny 的缺口：**没有 `with_wireguard` / `with_dhcp` / `with_acme` / `with_tailscale`**。节点里有 WireGuard 出站就会报 `unknown outbound type`，需要时在 `net/sing-box/Makefile` 的 tiny 分支补 tag 后重建。

MV1000 是双核 A53 1GHz / 1GB RAM，代理吞吐大约 100–300 Mbps（协议不同差异大），别指望跑满千兆；直连（走绕过规则）可以接近千兆。

## 3. GitHub Actions 出包

### 3.1 仓库准备

把本目录推到自己的 GitHub 仓库（公开/私有均可），默认分支 `main`。Actions 里运行 **Build MV1000 firmware**：

- `plugin`：`singbox`（默认）/ `openclash` / `none`
- `rootfs_mb`：默认 `256`。这个值直接决定 ext4 根分区和整包 raw 大小；U-Boot 网页上传实测 274MB 可以、530MB 会失败，所以别超过 320。剩余 eMMC 空间由首次启动脚本自动建成 `/mnt/data` 数据分区。

产物：`openwrt-25.12.6-mvebu-cortexa53-glinet_gl-mv1000-mv1000-<plugin>-ext4-sdcard.img.gz`。打 tag 推送时会自动发 Release。

### 3.2 镜像里做了什么

- 基于 `openwrt-imagebuilder-25.12.6-mvebu-cortexa53`，profile `glinet_gl-mv1000`（内核 6.12.112）。
- 内置 `luci` + 中文语言包 + 包管理器；`sing-box-tiny` 1.14.4 由 CI 下载 OpenWrt SDK 现场编译成 apk 再装进镜像。feed 里的版本是 1.13.21，CI 会改 `PKG_VERSION/PKG_HASH` 升到上游最新版；tiny 固定 tag 为 `with_gvisor,with_quic,with_utls,with_clash_api,badlinkname,tfogo_checklinkname0`。
- 内置 `luci-theme-argon` 3.1.2（官方 release apk，构建时校验 SHA256）；包自带的 `/etc/uci-defaults/30_luci-theme-argon` 首次启动把默认主题设为 Argon。
- `files/etc/uci-defaults/99-bypass-router` 首次启动写入：LAN 静态 `192.168.1.2`、网关/DNS 指向 `.4`、关闭 DHCP/DHCPv6/RA、删除 WAN、LAN 区开启 masquerade + MSS clamping、时区 `Asia/Shanghai`。
- `files/etc/uci-defaults/99-data-partition` 首次启动检查 eMMC 尾部空闲空间（≥512MB 时），自动建 p3、格式化成 ext4（label `data`）、挂载到 `/mnt/data` 并写入 fstab；后续开机由 `block-mount` 自动挂载。首次启动会多花几十秒格式化。注意：`parted` 会重写 MBR 磁盘签名，而内核命令行的 `root=PARTUUID=...` 依赖它，脚本会在建分区后把备份的签名写回，否则下次启动会因找不到根分区而 panic。
- 本地编译的 sing-box apk 和 Argon 的 release apk 都没有构建环境认可的签名，所以构建时关闭了 Image Builder 的签名校验；官方包仍从 `downloads.openwrt.org` 走 HTTPS 拉取，Argon 额外用 PIN 的 SHA256 校验。
- 用的是 **ext4** 系统镜像：根分区直接可写，没有 overlay；根分区在构建时按 `rootfs_mb` 固定，运行时不做在线扩容（builder 用 `make_ext4fs` 生成的 ext4 不支持加组），eMMC 剩余空间由首启脚本建成 `/mnt/data`。代价是没有 `firstboot` 恢复出厂，重装只能 U-Boot 重刷或提前导出配置。
- 选 `openclash` 时会预置 `mihomo` 内核到 `/etc/openclash/core/clash_meta`，避免首启时联网下载。

### 3.3 为什么不全量编译

整棵 OpenWrt 源码编译需要 20–30 GB 磁盘和数小时，托管 Runner 撑不住。固件仍然用 Image Builder 出（3–5 分钟），只有 feed 版本落后的 sing-box 用 SDK 单独编译一个包（约 10 分钟），其余全部用官方预编译包。只有确实要改内核/驱动时才值得上自建 Runner 做全量编译。

## 4. 刷机（U-Boot 网页恢复）

> 刷机会清空 MV1000 原有系统；GL 原厂固件可从 <https://dl.gl-inet.com/router/mv1000/> 重新刷回。

1. 下载 artifact，**解压成 `.img`**（Windows 用 7-Zip，或 `tar -xzf xxx.img.gz`）。不要上传 `.gz`，也不要上传 `initramfs-kernel.bin`。
2. 电脑网卡设静态 `192.168.1.2 / 255.255.255.0`，用网线接 MV1000 的 **LAN 口**，WAN 口不接，先断开其他 `192.168.1.x` 网络。
3. 按住 Reset（↻）不放，插 USB 电源；等 Power 与 WAN 灯常亮后松开。
4. 浏览器打开 `http://192.168.1.1`（不要 https），选 `.img` 上传。页面会卡住是正常的，等 3–10 分钟（256 MB 镜像约 5 分钟），设备自动重启。
5. 电脑网卡改回自动获取，访问 `http://192.168.1.2`，SSH `root@192.168.1.2`（无密码，先 `passwd` 设密码）。
6. 确认 `df -h /` 显示根分区约等于 `rootfs_mb`，`df -h /mnt/data` 显示 eMMC 剩余空间（约 6GB）。

如果上传到固定大小就中断：说明该 U-Boot 对大文件有限制，用 `rootfs_mb=256` 重新出包再刷。

## 5. XDR5480 设置

在「路由设置 → DHCP 服务器」：

1. 带机量选「普通」，DHCP 服务器选 **开**（不要「自动」，否则不能自定义网关）。
2. 地址池改为 `192.168.1.100` – `192.168.1.254`，把 `.2` 和 `.4` 让出来。
3. 网关填 `192.168.1.2`；首选 DNS 填 `192.168.1.2`；备用 DNS 留 `0.0.0.0`。
4. 地址租期先改成 `2` 分钟，等终端续租生效后再改回 `120`（或原来的 2880）。
5. 关闭 IPv6（否则终端走 IPv6 会绕过旁路由）。

切换前先用一台电脑手动设静态 IP `192.168.1.103`、网关/DNS `192.168.1.2` 验证代理可用，再改全局 DHCP。

## 6. sing-box 配置

没有 LuCI 应用，全部走 SSH + JSON 配置：

1. 编辑 `/etc/sing-box/config.json`（OpenWrt 包的默认路径），按 sing-box 官方文档写 inbounds / outbounds / route。旁路由典型做法：`tun` 入站 + `auto_route`，或 `mixed` 入站配合防火墙重定向。
2. `/etc/config/sing-box` 里 `option enabled '1'`；用 TUN 时把 `option user` 改成 `root`（默认 `sing-box` 用户没有创建 TUN 的权限）。
3. `/etc/init.d/sing-box enable && /etc/init.d/sing-box start`，`logread -f | grep sing-box` 看启动日志。
4. 需要网页面板时，在配置里开 `experimental.clash_api`：`external_controller` 设 `0.0.0.0:9090`（务必同时设 `secret`），`external_ui` 指向一个空目录（如 `/etc/sing-box/ui`）。目录为空时 sing-box 会按 `external_ui_download_url` 下载面板 ZIP，默认是 GitHub 上的 Yacd；国内拉不动就把 URL 换成镜像地址。面板只在目录为空时下载一次，不会自动更新。
5. 改完配置用 `/etc/init.d/sing-box restart` 生效；升级订阅就是替换 config.json 再 restart。

> 路由器自身流量是否走代理由 route 规则决定；旁路由场景一般把 `br-lan` 的转发流量导入 tun，本机流量直连，避免回环。

## 7. 验证与排错

```sh
# 旁路由上
pgrep -af 'sing-box run'             # 进程是否在跑
logread | grep -i sing-box           # 启动日志
ip link show tun0                    # TUN 是否建起来
curl -s -H "Authorization: Bearer <secret>" http://127.0.0.1:9090/proxies | head

# 终端上（网关/DNS 都应是 192.168.1.2）
curl -s https://api.ipify.org         # 应显示代理出口 IP
nslookup google.com 192.168.1.2
```

常见问题：

- **终端没网、旁路由正常**：检查 XDR 的网关/DNS 是否真的下发成 `.2`（终端 `ipconfig /all` 看租约），必要时重启终端网卡。
- **部分 App 仍显示国内 IP**：浏览器 DoH/DoT、或应用自带 DNS 会绕过劫持；在 App 内关掉安全 DNS。
- **IPv6 泄漏**：XDR 的 IPv6 必须关闭，或确认 sing-box 的 DNS/route 规则覆盖了 IPv6。
- **sing-box 启动失败**：先 `sing-box check -c /etc/sing-box/config.json` 校验配置；常见是用了 tiny 未编译的出站类型（WireGuard/DHCP/ACME/Tailscale），或 TUN 模式下 `user` 没改成 `root`。
- **端口 53 被 dnsmasq 占用**：用 TUN + `auto_route` 时无需自己监听 53；若配置了 DNS 入站，先在「DHCP/DNS」里关闭 dnsmasq 的 DNS 服务。

## 8. 回滚

- 想回 GL 原厂：从 GL 下载站取 MV1000 的 `.img`，用同样的 U-Boot 流程刷回。
- 想临时恢复上网：XDR 的 DHCP 网关改回 `0.0.0.0`（自动）或 `192.168.1.4`，DNS 改回自动。
- 旁路由刷坏：U-Boot 恢复不依赖系统，随时可以重刷。

## 参考

- OpenWrt 设备页：<https://openwrt.org/toh/gl.inet/gl-mv1000>
- 25.12.6 固件 / Image Builder / SDK：<https://downloads.openwrt.org/releases/25.12.6/targets/mvebu/cortexa53/>
- Image Builder 文档：<https://openwrt.org/docs/guide-user/additional-software/imagebuilder>
- GL U-Boot 恢复：<https://docs.gl-inet.cn/router/3/features/uboot/>
- sing-box：<https://github.com/SagerNet/sing-box>
- sing-box OpenWrt 包定义：<https://github.com/openwrt/packages/blob/openwrt-25.12/net/sing-box/Makefile>
- luci-theme-argon：<https://github.com/jerrykuku/luci-theme-argon>
- OpenClash：<https://github.com/vernesong/OpenClash>
- PassWall：<https://github.com/Openwrt-Passwall/openwrt-passwall>
