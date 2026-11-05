# 备用固件与软件包构建

日常使用推荐 [默认通用固件](../README.md)。已有通用固件时，使用 sing-box 参照[安装与切换](proxy-switching.md)；下面两条 workflow 均为手动运行。

## 构建官方内核固件

在 Actions 选择 **Optional: Build MV1000 sing-box/OpenClash firmware**（[build.yml](../.github/workflows/build.yml)）。

| 参数 | 可选值 | 默认 |
| --- | --- | --- |
| `plugin` | `singbox` / `openclash` / `none` | `singbox` |
| `rootfs_mb` | 根分区大小，单位 MiB | `256` |

```sh
gh workflow run build.yml --ref main -f plugin=singbox -f rootfs_mb=256
```

此路线用官方 Image Builder 和预编译内核组装镜像，预装 LuCI、中文 Vantage 及所选代理。sing-box 使用 `singbox.env` 指定的 APK；OpenClash 额外安装依赖，并预置上游 mihomo 程序。

产物为 `openwrt-25.12.6-mv1000-<plugin>`，按 [README 刷机步骤](../README.md#刷机) 操作。**该镜像不包含 honk 的自定义内核能力**，要运行 honk 需换回通用固件。

## 构建 sing-box 包

选择 **Optional: Build sing-box-tiny package**（[singbox.yml](../.github/workflows/singbox.yml)），产物发布到 `singbox-tiny-v<版本>` Release。

| 参数 | 行为 |
| --- | --- |
| `version` 留空 | 构建最新稳定版，成功后更新 `singbox.env`；`SINGBOX_PIN=1` 时跳过 |
| 指定 `version` | 构建该版本，不修改 `singbox.env` |
| `force=true` | 已有包时仍重新构建 |

```sh
gh workflow run singbox.yml --ref main
gh workflow run singbox.yml --ref main -f version=1.15.0-alpha.13
```

包构建完成后，手动安装到通用固件，或运行 `build.yml` 预装进备用镜像。包流程不会自动触发固件构建。

手动固定版本时，修改 [singbox.env](../singbox.env) 的 `SINGBOX_VERSION`、`SINGBOX_APK_SHA256`，并设 `SINGBOX_PIN=1`；哈希取对应 Release 的 `sha256sums`。tiny 变体包含 gVisor、QUIC、uTLS 和 Clash API，不包含 WireGuard、DHCP、ACME、Tailscale 功能。
