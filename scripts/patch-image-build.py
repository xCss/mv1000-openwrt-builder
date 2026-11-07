#!/usr/bin/env python3
"""Prepare ext4 before the normal sdcard/gzip/fwtool metadata pipeline."""
from pathlib import Path
import shutil
import sys

tree = Path(sys.argv[1])
repo = Path(__file__).resolve().parents[1]
path = tree / "include/image.mk"
text = path.read_text()
start = text.index("define Image/mkfs/ext4\n")
end = text.index("\nendef", start)
recipe = '\n\t$(TOPDIR)/scripts/mv1000-prepare-rootfs.sh $@'
assert "mv1000-prepare-rootfs" not in text, "patch already applied"
text = text[:end] + recipe + text[end:]
path.write_text(text)
dest = tree / "scripts/mv1000-prepare-rootfs.sh"
shutil.copyfile(repo / "scripts/prepare-rootfs-ext4.sh", dest)
dest.chmod(0o755)
