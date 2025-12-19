#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS Unpack Module for Calamares

Fast installation via rsync from the live filesystem.
This achieves <10 second installations on modern SSDs by avoiding
squashfs decompression overhead.

The live ISO contains pre-loaded packages, so we simply rsync
the entire filesystem to the target with appropriate exclusions.
"""

import shutil
import sys
from pathlib import Path

import libcalamares

# Add shedos_installer to Python path
# The installer package is at /opt/shedos-installer/ in the live ISO
INSTALLER_ROOT = Path("/opt/shedos-installer")
sys.path.insert(0, str(INSTALLER_ROOT))

from shedos_installer.utils.command import run_command


# Directories to exclude from rsync
# These are either virtual filesystems, temporary, or will be recreated
RSYNC_EXCLUDES = [
    "/dev/*",
    "/proc/*",
    "/sys/*",
    "/tmp/*",
    "/run/*",
    "/mnt/*",
    "/media/*",
    "/lost+found",
    # Archiso-specific
    "/run/archiso/*",
    "/airootfs/*",
    # Machine-specific files
    "/etc/machine-id",
    "/var/lib/dbus/machine-id",
    # Swap files
    "/swapfile",
    "/swap/*",
]

# Archiso artifacts to clean up after copy
ARCHISO_CLEANUP_PATHS = [
    "etc/systemd/system/getty@tty1.service.d",
    "etc/systemd/system/getty@tty1.service.d/autologin.conf",
    "etc/mkinitcpio.d/archiso.preset",
    "etc/systemd/system/multi-user.target.wants/pacman-init.service",
    "etc/systemd/journald.conf.d/volatile-storage.conf",
    "etc/systemd/logind.conf.d/do-not-suspend.conf",
    "root/.automated_script.sh",
    "root/.gnupg",
    "etc/systemd/system/etc-pacman.d-gnupg.mount",
    "etc/systemd/system/pacman-init.service",
]


def pretty_name():
    """Return the display name for this module."""
    return "Installing ShedOS (fast copy)"


def run():
    """
    Main entry point for the module.

    Copies the live filesystem to the target using rsync for
    maximum speed.
    """
    root_mount = libcalamares.globalstorage.value("rootMountPoint")

    if not root_mount:
        return ("No mount point", "rootMountPoint not set in global storage")

    root_mount = Path(root_mount)

    # Detect live environment source
    # Try archiso paths first
    live_root = Path("/run/archiso/airootfs")
    if not live_root.exists():
        live_root = Path("/run/archiso/cowspace/persistent")
        if not live_root.exists():
            # Fallback to root filesystem
            live_root = Path("/")

    libcalamares.utils.debug(f"Source: {live_root}")
    libcalamares.utils.debug(f"Target: {root_mount}")

    # Build rsync command
    cmd = [
        "rsync",
        "-aAXH",           # Archive mode, preserve ACLs, xattrs, hardlinks
        "--info=progress2", # Show progress
        "--no-inc-recursive", # Faster for large trees
    ]

    # Add exclusions
    for excl in RSYNC_EXCLUDES:
        cmd.extend(["--exclude", excl])

    # Source and destination (trailing slashes important!)
    cmd.extend([f"{live_root}/", f"{root_mount}/"])

    libcalamares.utils.debug(f"Running: {' '.join(cmd)}")

    # Run rsync
    result = run_command(cmd, timeout=600)  # 10 minute timeout

    if not result.success:
        return ("Copy failed", f"rsync failed: {result.stderr}")

    libcalamares.utils.debug("rsync completed successfully")

    # Clean up archiso artifacts
    cleanup_count = 0
    for rel_path in ARCHISO_CLEANUP_PATHS:
        full_path = root_mount / rel_path
        if full_path.exists():
            try:
                if full_path.is_dir():
                    shutil.rmtree(full_path)
                else:
                    full_path.unlink()
                cleanup_count += 1
                libcalamares.utils.debug(f"Cleaned up: {rel_path}")
            except Exception as e:
                libcalamares.utils.warning(f"Could not remove {rel_path}: {e}")

    libcalamares.utils.debug(f"Cleaned up {cleanup_count} archiso artifacts")

    # Create essential directories that were excluded
    essential_dirs = ["dev", "proc", "sys", "tmp", "run", "mnt", "media"]
    for dirname in essential_dirs:
        dir_path = root_mount / dirname
        dir_path.mkdir(mode=0o755, exist_ok=True)

    # Set /tmp permissions
    (root_mount / "tmp").chmod(0o1777)

    # Generate new machine-id (empty file, systemd will populate on first boot)
    machine_id_path = root_mount / "etc" / "machine-id"
    machine_id_path.touch()

    libcalamares.utils.debug("Fast copy complete")

    return None  # Success
