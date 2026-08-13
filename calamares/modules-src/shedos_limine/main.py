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

# Calamares loads this file from /usr/lib/calamares/modules, which puts
# nothing of the installer on the import path.
INSTALLER_ROOT = Path("/usr/lib/shedos-installer")
sys.path.insert(0, str(INSTALLER_ROOT))

from shedos_installer.core.bootloader import LimineInstaller
from shedos_installer.utils.hardware import get_gpus, should_install_nvidia, is_uefi
from shedos_installer.utils.vconsole import sanitize_keymap


def pretty_name():
    return "Installing Limine bootloader"


def _scan_partitions(partitions):
    """Pick (root_uuid, root_fs, luks_uuid, disk_device, swap_luks) from
    Calamares' globalstorage partition list.

    Only the root partition's LUKS UUID counts for `luks_uuid`: the cmdline
    must decrypt the container holding the root fs. With several encrypted
    partitions (e.g. / plus a LUKS /home) any-partition-wins used to pick
    whichever came last.

    `swap_luks` is (luks_uuid, mapper_name) for the separate encrypted swap
    container, or None. Hibernation resumes from the decrypted swap mapper,
    so the initramfs needs that container's own rd.luks.name to unlock it."""
    root_uuid = None
    root_fs = None
    luks_uuid = None
    disk_device = None
    swap_luks = None

    for partition in partitions:
        if (partition.get("fs") or "").lower() == "linuxswap" \
                and partition.get("luksMapperName"):
            swap_luks = (partition.get("luksUuid"), partition.get("luksMapperName"))
        if partition.get("mountPoint", "") != "/":
            continue
        root_uuid = partition.get("uuid")
        root_fs = (partition.get("fs") or "").lower()
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

    return root_uuid, root_fs, luks_uuid, disk_device, swap_luks


def run():
    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")

    if not root_mount_point:
        root_mount_point = "/tmp/calamares-root"

    partitions = libcalamares.globalstorage.value("partitions")

    if not partitions:
        return ("No partitions found", "Partition information not available")

    uefi = is_uefi()
    if uefi:
        # Calamares' mount module mounts root + subvolumes but not the ESP.
        # Without mounting it here, LimineInstaller writes directories
        # into BTRFS at /boot/efi instead of the ESP partition.
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
    else:
        libcalamares.utils.debug("BIOS boot detected — skipping ESP detection/mount")

    root_uuid, root_fs, luks_uuid, disk_device, swap_luks = _scan_partitions(partitions)

    if not root_uuid:
        return ("Missing root UUID", "Could not determine root partition UUID")

    # The kernel cmdline this module renders hardcodes the btrfs @
    # subvolume layout, and ShedOS's snapshot/rollback stack requires
    # it; a manually-partitioned ext4/xfs root would kernel-panic on
    # first boot and silently lack the entire safety net.
    if root_fs and root_fs not in ("btrfs", "luks", "luks2"):
        return (
            "Unsupported root filesystem",
            f"ShedOS requires a btrfs root (snapshots and rollback "
            f"depend on it); the selected root partition is {root_fs}. "
            f"Re-partition with btrfs as the root filesystem.",
        )

    libcalamares.utils.debug(f"Root UUID: {root_uuid}")
    libcalamares.utils.debug(f"Disk device: {disk_device}")
    libcalamares.utils.debug(f"LUKS UUID: {luks_uuid}")
    libcalamares.utils.debug(f"UEFI mode: {uefi}")

    gpus = get_gpus()
    has_nvidia = any(gpu.is_nvidia for gpu in gpus)
    # Pre-Turing cards can't run the open kernel modules (the only
    # NVIDIA driver in the repos since 590 dropped Maxwell/Pascal);
    # installing it would ship a driver that refuses to bind the GPU.
    # Those systems boot on nouveau/modesetting and shedos_nvidia
    # leaves a note explaining the AUR legacy path.
    install_nvidia = should_install_nvidia(gpus)

    libcalamares.utils.debug(f"NVIDIA detected: {has_nvidia}")
    libcalamares.utils.debug(f"Install NVIDIA drivers: {install_nvidia}")

    swap_luks_uuid, swap_luks_mapper = swap_luks if swap_luks else (None, None)
    limine = LimineInstaller(
        mount_point=root_mount_point,
        root_uuid=root_uuid,
        luks_uuid=luks_uuid,
        nvidia=install_nvidia,
        swap_luks_uuid=swap_luks_uuid,
        swap_luks_mapper=swap_luks_mapper,
    )

    if not limine.install(disk_device or ""):
        return ("Bootloader installation failed",
                limine.last_error or "Failed to install Limine bootloader")

    libcalamares.utils.debug("Limine bootloader installed")

    # Must precede mkinitcpio: sd-vconsole bakes vconsole.conf into the
    # initramfs, so a console-less keymap fails Virtual Console Setup on
    # every boot even after the on-disk file is corrected.
    try:
        if sanitize_keymap(root_mount_point):
            libcalamares.utils.debug(
                "replaced a console-less KEYMAP with us in vconsole.conf"
            )
    except OSError as exc:
        libcalamares.utils.warning(f"cannot sanitize vconsole.conf: {exc}")

    if not limine.configure_mkinitcpio():
        return ("mkinitcpio configuration failed", "Failed to configure mkinitcpio")

    libcalamares.utils.debug("mkinitcpio configured and initramfs regenerated")

    return None
