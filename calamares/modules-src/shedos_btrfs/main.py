#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS BTRFS Subvolume Module for Calamares

Creates the 13-subvolume BTRFS layout with selective CoW (Copy-on-Write)
disabling for database, VM, and cache directories.

Subvolumes with CoW disabled:
- @log, @cache, @temp, @pkg (logs and caches)
- @libvirt, @docker, @database (virtualization and databases)
"""

import sys
from pathlib import Path

import libcalamares

# Add shedos_installer to Python path
# The installer package is at /opt/shedos-installer/ in the live ISO
INSTALLER_ROOT = Path("/opt/shedos-installer")
sys.path.insert(0, str(INSTALLER_ROOT))

from shedos_installer.config import DEFAULT_SUBVOLUMES
from shedos_installer.utils.command import run_command


def pretty_name():
    """Return the display name for this module."""
    return "Creating ShedOS BTRFS subvolumes"


def create_subvolumes(device: str, mount_point: Path) -> tuple[bool, str]:
    """
    Create all BTRFS subvolumes with appropriate CoW settings.

    Args:
        device: The BTRFS partition device path
        mount_point: Temporary mount point for subvolume creation

    Returns:
        Tuple of (success: bool, error_message: str)
    """
    # Ensure mount point exists
    mount_point.mkdir(parents=True, exist_ok=True)

    # Mount the root BTRFS filesystem
    result = run_command([
        "mount", "-t", "btrfs", "-o", "compress=zstd:1",
        device, str(mount_point)
    ])

    if not result.success:
        return False, f"Failed to mount {device}: {result.stderr}"

    try:
        for subvol in DEFAULT_SUBVOLUMES:
            subvol_path = mount_point / subvol.name

            # Create the subvolume
            result = run_command([
                "btrfs", "subvolume", "create", str(subvol_path)
            ])

            if not result.success:
                return False, f"Failed to create subvolume {subvol.name}: {result.stderr}"

            libcalamares.utils.debug(f"Created subvolume: {subvol.name} -> {subvol.mountpoint}")

            # Disable Copy-on-Write for subvolumes that don't need it
            # (databases, VMs, logs, caches)
            if not subvol.cow:
                result = run_command([
                    "chattr", "+C", str(subvol_path)
                ])
                if result.success:
                    libcalamares.utils.debug(f"Disabled CoW for: {subvol.name}")
                else:
                    # Not fatal, just log warning
                    libcalamares.utils.warning(f"Could not disable CoW for {subvol.name}")

        return True, ""

    finally:
        # Always unmount
        run_command(["umount", str(mount_point)])


def run():
    """
    Main entry point for the module.

    Gets the root partition from global storage and creates all
    BTRFS subvolumes on it.
    """
    # Get partition information from global storage
    partitions = libcalamares.globalstorage.value("partitions")

    if not partitions:
        return ("No partitions found", "Partition information not available in global storage")

    # Find the root partition
    root_device = None
    for partition in partitions:
        if partition.get("mountPoint") == "/":
            root_device = partition.get("device")
            break

    if not root_device:
        return ("No root partition", "Could not identify root partition")

    # Check if using LUKS encryption
    encrypted_device = libcalamares.globalstorage.value("encryptedRootDevice")
    if encrypted_device:
        root_device = encrypted_device
        libcalamares.utils.debug(f"Using encrypted device: {root_device}")

    libcalamares.utils.debug(f"Creating BTRFS subvolumes on {root_device}")

    # Create subvolumes
    mount_point = Path("/tmp/shedos_btrfs_setup")
    success, error = create_subvolumes(root_device, mount_point)

    if not success:
        return ("BTRFS subvolume creation failed", error)

    libcalamares.utils.debug(f"Successfully created {len(DEFAULT_SUBVOLUMES)} subvolumes")

    # Store subvolume info for other modules
    libcalamares.globalstorage.insert("shedos_subvolumes_created", True)

    return None  # Success
