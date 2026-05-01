#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Pacstrap shedOS to /target.

Inherits the live ISO's /etc/pacman.conf (which has [core], [extra],
[multilib], and [shedos]). shedos-meta's depends=() transitively
pulls every shedos-* + republished AUR + the kernel + firmware.
"""

import subprocess

import libcalamares


BASE_PACKAGES = [
    "base",
    "base-devel",
    "shedos-keyring",
    "shedos-meta",
]

NVIDIA_PACKAGES = [
    "nvidia-open-dkms",
    "nvidia-utils",
    "egl-wayland",
    "libva-nvidia-driver",
]


def pretty_name():
    return "Installing shedOS to disk..."


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    if not root:
        return ("No root mount point", "")

    packages = list(BASE_PACKAGES)
    if libcalamares.globalstorage.value("shedos_install_nvidia"):
        packages.extend(NVIDIA_PACKAGES)

    cmd = ["pacstrap", root, *packages]
    libcalamares.utils.debug(f"shedos_pacstrap: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return (
            f"pacstrap failed (rc={result.returncode})",
            (result.stderr or "")[-2000:],
        )

    libcalamares.utils.debug("shedos_pacstrap: complete")
    return None
