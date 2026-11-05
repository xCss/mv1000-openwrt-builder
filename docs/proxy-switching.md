# 在同一固件中使用 honk / sing-box

`honk.yml` 构建的通用固件预装 honk，并为 sing-box 准备匹配的内核模块。sing-box 程序按需安装。两套程序可以共存，每次只启用一套透明接管；切换服务和 DNS 后即可使用，无需为每次切换重新编译或刷机。

## 1. 确认使用通用固件

在 MV1000 上执行：

```sh
cat /etc/mv1000-build-info
apk info -e kmod-tun kmod-inet-diag kmod-nft-nat kmod-nft-fib kmod-nft-tproxy kmod-nft-socket
ls -l /dev/net/tun
```

`FIRMWARE_FLAVOR=honk-singbox` 表示通用固件。预装的模块覆盖 TUN、socket 诊断、nftables 自动重定向所需的 NAT/FIB，以及可手动配置的 TPROXY/socket 接管。模块安装不会自动创建 TUN 网卡或代理规则。

如果已安装 `kmod-tun` 但设备节点尚未出现，执行 `modprobe tun`，再检查 `/dev/net/tun`。仍失败则查看 `dmesg` 的模块加载错误。

**早期 honk 镜像没有预留这些模块。**这种设备需要先备份并升级到新通用镜像，或取得严格匹配旧内核 ABI 的模块。新构建的模块不能因版本号相同就补给旧内核；不要通过跳过依赖检查强行安装。

固件与 `mv1000-kernel-packages-<run_id>` artifact 都带 `mv1000-build-info`。模块 artifact 还包含 `kernel.vermagic`、kernel/kmod APK 和 `sha256sums`。补装模块前，用构建 ID 与 `apk info -a kernel` 中的 ABI 确认匹配；kernel APK 用作版本参照，不是在线替换运行内核的升级包。

## 2. 安装 sing-box 程序

在电脑的仓库目录运行以下 Bash 命令，从当前 pin 对应的 Release 下载并校验 APK：

```sh
version=$(sed -n 's/^SINGBOX_VERSION=//p' singbox.env)
expected=$(sed -n 's/^SINGBOX_APK_SHA256=//p' singbox.env)
test -n "$version" && test -n "$expected" || exit 1
download_dir=$(mktemp -d) || exit 1
gh release download "singbox-tiny-v${version}" --repo xCss/mv1000-openwrt-builder \
  --pattern 'sing-box-tiny-*.apk' --dir "$download_dir" || exit 1
apk=$(find "$download_dir" -maxdepth 1 -name 'sing-box-tiny-*.apk' -print)
test "$(printf '%s\n' "$apk" | wc -l)" -eq 1 && test -s "$apk" || exit 1
printf '%s  %s\n' "$expected" "$apk" | sha256sum -c - || exit 1
```

将校验通过的 APK 传到路由器 `/tmp`。例如，按设备实际 SSH 端口传输：

```sh
scp -O -P 22333 "$apk" root@192.168.1.2:/tmp/
```

新镜像的默认 SSH 端口是 `22`；`22333` 是已部署设备的示例。然后在路由器安装：

```sh
apk add --allow-untrusted /tmp/sing-box-tiny-*.apk || exit 1
sing-box version
# 先保持服务关闭，配置并验证后再切换
/etc/init.d/sing-box disable
uci set sing-box.main.enabled='0'
uci commit sing-box
```

`--allow-untrusted` 用于本仓库尚未加入系统信任链的 APK，前一步的 SHA256 校验仍须通过。它不代表可以忽略内核 ABI 或依赖错误。新通用固件已预装当前 sing-box-tiny 包声明的 `ca-bundle`、`kmod-tun`、`kmod-inet-diag` 和 libc 依赖，不需要另从官方源下载安装 kmod。

准备 `/etc/sing-box/config.json`，恢复节点、规则文件、缓存目录和面板设置。旧配置须先通过当前版本检查：

```sh
sing-box check -c /etc/sing-box/config.json || exit 1
uci set sing-box.main.user='root'
uci set sing-box.main.conffile='/etc/sing-box/config.json'
uci commit sing-box
```

TUN 模式需要 root。`auto_route` / `auto_redirect`、DNS 劫持和路由规则由 sing-box 配置控制。选择 TPROXY 入站时，还需自行配置 nftables 与策略路由，预装模块不会替你生成规则。

## 3. 从已运行的 honk 切到 sing-box

以下示例适用于当前单臂旁路由：XDR `192.168.1.4` 是独立上游 DNS，sing-box 使用 TUN `auto_route` / `auto_redirect` 并已配置 DNS 劫持。先检查 sing-box 配置，再备份当前 dnsmasq 设置：

```sh
sing-box check -c /etc/sing-box/config.json || exit 1
mkdir -p /root/proxy-switch
cp -p /etc/config/dhcp /root/proxy-switch/dhcp.honk

/etc/init.d/honk disable
/etc/init.d/honk stop
```

用 `pidof honk-core` 确认原进程已退出，等其清理 eBPF、NFQUEUE 和监听端口。若仍未退出或清理失败，先查看 `logread -e honk`，再继续。停止 honk 后，原先转发到 `127.0.0.1#1053` 的 dnsmasq 上游暂时不可用，因此要切换为独立上游：

```sh
uci set dhcp.@dnsmasq[0].noresolv='1'
uci -q delete dhcp.@dnsmasq[0].server
uci add_list dhcp.@dnsmasq[0].server='192.168.1.4'
uci commit dhcp
/etc/init.d/dnsmasq restart

uci set sing-box.main.enabled='1'
uci commit sing-box
/etc/init.d/sing-box start
logread -e sing-box
```

此时 dnsmasq 有一个可独立工作的上游，终端 DNS 再由 TUN 的规则按配置接管。若 sing-box 使用独立 DNS 监听端口，应把 dnsmasq 指向该监听地址，而非照抄 `.4`；避免指回已经停止的 honk 或形成循环。

在终端验证国内访问、海外代理、TCP/UDP DNS，以及 TUN/路由状态。确认正常后再执行 `/etc/init.d/sing-box enable`。如果启动或连通性失败，按下一节恢复 honk。

## 4. 切回 honk

先关闭 sing-box，并用 `pidof sing-box` 确认退出，等 TUN 和自动生成的规则清理。手工配置的 TPROXY 规则须按自己的部署记录撤销，不要清空整个防火墙：

```sh
/etc/init.d/sing-box disable
/etc/init.d/sing-box stop
uci set sing-box.main.enabled='0'
uci commit sing-box
```

恢复 honk 服务。确认其 DNS 监听已经就绪后，再恢复切换前保存的 dnsmasq 配置：

```sh
/etc/init.d/honk start
logread -e honk
# 等待 honk 报告运行及 DNS 监听就绪，再执行以下命令
test -s /root/proxy-switch/dhcp.honk || exit 1
cp -p /root/proxy-switch/dhcp.honk /etc/config/dhcp
/etc/init.d/dnsmasq restart
```

验证终端分流和 DNS 后执行 `/etc/init.d/honk enable`。切换备份只应恢复到对应的一次部署；若期间修改过 DHCP 配置，应合并 DNS 字段，避免覆盖其他设置。honk 重启会使面板会话失效，需要重新登录。

## 5. 更新与验证范围

- sing-box 程序可独立换版本，使用 [singbox.yml](../.github/workflows/singbox.yml) 生成 APK，不必为纯程序更新重新构建固件。
- 更新程序前备份配置和状态，执行配置检查，停止旧进程后安装并验证新版本。
- 内核及 kmod 更新仍须整体匹配；官方源中的同版本 kmod 未必适配本仓库的自编内核。
- CI 验证模块选项、镜像内模块文件和包清单；TUN/TPROXY、DNS 与代理吞吐须在设备上分别验证。本改动没有证明 sing-box 比 honk 更快。

若主动改刷官方内核镜像，可参照 [备用固件说明](alternative-firmware.md)。该路线与这里的同固件切换不同，不能直接装 honk 就补齐其内核能力。
