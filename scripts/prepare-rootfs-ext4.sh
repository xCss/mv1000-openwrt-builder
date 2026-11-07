#!/bin/sh
# Run on the build host, on the unmounted root.ext4 BEFORE image assembly and
# metadata/checksum generation. make_ext4fs' resize inode has reserved-GDT block
# ordering incompatible with online growth. Remove that feature offline, then
# let e2fsck release its blocks and normalize the bitmap padding.
set -eu
image="$1"
[ -f "$image" ] && [ ! -b "$image" ]
/usr/sbin/tune2fs -O ^resize_inode "$image"
rc=0
/usr/sbin/e2fsck -f -y "$image" || rc=$?
[ "$rc" -le 1 ]
/usr/sbin/e2fsck -f -n "$image"
