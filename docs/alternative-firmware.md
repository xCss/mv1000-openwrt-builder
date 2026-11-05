# 备用方案：sing-box / OpenClash

仓库默认路线为 [honk / sing-box 通用固件](../README.md)。**已有新通用固件时，使用 sing-box 只需安装程序并切换服务/DNS，无需另刷本文的镜像**，步骤见 [同一固件安装与切换](proxy-switching.md)。

本文保留官方预编译内核的 Image Builder 路线。需要这种内核的 sing-box、OpenClash 或不带代理镜像时，手动运行以下 workflow。

## 手动构建固件

在 GitHub Actions 中选择 **Optional: Build MV1000 sing-box/OpenClash firmware**（[build.yml](../.github/workflows/build.yml)）：

| 参数 | 可选值 | 默认 |
| --- | --- | --- |
| `plugin` | `singbox` / `openclash` / `none` | `singbox` |
| `rootfs_mb` | 根文件系统大小，单位 MiB | `256` |

CLI 示例：

```sh
gh workflow run build.yml --ref main -f plugin=singbox -f rootfs_mb=256
gh workflow run build.yml --ref main -f plugin=openclash -f rootfs_mb=256
```

该流程下载 OpenWrt 25.12.6 官方 Image Builder，使用 profile `glinet_gl-mv1000` 组装镜像。它使用官方预编译内核，不复用 `honk.yml` 的自定义 BTF 内核，也不调用 honk 构建。

公共内容包括 LuCI、中文包、包管理器、固定为 1.0.14 的 Vantage 主题与应用、分区工具和仓库的 `files/` 首启设置。sing-box APK 按 `singbox.env` 的 SHA256 校验，Vantage APK 按 workflow 内固定 SHA256 校验。Image Builder 关闭第三方包签名检查，官方软件包通过 HTTPS 下载。

选择 OpenClash 时额外安装 `dnsmasq-full` 等依赖，并预置 mihomo 内核，避免首次启动下载。此分支从上游 latest release 获取 OpenClash 和 mihomo。

固件 artifact 为 `openwrt-25.12.6-mv1000-<plugin>`，内含 ext4 SD-card 压缩镜像和 `sha256sums`。分区、备份和 U-Boot 刷机步骤见 [主说明](../README.md#3-分区与刷机)；备用 Image Builder 路线的启动分区由官方构建器配置决定，不使用 honk workflow 的 32 MiB 设置。

## 按需更新 sing-box 包

新通用固件后装 sing-box，以及 `build.yml` 的 sing-box 分支，都可以使用 [singbox.env](../singbox.env) 指定的 `singbox-tiny-v<版本>` Release。如果包不存在，先运行 **Optional: Build sing-box-tiny package**（[singbox.yml](../.github/workflows/singbox.yml)）。

该流程只接受手动触发，没有定时任务、推送触发或下游固件自动触发：

- `version` 留空：读取最新稳定 Release，构建并发布包，然后更新 `singbox.env`。`SINGBOX_PIN=1` 时跳过这一更新。
- 指定 `version`：构建并发布指定版本，例如 `1.15.0-alpha.13`，不修改 `singbox.env`。
- `force=true`：即使 Release 中已有包也重新构建。

```sh
# 按需更新稳定版；完成后将 APK 装入通用固件，或另行运行 build.yml
gh workflow run singbox.yml --ref main

# 构建指定测试版，不修改固件版本选择
gh workflow run singbox.yml --ref main -f version=1.15.0-alpha.13
```

编译失败时不更新 `singbox.env`。手动固定版本时，从对应 Release 的 `sha256sums` 取 APK 哈希，更新 `SINGBOX_VERSION`、`SINGBOX_APK_SHA256`，并设 `SINGBOX_PIN=1`。随后在通用固件上安装该 APK，或手动运行 `build.yml` 预装到官方内核镜像。

sing-box tiny 使用独立 Go 交叉编译和 OpenWrt SDK 的 APK 打包工具。固定 tags 为 `with_gvisor,with_quic,with_utls,with_clash_api,badlinkname,tfogo_checklinkname0`，不包含 WireGuard、DHCP、ACME、Tailscale 对应功能。

## sing-box 使用与验证

1. 编辑 `/etc/sing-box/config.json`。
2. 在 `/etc/config/sing-box` 中将 `enabled` 设为 `1`；TUN 模式使用 `root` 用户。
3. 执行配置检查后启动：

```sh
sing-box check -c /etc/sing-box/config.json
/etc/init.d/sing-box enable
/etc/init.d/sing-box start
logread -e sing-box
```

1.14 起可使用原生 API/dashboard，例如：

```json
{
  "services": [{
    "type": "api",
    "listen": "0.0.0.0",
    "listen_port": 9090,
    "secret": "<替换为密钥>",
    "dashboard": true
  }]
}
```

`listen` 只填地址，端口放在 `listen_port`。Dashboard 默认下载到工作目录 `/usr/share/sing-box/dashboard`，访问 `http://192.168.1.2:9090/dashboard/`。配置语法以选定版本的上游文档为准。

TUN、DNS、路由和节点规则需要另行配置。浏览器使用系统 DNS，才能遵循旁路由 DNS 策略。honk 与 sing-box 的透明接管不应同时启用。

**在通用固件上切回 honk，无需重刷**，按 [切换说明](proxy-switching.md) 恢复服务和 DNS 即可。只有刷入了本文的官方内核备用镜像，才需要换回 `honk.yml` 产物；该备用镜像不提供 honk 所需的自定义内核。

参考：[sing-box](https://github.com/SagerNet/sing-box)、[OpenClash](https://github.com/vernesong/OpenClash)、[Image Builder](https://openwrt.org/docs/guide-user/additional-software/imagebuilder)。
