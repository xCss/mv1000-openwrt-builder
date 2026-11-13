# 内核与流量控制能力

这些配置用于 `.github/workflows/honk.yml` 的自编内核通用固件；备用 ImageBuilder 工作流不包含本次能力补齐。修改构建器不会改变正在运行的路由器，必须完成新固件构建、刷入与实机验证后才能确认生效。

## 提供的能力与默认状态

| 能力 | 构建内容 | 新刷入后的默认行为 |
| --- | --- | --- |
| honk UDP receive tracing | BPF_EVENTS、KPROBES、KPROBE_EVENTS、PERF_EVENTS、BTF 与 function/dynamic ftrace | 提供 FEntry/FExit 所需内核能力，由 honk 尝试加载和挂载 |
| NETKIT | `CONFIG_NETKIT=y` | 提供内核设备类型，由 honk 决定是否使用；保留 veth 回退 |
| BBR | `kmod-tcp-bbr` | 模块可用，TCP 默认仍为 cubic |
| fq | `kmod-sched` 中的 `sch_fq` | 提供调度器，不修改全局默认 qdisc，不替换接口队列 |
| CAKE、IFB | `kmod-sched-cake`、`kmod-ifb` 及 SQM 依赖 | 提供整形能力，不自动配置流量重定向 |
| SQM | `sqm-scripts`、`luci-app-sqm`、简体中文界面 | `bypass` 队列关闭，接口为空，上传/下载均为 0 |
| 诊断工具 | `ip-full`、`tc-full` | 完整工具作为 `/sbin/ip` 和 `/sbin/tc` 的实现 |
| 多核收包分流 | OpenWrt 自带 `packet_steering` 服务与首次启动检测脚本 | 多核且没有已有选项时设置 `network.@globals[0].packet_steering=2`，单核不启用 |

OpenWrt 的 `kmod-tcp-bbr` 包会安装 `/etc/sysctl.d/12-tcp-bbr.conf`，自动设置 BBR。本固件通过后加载的 `/etc/sysctl.d/90-mv1000-tcp.conf` 保留 cubic，避免安装模块就改变默认 TCP 行为。SQM 的服务入口可以存在，但关闭的队列不会执行整形；`/etc/init.d/sqm enabled` 只表示服务自启状态，不表示队列已经启用。

上述是新镜像的默认值。保留配置升级或恢复备份后，原有 `/etc/config/sqm`、`/etc/sysctl.conf` 等用户配置可能继续生效，应重新检查实际状态。

## 自动启用多核收包分流

`files/etc/uci-defaults/99-packet-steering` 随镜像打包，在设备首次启动时读取 `/proc/stat` 的在线 CPU 数量。检测的是路由器 CPU，不能使用 GitHub Actions 构建主机的 `nproc` 结果。多核且没有显式 packet steering 配置时，脚本创建所需的 globals 段、设置 `packet_steering=2` 并启用、重载系统自带服务。单核或缺少服务时跳过；已有值（包括 `0`）保持不变。

在本次 MV1000/OpenWrt 版本上，标准服务会把 eth0 的接收队列 RPS 位掩码设置为 `3`，允许 CPU0 和 CPU1 按流分配；其他平台由其标准服务或平台脚本决定具体分配。无需写死 CPU 数量、网卡 IRQ 编号或 honk 进程亲和性。后续网络、接口及防火墙事件由系统服务重新应用配置。

2026-11-13 的 MV1000 有线实测中，国内 8 并发约 55 秒下载由 165–168 Mbps 提升到 272–301 Mbps，上传约 53.55 Mbps。高负载下仍有丢弃计数及部分 ICMP 超时；这些结果不是千兆吞吐保证。将全部接收处理移到单个另一核心在 8/16 并发下出现明显软件队列丢包，因此采用标准多核选项。

检查实际配置与分配：

```sh
uci get 'network.@globals[0].packet_steering'
/etc/init.d/packet_steering enabled
for queue in /sys/class/net/eth0/queues/rx-*; do
    cat "$queue/rps_cpus"
done
```

首次启动成功后脚本由 OpenWrt 删除，之后用户修改不会被强制覆盖。保留配置升级时若已有选项则保留；若尚未配置且为多核，则使用新默认值。手动恢复旧备份可能覆盖该选项，应重新检查。此检测脚本也被备用 ImageBuilder 工作流打包。

## honk 的“未知”与内核降级

已审计的旧固件缺少 BPF_EVENTS、KPROBES 和 PERF_EVENTS。honk beta.5/beta.6 的 UDP receive tracing 使用 FEntry/FExit；Linux 6.12 的 BPF tracing 程序类型受 BPF_EVENTS 控制，仅启用 BTF 和 function tracer 不足以提供该能力。

OpenWrt 会在目标内核片段之后合并 `CONFIG_KERNEL_*` 选项，因此工作流与 `honk/kernel/mvebu-cortexa53.config-6.12` 必须同时配置依赖。构建检查覆盖 `make defconfig` 的结果和最终 Linux `.config`，避免片段写了 `y`、最终内核仍被关闭。

这次修复针对缺失的 tracing 能力。面板中的“未知”还需结合 DNS、规则命中和连接元数据判断，不能保证所有“未知”都因此消失。NETKIT 也只代表能力可用；是否成功采用、是否回退到 veth，以 honk 实机日志为准。

## 刷入后的验收

先确认当前启动的是新构建，且新建连接期间没有再次出现 tracing 加载失败。旧内核无法通过安装这些新 kmod 补齐 BPF_EVENTS/NETKIT；内核与模块必须来自同次构建，勿混用官方仓库的 kmod。

```sh
cat /etc/mv1000-build-info
uname -r
ls -l /sys/kernel/btf/vmlinux
logread -e honk
dmesg | grep -Ei 'bpf|netkit|trace|fail|error'
sysctl net.ipv4.tcp_available_congestion_control
sysctl net.ipv4.tcp_congestion_control
sysctl net.core.default_qdisc
readlink /sbin/ip
readlink /sbin/tc
uci show sqm
tc -s qdisc show
```

新镜像默认应看到可用算法包含 `bbr`、当前算法为 `cubic`；工具分别指向 `/usr/libexec/ip-full` 和 `/usr/libexec/tc-full`；`sqm.bypass.enabled='0'`、接口为空、速率为 0。未恢复配置时，不应有本固件主动添加的 CAKE 队列。仅凭 `dmesg` 没有报错或 BTF 文件存在，不能证明 honk 已成功挂载 FEntry/FExit；需结合 honk 日志和新建 UDP 流量验证。

可检查模块已打包；`lsmod` 只能显示当前已加载模块，不能代替文件和能力检查：

```sh
find /lib/modules -type f \( -name 'tcp_bbr.ko*' -o -name 'sch_fq.ko*' \
  -o -name 'sch_cake.ko*' -o -name 'ifb.ko*' \)
```

## BBR 的测试与回退

BBR 影响 MV1000 本机 Linux TCP 栈创建的连接，包括使用系统 TCP socket 的代理出站。它不会替终端的纯转发 TCP 连接改变拥塞控制，也不会直接替换 QUIC/Hysteria2 的用户态拥塞控制。

需要对比测试时，临时启用 BBR：

```sh
modprobe tcp_bbr
sysctl -w net.ipv4.tcp_congestion_control=bbr
sysctl net.ipv4.tcp_congestion_control
```

使用新建的代理 TCP 连接比较吞吐、延迟和重传，已有 socket 不一定随系统默认值切换。临时回退用 `sysctl -w net.ipv4.tcp_congestion_control=cubic`；重启也会恢复镜像默认值，除非已有其他持久配置覆盖。确认有效后，可将 `/etc/sysctl.d/90-mv1000-tcp.conf` 中的 `cubic` 改为 `bbr`，再用 `sysctl -p /etc/sysctl.d/90-mv1000-tcp.conf` 应用；检查最后加载的 `/etc/sysctl.conf` 是否另有覆盖。

此处不要求同时更换 `br-lan` 的 root qdisc。内核 6.12 在没有 fq 时有 TCP 内部 pacing 回退；fq 已打包，是否使用以及挂在哪个设备上，应在确认 honk 的实际出站路径后测试。

## XDR5480 与单臂 SQM

XDR5480 是主路由，MV1000 只有一条 LAN 上联；这个拓扑没有让 MV1000 的同一网口天然成为独立的 WAN 上下行边界。同一端口可能同时承载终端流量、发往主路由的流量和回程流量。不能把宽带上下行速率直接套在 `br-lan` 上，也不应在未核对 honk 的 tc/BPF 挂载前替换现有 ingress/clsact 规则。

启用 SQM 前应先确认客户端是否都经 MV1000、上下行实际经过的设备和方向、是否与 honk 的 tc/BPF 规则冲突，以及实际可持续带宽、负载下的 CPU 和延迟。若需要控制整个家庭 WAN 的排队，整形点应覆盖真正的 WAN 瓶颈；仅经过 MV1000 的流量才可能受其整形控制。主路由型号本身不能替代这些验证。

因此镜像预装 CAKE/IFB/SQM，默认不绑定接口、不设置限速、不自动添加整形规则。后续通过 LuCI 的网络 → SQM QoS 配置，需同时核对队列开关与 SQM 服务自启状态。上传/下载 0 表示对应方向不整形，不表示自动测量带宽。

## 构建验证

工作流依次检查：

1. `make defconfig` 后 tracing 顶层选项和新增软件包确实为 `y`。
2. 最终 Linux 配置中 tracing/NETKIT 为内建，BBR/fq/CAKE/IFB 及 ingress/mirred/u32 依赖为 `y` 或 `m`。
3. 镜像根目录中有包记录、模块、完整工具、SQM 脚本和中文资源；新镜像 SQM 配置与关闭模板一致，按加载顺序得到的默认 TCP 算法为 cubic。
4. 上传的同次编译 kmod 集合包含 BBR、调度器、CAKE 和 IFB。

这些静态检查不能替代 ARM64 实机的 BPF 挂载和转发测试。首次构建成功后仍需按上面的验收步骤检查日志和连接。

## 上游依据

- OpenWrt v25.12.6：`config/Config-kernel.in`、`package/kernel/linux/modules/netsupport.mk`、`package/kernel/linux/files/sysctl-tcp-bbr.conf`、`package/network/utils/iproute2/Makefile`、`package/base-files/files/etc/init.d/sysctl`。
- Linux v6.12：`include/linux/bpf_types.h` 的 BPF_EVENTS 条件；`drivers/net/Kconfig` 的 NETKIT 依赖。
- sqm-scripts `20ba92639546075d8e39346dcb88a3cdfe8ee903`：`platform/openwrt/sqm-uci`、`platform/openwrt/sqm-hotplug`、`src/run-openwrt.sh`。构建使用 OpenWrt feeds 指定的版本，本文记录核对时的来源版本。
