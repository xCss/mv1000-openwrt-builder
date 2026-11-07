#!/usr/bin/env python3
"""Root-only integration checks. Only loop devices backed by our temp files change.

Run with sudo python3 tests/rootfs_growth.py, or --image firmware.img.gz to test
the final, build-time-normalized make_ext4fs output.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile
import zlib

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / "files/lib/mv1000-rootfs.sh"
DISK_BYTES = 15269888 * 512  # Actual MV1000 eMMC size, not a rounded-up 8 GB.


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout.strip()


def entries(path):
    with open(path, "rb") as f:
        mbr = f.read(512)
    assert mbr[510:] == b"\x55\xaa"
    return mbr, [struct.unpack_from("<B3sB3sII", mbr, 446 + i * 16) for i in range(4)]


class Disk:
    def __init__(self, base, image=None, data=False, journal=True, prepare_legacy=False, legacy=False):
        self.base = Path(base)
        self.path = self.base / "disk.img"
        self.mount = self.base / "root"
        self.mount.mkdir()
        self.loop = None
        self.mounted = False
        if image:
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            with open(image, "rb") as src, self.path.open("wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(decoder.decompress(chunk))
                    if decoder.eof:  # OpenWrt metadata after gzip is intentional.
                        break
                assert decoder.eof, "incomplete gzip image"
            assert self.path.stat().st_size < DISK_BYTES
            if prepare_legacy:
                _, parts = entries(self.path)
                start, size = parts[1][4:6]
                root = self.base / "root.ext4"
                # Keep the 256 KiB partition padding out of the filesystem image.
                with self.path.open("rb") as src:
                    src.seek(start * 512 + 1024)
                    sb = src.read(1024)
                    length = struct.unpack_from("<I", sb, 4)[0] * (1024 << struct.unpack_from("<I", sb, 24)[0])
                    assert length <= size * 512
                    src.seek(start * 512)
                    root.write_bytes(src.read(length))
                print(run("sh", str(REPO / "scripts/prepare-rootfs-ext4.sh"), str(root)), flush=True)
                with self.path.open("r+b") as dst:
                    dst.seek(start * 512)
                    dst.write(root.read_bytes())
        with self.path.open("ab") as f:
            f.truncate(DISK_BYTES)
        if not image:
            layout = "label: dos\nlabel-id: 0x1234abcd\nunit: sectors\n\n2048,66048,83\n69632,524800,83\n"
            if data:
                layout += "595968,,83\n"
            run("sfdisk", str(self.path), input=layout)
        self.attach()
        if not image:
            run("mkfs.ext4", "-q", "-F", "-L", "kernel", self.loop + "p1")
            # Match the old make_ext4fs features rather than modern mke2fs defaults.
            features = "none,ext_attr,dir_index,filetype,extent,sparse_super,large_file,uninit_bg"
            if legacy:
                features += ",resize_inode"
            if journal:
                features += ",has_journal"
            run("mkfs.ext4", "-q", "-F", "-b", "4096", "-O", features,
                "-L", "rootfs", self.loop + "p2", "65536")
            if data:
                run("mkfs.ext4", "-q", "-F", "-L", "data", self.loop + "p3")
                # Payload must survive the skipped-layout path byte for byte.
                run("debugfs", "-w", "-R", "write /etc/hostname /keep-me", self.loop + "p3")
        run("mount", self.loop + "p2", str(self.mount))
        self.mounted = True
        self.state = self.mount / "etc/mv1000-rootfs"
        self.marker = self.mount / "rootfs-growth-payload"
        self.payload = os.urandom(1024 * 1024)
        self.marker.write_bytes(self.payload)
        self.uuid = run("blkid", "-p", "-s", "UUID", "-o", "value", self.loop + "p2")
        self.mbr, self.parts = entries(self.path)
        with self.path.open("rb") as f:
            f.seek(self.parts[0][4] * 512)
            self.boot_hash = hashlib.sha256(f.read(self.parts[0][5] * 512)).hexdigest()

    def attach(self):
        self.loop = run("losetup", "--find", "--show", "--partscan", str(self.path))
        # Minimal privileged containers have no udev to create partition nodes.
        for n in range(1, 5):
            dev = Path(self.loop + f"p{n}")
            sysdev = Path("/sys/class/block") / dev.name / "dev"
            if sysdev.exists():
                major, minor = map(int, sysdev.read_text().strip().split(":"))
                rdev = os.makedev(major, minor)
                if dev.exists() and dev.stat().st_rdev != rdev:
                    dev.unlink()  # A loop reused after detach can have new minors.
                if not dev.exists():
                    os.mknod(dev, stat.S_IFBLK | 0o600, rdev)

    def grow(self, expected=0, fake=None):
        env = dict(os.environ, LC_ALL="C")
        if fake:
            mocks = self.base / "mocks"
            mocks.mkdir(exist_ok=True)
            for name, code in fake.items():
                script = mocks / name
                script.write_text("#!/bin/sh\n" + code + "\n")
                script.chmod(0o755)
            env["PATH"] = str(mocks) + ":" + env["PATH"]
        result = subprocess.run(["sh", "-c", '. "$1"; grow_rootfs "$2" "$3" "$4"',
                                 "sh", str(LIB), self.loop, self.loop + "p2", str(self.state)],
                                env=env, text=True, capture_output=True)
        print(result.stdout, end="", flush=True)
        if result.returncode != expected:
            print(result.stderr)
            print((self.state / "log").read_text() if (self.state / "log").exists() else "no log")
        assert result.returncode == expected, (result.returncode, expected)

    def verify(self):
        run("sync")
        after, parts = entries(self.path)
        assert after[:462] == self.mbr[:462], "boot code/signature/p1 changed"
        assert after[478:] == self.mbr[478:], "p3/p4 changed"
        assert parts[1][2] == 0x83 and parts[1][4] == self.parts[1][4]
        assert (parts[1][4] + parts[1][5]) * 512 == DISK_BYTES
        assert self.marker.read_bytes() == self.payload
        assert self.uuid == run("blkid", "-p", "-s", "UUID", "-o", "value", self.loop + "p2")
        with self.path.open("rb") as f:
            f.seek(parts[0][4] * 512)
            assert self.boot_hash == hashlib.sha256(f.read(parts[0][5] * 512)).hexdigest()
        print(run("df", "-h", str(self.mount)), flush=True)
        with open(self.loop + "p2", "rb") as f:
            f.seek(1024)
            sb = f.read(1024)
        blocks = struct.unpack_from("<I", sb, 4)[0]
        block_size = 1024 << struct.unpack_from("<I", sb, 24)[0]
        assert blocks * block_size == parts[1][5] * 512
        assert os.statvfs(self.mount).f_blocks * os.statvfs(self.mount).f_frsize > DISK_BYTES * 0.9
        assert (self.state / "status").read_text().strip() == "complete"

    def close(self):
        if self.mounted:
            run("umount", str(self.mount))
            self.mounted = False
        if self.loop:
            # Offline fsck must find no damage after online growth.
            result = subprocess.run(["e2fsck", "-f", "-n", self.loop + "p2"], capture_output=True, text=True)
            try:
                assert result.returncode == 0, result.stdout + result.stderr
            finally:
                run("losetup", "-d", self.loop)
                self.loop = None


def exercise(kind, image=None, prepare_legacy=False):
    print(f"TEST {kind}", flush=True)
    with tempfile.TemporaryDirectory(prefix="mv1000-rootfs-") as tmp:
        disk = Disk(tmp, image=image, data=kind == "existing-p3", journal=kind != "no-journal",
                    prepare_legacy=prepare_legacy, legacy=kind == "unprepared-filesystem")
        try:
            if kind == "existing-p3":
                before = run("sha256sum", disk.loop + "p3").split()[0]
                disk.grow()
                assert (disk.state / "status").read_text().strip() == "skipped-layout"
                assert entries(disk.path)[0] == disk.mbr
                assert run("sha256sum", disk.loop + "p3").split()[0] == before
            elif kind == "unprepared-filesystem":
                disk.grow(expected=1)
                assert entries(disk.path)[0] == disk.mbr
                assert disk.marker.read_bytes() == disk.payload
            elif kind == "partition-failure":
                disk.grow(expected=1, fake={"sfdisk": 'case "$*" in *--dump*) exec /usr/sbin/sfdisk "$@";; *) exit 1;; esac'})
                assert entries(disk.path)[0] == disk.mbr
                assert disk.marker.read_bytes() == disk.payload
            elif kind == "resize-failure":
                disk.grow(expected=1, fake={"resize2fs": "exit 1"})
                assert disk.marker.read_bytes() == disk.payload
                disk.grow()
                disk.verify()
            elif kind == "resize-noop":
                disk.grow(expected=1, fake={"resize2fs": "exit 0"})
                assert disk.marker.read_bytes() == disk.payload
                disk.grow()
                disk.verify()
            elif kind == "reboot-resume":
                disk.grow(expected=10, fake={"partx": "exit 1"})
                # Don't create a reboot loop when the kernel size stays stale.
                disk.grow(expected=1, fake={"partx": "exit 1"})
                run("partx", "-u", "--nr", "2", disk.loop)
                disk.grow()
                disk.verify()
            else:
                disk.grow()
                disk.verify()
                before = entries(disk.path)[0]
                disk.grow()  # Re-running must be harmless.
                disk.verify()
                assert entries(disk.path)[0] == before
        finally:
            disk.close()
    print(f"PASS {kind}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path)
    parser.add_argument("--prepare-legacy", action="store_true",
                        help="test build-time preparation of a previous firmware image")
    args = parser.parse_args()
    assert os.geteuid() == 0, "run as root; only disposable loop devices are modified"
    for tool in ("sfdisk", "losetup", "partx", "resize2fs", "mkfs.ext4", "blkid", "e2fsck"):
        assert shutil.which(tool), f"missing {tool}"
    if args.image:
        exercise("built-firmware", args.image, args.prepare_legacy)
    else:
        for case in ("fresh-online", "no-journal", "existing-p3", "unprepared-filesystem",
                     "partition-failure", "reboot-resume", "resize-failure", "resize-noop"):
            exercise(case)
