#
# honk-bin: installs the upstream static aarch64 musl build of honk-core.
#
# The binary is a GitHub release asset, so nothing here compiles Rust: the
# OpenWrt tree only unpacks it. A source build of honk needs rustup, a
# nightly toolchain for the eBPF object, BoringSSL and SQLite, which is not
# worth carrying in this image pipeline.
#

PKG_DIR:=$(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

include $(TOPDIR)/rules.mk

PKG_NAME:=honk-bin
PKG_VERSION:=0.1.0_beta5
PKG_RELEASE:=1

PKG_LICENSE:=GPL-3.0-only
PKG_LICENSE_FILES:=LICENSE

PKG_SOURCE:=honk-core-v0.1.0-beta.5-aarch64-unknown-linux-musl-full.tar.gz
PKG_SOURCE_URL:=https://github.com/daeuniverse/honk/releases/download/v0.1.0-beta.5
PKG_HASH:=6e06b12c05f775744b4cc65f80d29ae486e65f4a433d2878b197703d8f83e7ae

include $(INCLUDE_DIR)/package.mk

define Package/honk-bin
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=Web Servers/Proxies
  TITLE:=honk eBPF transparent proxy (upstream static build)
  URL:=https://github.com/daeuniverse/honk
  LICENSE:=GPL-3.0-only
  DEPENDS:=+kmod-veth +kmod-sched-core +kmod-sched-bpf \
           +kmod-nft-core +kmod-nft-queue +kmod-nfnetlink-queue \
           +kmod-nf-conntrack +v2ray-geoip +v2ray-geosite
endef

define Package/honk-bin/description
 honk is an eBPF transparent proxy engine. This package installs the
 upstream static musl binary; the kernel must provide BTF and cgroup BPF,
 which the MV1000 honk image enables. The service is installed disabled.
endef

define Package/honk-bin/conffiles
/etc/config/honk
/etc/honk/config.dae
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(TAR) -xzf $(DL_DIR)/$(PKG_SOURCE) -C $(PKG_BUILD_DIR) --strip-components=1
endef

define Build/Compile
endef

define Package/honk-bin/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/honk-core $(1)/usr/bin/honk-core
	$(INSTALL_DIR) $(1)/usr/share/licenses/honk
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/LICENSE $(1)/usr/share/licenses/honk/LICENSE
	$(INSTALL_DIR) $(1)/etc/init.d
	$(INSTALL_BIN) $(PKG_DIR)/files/honk.init $(1)/etc/init.d/honk
	$(INSTALL_DIR) $(1)/etc/config
	$(INSTALL_CONF) $(PKG_DIR)/files/honk.config $(1)/etc/config/honk
	$(INSTALL_DIR) $(1)/etc/honk
	$(INSTALL_CONF) $(PKG_DIR)/files/config.dae $(1)/etc/honk/config.dae
	$(INSTALL_DIR) $(1)/lib/upgrade/keep.d
	printf '%s\n' '/etc/honk/data/' > $(1)/lib/upgrade/keep.d/honk
	$(INSTALL_DIR) $(1)/etc/uci-defaults
	$(INSTALL_BIN) $(PKG_DIR)/files/honk.uci-defaults $(1)/etc/uci-defaults/99-honk
endef

$(eval $(call BuildPackage,honk-bin))
