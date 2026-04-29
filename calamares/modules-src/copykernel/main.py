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


# Where mkarchiso copies kernel + initramfs files on the live ISO.
# install_dir=shedos, arch=x86_64 (from profiledef.sh).
_LIVE_BOOT_DIRS = (
    "/run/archiso/bootmnt/shedos/x86_64",
    "/run/archiso/bootmnt/shedos/boot/x86_64",
    "/run/archiso/bootmnt/shedos/boot",
    "/run/archiso/copytoram/shedos/x86_64",
)


def pretty_name():
    return "Copying kernel and initramfs..."


def _find_kernels():
    """Yield (pkgbase, kver, vmlinuz_src) for every installed kernel.

    Reads /usr/lib/modules/*/pkgbase — the canonical record each kernel
    package writes when installed (see mkinitcpio's pacman hook). This
    handles shedos-kernel, stock linux, or any other kernel package
    without hardcoded names.
    """
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
    """Locate initramfs-<pkgbase>[<suffix>].img on the live ISO."""
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
            # Failure to copy shedos-kernel is fatal (it's the default boot
            # entry). Failure to copy a non-default kernel is logged but
            # not fatal — mkinitcpio -P would error later anyway and the
            # installer fails clearly there.
            if pkgbase == "shedos-kernel":
                return (f"Failed to copy {pkgbase} kernel: {e}",
                        f"Source: {vmlinuz_src}, Destination: {vmlinuz_dst}")
            continue

        # Best-effort initramfs copy. mkinitcpio -P regenerates these
        # later, but keeping the live-ISO copy gives Limine a working
        # initramfs to load even if anything else in the install path
        # fails after this step.
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
