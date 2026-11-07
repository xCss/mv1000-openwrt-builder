#!/bin/sh
# Grow an MBR/ext4 p2 in place. The caller must identify the running root disk.
# Return 10 only when a partition-table reboot is needed, 0 when done or skipped.

rootfs_note() {
	printf '%s\n' "$*"
	printf '%s\n' "$*" >> "$STATE/log"
}

rootfs_status() {
	printf '%s\n' "$1" > "$STATE/status.new" &&
		mv "$STATE/status.new" "$STATE/status"
}

rootfs_same() {
	[ "$(md5sum "$1" | awk '{print $1}')" = "$(md5sum "$2" | awk '{print $1}')" ]
}

rootfs_fail() {
	rootfs_note "ERROR: $*"
	rootfs_status failed
	return 1
}

rootfs_layout() {
	sfdisk --dump "$DISK" > "$STATE/layout.current" || return 1
	# Do not modify GPT, extended partitions, or disks with a data partition.
	grep -qx 'label: dos' "$STATE/layout.current" || return 1
	[ "$(grep -c '^/dev/' "$STATE/layout.current")" = 2 ] || return 1
	grep -q "^${DISK}p1 :" "$STATE/layout.current" || return 1
	grep -q "^${PART} :" "$STATE/layout.current" || return 1
	line=$(grep "^${PART} :" "$STATE/layout.current")
	START=$(printf '%s\n' "$line" | sed -n 's/.*start= *\([0-9]*\).*/\1/p')
	SIZE=$(printf '%s\n' "$line" | sed -n 's/.*size= *\([0-9]*\).*/\1/p')
	TYPE=$(printf '%s\n' "$line" | sed -n 's/.*type= *\([^, ]*\).*/\1/p')
	[ "$TYPE" = 83 ] && [ -n "$START" ] && [ -n "$SIZE" ] || return 1
	# p1 must end before p2 begins.
	first=$(grep "^${DISK}p1 :" "$STATE/layout.current")
	p1start=$(printf '%s\n' "$first" | sed -n 's/.*start= *\([0-9]*\).*/\1/p')
	p1size=$(printf '%s\n' "$first" | sed -n 's/.*size= *\([0-9]*\).*/\1/p')
	[ -n "$p1start" ] && [ -n "$p1size" ] || return 1
	[ "$START" -ge $((p1start + p1size)) ] && [ "$SIZE" -gt 0 ]
}

grow_rootfs() {
	DISK="$1"
	PART="$2"
	STATE="$3"
	umask 077
	mkdir -p "$STATE" || return 1
	if [ ! -b "$DISK" ] || [ ! -b "$PART" ]; then
		rootfs_fail 'not a block device'; return 1
	fi
	for tool in sfdisk partx resize2fs blkid md5sum dd hexdump; do
		command -v "$tool" >/dev/null 2>&1 || { rootfs_fail "missing $tool"; return 1; }
	done
	[ "$(cat "/sys/class/block/${DISK##*/}/queue/logical_block_size")" = 512 ] || {
		rootfs_fail 'only 512-byte-sector disks are supported'; return 1;
	}
	[ "$(blkid -p -s TYPE -o value "$PART")" = ext4 ] || {
		rootfs_fail 'root filesystem is not ext4'; return 1;
	}
	if ! rootfs_layout; then
		rootfs_note 'SKIPPED: expected only MBR p1 + ext4 p2; existing data partitions are preserved. Use a full two-partition image flash for auto-growth.'
		rootfs_status skipped-layout
		return 0
	fi
	# The build host normalizes make_ext4fs images and removes resize_inode.
	# Never attempt live growth of the unprepared older firmware filesystem.
	features=$(dd if="$PART" bs=1 skip=1116 count=4 2>/dev/null | hexdump -v -e '1/4 "%u"')
	case "$features" in
		''|*[!0-9]*) rootfs_fail 'cannot read ext4 feature flags'; return 1 ;;
	esac
	if [ $((features & 16)) -ne 0 ]; then
		rootfs_fail 'resize_inode is present; use a firmware image prepared for online expansion'; return 1
	fi
	disk_size=$(cat "/sys/class/block/${DISK##*/}/size") || return 1
	# End on a 1 MiB boundary. Never shrink, and keep MBR sector counts in range.
	new_size=$((disk_size / 2048 * 2048 - START))
	if [ "$new_size" -le 0 ] || [ "$new_size" -gt 4294967295 ] || [ "$new_size" -lt "$SIZE" ]; then
		rootfs_fail 'invalid target size or attempted shrink'; return 1
	fi
	root_uuid=$(blkid -p -s UUID -o value "$PART")
	[ -n "$root_uuid" ] || { rootfs_fail 'root UUID is missing'; return 1; }
	if [ "$new_size" -gt "$SIZE" ]; then
		rootfs_note "Growing $PART: $SIZE -> $new_size sectors; start=$START, UUID=$root_uuid"
		dd if="$DISK" of="$STATE/mbr.before" bs=512 count=1 2>/dev/null || return 1
		cp "$STATE/layout.current" "$STATE/layout.before" || return 1
		rootfs_status partitioning || return 1
		sync
		old_start="$START"
		# Updating only p2 preserves the MBR signature/PARTUUID and p1. Do not ask
		# BLKRRPART to reread a mounted disk; update p2's kernel size separately.
		if ! printf 'size=%s\n' "$new_size" | sfdisk --no-reread --no-tell-kernel \
			--wipe never --wipe-partitions never -N 2 "$DISK" >> "$STATE/log" 2>&1; then
			dd if="$STATE/mbr.before" of="$DISK" bs=512 count=1 conv=notrunc 2>/dev/null
			sync
			rootfs_fail 'partition update failed; restored original MBR'; return 1
		fi
		# Verify boot code, disk signature, p1, root start/type and empty p3/p4.
		dd if="$STATE/mbr.before" of="$STATE/prefix.before" bs=1 count=462 2>/dev/null
		dd if="$DISK" of="$STATE/prefix.after" bs=1 count=462 2>/dev/null
		dd if="$STATE/mbr.before" of="$STATE/tail.before" bs=1 skip=478 count=34 2>/dev/null
		dd if="$DISK" of="$STATE/tail.after" bs=1 skip=478 count=34 2>/dev/null
		if ! rootfs_layout || [ "$START" != "$old_start" ] || [ "$SIZE" != "$new_size" ] ||
			! rootfs_same "$STATE/prefix.before" "$STATE/prefix.after" ||
			! rootfs_same "$STATE/tail.before" "$STATE/tail.after"; then
			dd if="$STATE/mbr.before" of="$DISK" bs=512 count=1 conv=notrunc 2>/dev/null
			sync
			rootfs_fail 'partition verification failed; restored original MBR'; return 1
		fi
		sync
	fi
	# Also handles an interrupted run with an already-grown on-disk partition.
	if [ "$(cat "/sys/class/block/${PART##*/}/size")" != "$new_size" ]; then
		partx -u --nr 2 "$DISK" >> "$STATE/log" 2>&1 || true
	fi
	if [ "$(cat "/sys/class/block/${PART##*/}/size")" != "$new_size" ]; then
		if [ -f "$STATE/reboot-requested" ]; then
			rootfs_fail 'kernel still reports old partition size; automatic reboot already requested'; return 1
		fi
		printf '%s\n' "$root_uuid" > "$STATE/reboot-requested"
		rootfs_status reboot-required
		rootfs_note 'Partition table saved; one reboot is required before filesystem growth.'
		sync
		return 10
	fi
	rootfs_status resizing || return 1
	if ! resize2fs "$PART" >> "$STATE/log" 2>&1; then
		rootfs_fail 'resize2fs failed; inspect log before retrying. Do not restore the smaller partition table.'; return 1
	fi
	[ "$(blkid -p -s UUID -o value "$PART")" = "$root_uuid" ] || {
		rootfs_fail 'filesystem UUID changed unexpectedly'; return 1;
	}
	# MV1000 is far below 2^32 ext4 blocks. Verify the superblock, not just
	# resize2fs's exit status (a no-op against a stale device must not pass).
	blocks=$(dd if="$PART" bs=1 skip=1028 count=4 2>/dev/null | hexdump -v -e '1/4 "%u"')
	block_shift=$(dd if="$PART" bs=1 skip=1048 count=4 2>/dev/null | hexdump -v -e '1/4 "%u"')
	if [ "$((blocks * (1024 << block_shift)))" != "$((new_size * 512))" ]; then
		rootfs_fail 'ext4 size does not equal the enlarged partition size'; return 1
	fi
	rootfs_status complete || return 1
	rm -f "$STATE/reboot-requested"
	rootfs_note "Complete: $PART is now $((new_size / 2048)) MiB; filesystem UUID preserved."
	sync
	return 0
}
