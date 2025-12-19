#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS Limine Bootloader Module for Calamares

Installs the Limine bootloader instead of GRUB.
Supports both UEFI and BIOS boot modes, with LUKS encryption support.

Limine is a modern, fast, minimal bootloader that provides:
- Quick boot times
- Simple configuration
- UEFI and legacy BIOS support
- LUKS2 encryption support
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import libcalamares

# Add shedos_installer to Python path
# The installer package is at /opt/shedos-installer/ in the live ISO
INSTALLER_ROOT = Path("/opt/shedos-installer")
sys.path.insert(0, str(INSTALLER_ROOT))

from shedos_installer.core.bootloader import LimineInstaller
from shedos_installer.utils.hardware import get_gpus, is_uefi


def pretty_name():
    """Return the display name for this module."""
    return "Installing Limine bootloader"


def run():
    """
    Main entry point for the module.

    Installs and configures the Limine bootloader based on system
    configuration (UEFI/BIOS, encryption, NVIDIA).
    """
    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")

    if not root_mount_point:
        root_mount_point = "/tmp/calamares-root"

    # Get partition information from global storage
    partitions = libcalamares.globalstorage.value("partitions")

    if not partitions:
        return ("No partitions found", "Partition information not available")

    # ========================================================================
    # CRITICAL: Mount ESP before bootloader installation
    # The Calamares mount module doesn't mount the ESP, only root + subvolumes
    # If ESP isn't mounted, LimineInstaller creates directories in BTRFS
    # instead of writing to the actual ESP partition → boot fails
    # ========================================================================

    # Find ESP partition
    esp_device = None
    for partition in partitions:
        if partition.get("mountPoint") == "/boot/efi":
            esp_device = partition.get("device")
            break

    if not esp_device:
        return ("ESP not found", "No partition configured for /boot/efi")

    # Mount ESP
    esp_path = os.path.join(root_mount_point, "boot", "efi")
    os.makedirs(esp_path, exist_ok=True)

    if not os.path.ismount(esp_path):
        libcalamares.utils.debug(f"Mounting ESP {esp_device} at {esp_path}")
        try:
            subprocess.run(["mount", "-t", "vfat", esp_device, esp_path], check=True)
            libcalamares.utils.debug("ESP mounted successfully")
        except subprocess.CalledProcessError as e:
            return (f"Failed to mount ESP: {e}", f"Could not mount {esp_device} at {esp_path}")
    else:
        libcalamares.utils.debug(f"ESP already mounted at {esp_path}")

    # ========================================================================

    # Extract required information from partitions
    root_uuid = None
    luks_uuid = None
    disk_device = None

    for partition in partitions:
        mount_point = partition.get("mountPoint", "")

        if mount_point == "/":
            root_uuid = partition.get("uuid")
            device = partition.get("device", "")

            # Extract base disk from partition
            # e.g., /dev/sda1 -> /dev/sda, /dev/nvme0n1p1 -> /dev/nvme0n1
            if device:
                if "nvme" in device or "mmcblk" in device:
                    # NVMe/MMC: /dev/nvme0n1p1 -> /dev/nvme0n1
                    disk_device = re.sub(r'p\d+$', '', device)
                else:
                    # SATA/SCSI: /dev/sda1 -> /dev/sda
                    disk_device = re.sub(r'\d+$', '', device)

        # Check for LUKS encryption
        if partition.get("luksMapperName"):
            luks_uuid = partition.get("luksUuid")

    if not root_uuid:
        return ("Missing root UUID", "Could not determine root partition UUID")

    libcalamares.utils.debug(f"Root UUID: {root_uuid}")
    libcalamares.utils.debug(f"Disk device: {disk_device}")
    libcalamares.utils.debug(f"LUKS UUID: {luks_uuid}")
    libcalamares.utils.debug(f"UEFI mode: {is_uefi()}")

    # Detect NVIDIA GPU
    gpus = get_gpus()
    has_nvidia = any(gpu.is_nvidia for gpu in gpus)

    # Check if user's profile warrants NVIDIA drivers
    profile = libcalamares.globalstorage.value("shedos_profile")
    install_nvidia = has_nvidia and profile in ["desktop", "developer", "full"]

    libcalamares.utils.debug(f"NVIDIA detected: {has_nvidia}")
    libcalamares.utils.debug(f"Install NVIDIA drivers: {install_nvidia}")

    # Create and run LimineInstaller
    limine = LimineInstaller(
        mount_point=root_mount_point,
        root_uuid=root_uuid,
        luks_uuid=luks_uuid,
        nvidia=install_nvidia,
    )

    # Install bootloader
    if not limine.install(disk_device or ""):
        return ("Bootloader installation failed", "Failed to install Limine bootloader")

    libcalamares.utils.debug("Limine bootloader installed")

    # Configure mkinitcpio with proper hooks
    if not limine.configure_mkinitcpio():
        return ("mkinitcpio configuration failed", "Failed to configure mkinitcpio")

    libcalamares.utils.debug("mkinitcpio configured and initramfs regenerated")

    # Store NVIDIA status for later modules
    libcalamares.globalstorage.insert("shedos_install_nvidia", install_nvidia)
    libcalamares.globalstorage.insert("shedos_has_nvidia", has_nvidia)

    return None  # Success
