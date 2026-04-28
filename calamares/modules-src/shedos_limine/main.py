#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Install Limine bootloader (UEFI or BIOS), wired up for LUKS + NVIDIA
when those are detected. Delegates the heavy lifting to
shedos_installer.core.bootloader.LimineInstaller."""

import os
import re
import subprocess
import sys
from pathlib import Path

import libcalamares

# Installer package lives at /opt/shedos-installer/ in the live ISO.
INSTALLER_ROOT = Path("/opt/shedos-installer")
sys.path.insert(0, str(INSTALLER_ROOT))

from shedos_installer.core.bootloader import LimineInstaller
from shedos_installer.utils.hardware import get_gpus, is_uefi


def pretty_name():
    return "Installing Limine bootloader"


def run():
    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")

    if not root_mount_point:
        root_mount_point = "/tmp/calamares-root"

    partitions = libcalamares.globalstorage.value("partitions")

    if not partitions:
        return ("No partitions found", "Partition information not available")

    # CRITICAL: Calamares' mount module mounts root + subvolumes but not
    # the ESP. Without mounting it here, LimineInstaller would write
    # directories into BTRFS at /boot/efi instead of the ESP partition,
    # and the install would silently fail to boot.
    esp_device = None
    for partition in partitions:
        if partition.get("mountPoint") == "/boot/efi":
            esp_device = partition.get("device")
            break

    if not esp_device:
        return ("ESP not found", "No partition configured for /boot/efi")

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

    root_uuid = None
    luks_uuid = None
    disk_device = None

    for partition in partitions:
        mount_point = partition.get("mountPoint", "")

        if mount_point == "/":
            root_uuid = partition.get("uuid")
            device = partition.get("device", "")

            # Strip the partition number off to get the parent disk:
            #   /dev/sda1       -> /dev/sda
            #   /dev/nvme0n1p1  -> /dev/nvme0n1
            if device:
                if "nvme" in device or "mmcblk" in device:
                    disk_device = re.sub(r'p\d+$', '', device)
                else:
                    disk_device = re.sub(r'\d+$', '', device)

        if partition.get("luksMapperName"):
            luks_uuid = partition.get("luksUuid")

    if not root_uuid:
        return ("Missing root UUID", "Could not determine root partition UUID")

    libcalamares.utils.debug(f"Root UUID: {root_uuid}")
    libcalamares.utils.debug(f"Disk device: {disk_device}")
    libcalamares.utils.debug(f"LUKS UUID: {luks_uuid}")
    libcalamares.utils.debug(f"UEFI mode: {is_uefi()}")

    gpus = get_gpus()
    has_nvidia = any(gpu.is_nvidia for gpu in gpus)

    profile = libcalamares.globalstorage.value("shedos_profile")
    install_nvidia = has_nvidia and profile in ["desktop", "developer", "full"]

    libcalamares.utils.debug(f"NVIDIA detected: {has_nvidia}")
    libcalamares.utils.debug(f"Install NVIDIA drivers: {install_nvidia}")

    limine = LimineInstaller(
        mount_point=root_mount_point,
        root_uuid=root_uuid,
        luks_uuid=luks_uuid,
        nvidia=install_nvidia,
    )

    if not limine.install(disk_device or ""):
        return ("Bootloader installation failed", "Failed to install Limine bootloader")

    libcalamares.utils.debug("Limine bootloader installed")

    if not limine.configure_mkinitcpio():
        return ("mkinitcpio configuration failed", "Failed to configure mkinitcpio")

    libcalamares.utils.debug("mkinitcpio configured and initramfs regenerated")

    libcalamares.globalstorage.insert("shedos_install_nvidia", install_nvidia)
    libcalamares.globalstorage.insert("shedos_has_nvidia", has_nvidia)

    return None
