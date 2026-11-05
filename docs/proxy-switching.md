# 安装与切换 honk / sing-box

通用固件预装 honk 和两套程序的内核依赖，sing-box 按需安装。**每次只运行一套透明接管**，切换时同时调整 DNS。

## 确认固件

```sh
cat /etc/mv1000-build-info
apk info -e kmod-tun kmod-inet-diag kmod-nft-tproxy kmod-nft-socket
ls -l /dev/net/tun
```

`FIRMWARE_FLAVOR=honk-singbox` 表示通用固件。若已安装 TUN 模块但没有设备节点，可执行 `modprobe tun`。早期 honk 镜像未包含这些模块，需要先[升级固件](../README.md#刷机)，或补装严格匹配内核 ABI 的模块。

补装 kmod 时，核对 `/etc/mv1000-build-info` 的构建 ID、`apk info -a kernel` 与同次构建模块包中的 `kernel.vermagic`。不要强制安装 ABI 不匹配的官方模块；模块包中的 kernel APK 也不能替代整机内核升级。

## 安装 sing-box

1. 查看 [singbox.env](../singbox.env) 的版本，从对应的 [Release](https://github.com/xCss/mv1000-openwrt-builder/releases) 下载 `sing-box-tiny-*.apk`。
2. 核对 APK 的 SHA256 与 `SINGBOX_APK_SHA256` 一致，将文件传到路由器 `/tmp`。
3. 在路由器执行以下命令。`--allow-untrusted` 用于本仓库未加入系统信任链的包，仍须完成哈希校验。

```sh
apk add --allow-untrusted /tmp/sing-box-tiny-*.apk || exit 1
sing-box version
/etc/init.d/sing-box disable
uci set sing-box.main.enabled='0'
uci set sing-box.main.user='root'
uci set sing-box.main.conffile='/etc/sing-box/config.json'
uci commit sing-box
```

准备 `/etc/sing-box/config.json` 及其引用的规则文件，再执行 `sing-box check -c /etc/sing-box/config.json`。TUN 使用 root，并配置 `auto_route`、`auto_redirect` 和 DNS 劫持。TPROXY 模式则需另外配置 nftables 和策略路由。

## 切到 sing-box

以下命令适用于本仓库的地址规划，并假定 sing-box 已配置好 TUN 和 DNS 劫持，XDR `.4` 是独立 DNS 上游。

```sh
sing-box check -c /etc/sing-box/config.json || exit 1
mkdir -p /root/proxy-switch
cp -p /etc/config/dhcp /root/proxy-switch/dhcp.honk
/etc/init.d/honk disable
/etc/init.d/honk stop
```

用 `pidof honk-core` 确认进程已退出，再切换 dnsmasq 上游并启动 sing-box：

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

若 sing-box 使用独立 DNS 监听端口，dnsmasq 应指向该监听地址。不要继续指向已停止的 honk，也不要形成 DNS 循环。终端的国内访问、海外代理与 DNS 验证通过后，执行 `/etc/init.d/sing-box enable`；失败则按下节回退。

## 切回 honk

```sh
/etc/init.d/sing-box disable
/etc/init.d/sing-box stop
uci set sing-box.main.enabled='0'
uci commit sing-box
```

用 `pidof sing-box` 确认退出；若曾手动添加 TPROXY 规则，按部署记录撤销。然后启动 honk：

```sh
/etc/init.d/honk start
logread -e honk
```

等待 honk 和 DNS 监听就绪，再恢复切换前的 dnsmasq 设置：

```sh
test -s /root/proxy-switch/dhcp.honk || exit 1
cp -p /root/proxy-switch/dhcp.honk /etc/config/dhcp
/etc/init.d/dnsmasq restart
```

若期间改过 DHCP 配置，应只合并 DNS 字段。验证访问和分流后，执行 `/etc/init.d/honk enable`。honk 重启后面板需重新登录。

## 更新程序

sing-box 可独立更新 APK，无需重编固件。先备份配置，停止服务，安装后检查配置并验证访问。需要新版本包时，参照[按需构建](alternative-firmware.md#构建-sing-box-包)。
