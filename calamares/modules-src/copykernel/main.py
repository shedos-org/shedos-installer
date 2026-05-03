#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Copy each installed kernel's binary + initramfs from the live ISO to
the installed system. mkarchiso wipes /boot/* before squashfs (see
mkarchiso _cleanup_pacstrap_dir), so unpackfs alone gives us an empty
/boot. Walk /usr/lib/modules/*/pkgbase to find every kernel package
that's installed, copy each kernel to /boot/vmlinuz-<pkgbase>, and copy
matching initramfs files from the live ISO's bootmnt directory if
present (mkinitcpio -P will regenerate them later regardless)."""

import glob
import os
import shutil
import libcalamares


_LIVE_BOOT_DIRS = (
    "/run/archiso/bootmnt/shedos/x86_64",
    "/run/archiso/bootmnt/shedos/boot/x86_64",
    "/run/archiso/bootmnt/shedos/boot",
    "/run/archiso/copytoram/shedos/x86_64",
)


def pretty_name():
    return "Copying kernel and initramfs..."


def _find_kernels():
    for pkgbase_file in sorted(glob.glob("/usr/lib/modules/*/pkgbase")):
        modules_dir = os.path.dirname(pkgbase_file)
        kver = os.path.basename(modules_dir)
        try:
            pkgbase = open(pkgbase_file).read().strip()
        except OSError:
            continue
        if not pkgbase:
            continue
        vmlinuz = os.path.join(modules_dir, "vmlinuz")
        if not os.path.exists(vmlinuz):
            continue
        yield (pkgbase, kver, vmlinuz)


def _find_initramfs(pkgbase, suffix=""):
    name = f"initramfs-{pkgbase}{suffix}.img"
    for d in _LIVE_BOOT_DIRS:
        path = os.path.join(d, name)
        if os.path.exists(path):
            return path
    return None


def run():
    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")
    if not root_mount_point:
        return ("Failed to get root mount point",
                "Could not determine where the system is installed")

    boot_dir = os.path.join(root_mount_point, "boot")
    os.makedirs(boot_dir, exist_ok=True)

    kernels = list(_find_kernels())
    if not kernels:
        return ("No kernels found",
                "No /usr/lib/modules/*/pkgbase entries on the live ISO.")

    libcalamares.utils.debug(
        f"copykernel: found {len(kernels)} kernel(s): "
        + ", ".join(p for p, _, _ in kernels)
    )

    copied_any_kernel = False

    for pkgbase, kver, vmlinuz_src in kernels:
        vmlinuz_dst = os.path.join(boot_dir, f"vmlinuz-{pkgbase}")
        try:
            libcalamares.utils.debug(
                f"copykernel: copying {vmlinuz_src} -> {vmlinuz_dst}"
            )
            shutil.copy2(vmlinuz_src, vmlinuz_dst)
            copied_any_kernel = True
        except Exception as e:
            libcalamares.utils.warning(
                f"copykernel: failed to copy {pkgbase} kernel: {e}"
            )
            # shedos-kernel is the default boot entry — fatal if it can't be copied.
            if pkgbase == "shedos-kernel":
                return (f"Failed to copy {pkgbase} kernel: {e}",
                        f"Source: {vmlinuz_src}, Destination: {vmlinuz_dst}")
            continue

        for suffix in ("", "-fallback"):
            initramfs_src = _find_initramfs(pkgbase, suffix)
            if initramfs_src:
                initramfs_dst = os.path.join(
                    boot_dir, f"initramfs-{pkgbase}{suffix}.img"
                )
                try:
                    shutil.copy2(initramfs_src, initramfs_dst)
                    libcalamares.utils.debug(
                        f"copykernel: copied initramfs {initramfs_src} -> {initramfs_dst}"
                    )
                except Exception as e:
                    libcalamares.utils.warning(
                        f"copykernel: failed to copy {pkgbase}{suffix} initramfs: {e}"
                    )

    if not copied_any_kernel:
        return ("No kernel could be copied",
                "Every kernel copy attempt failed. /boot is empty.")

    return None
