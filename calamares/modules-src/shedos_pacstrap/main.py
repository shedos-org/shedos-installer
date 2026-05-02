#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Pacstrap shedOS to /target.

Inherits the live ISO's /etc/pacman.conf (which has [core], [extra],
[multilib], and [shedos]). shedos-meta's depends=() transitively
pulls every shedos-* + republished AUR + the kernel + firmware.
"""

import os
import subprocess

import libcalamares


PACSTRAP_LOG = "/var/log/calamares/pacstrap.log"


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

    # -c suppresses pacman's color codes so the captured log is grep-able.
    cmd = ["pacstrap", "-c", root, *packages]
    libcalamares.utils.debug(f"shedos_pacstrap: {' '.join(cmd)}")

    os.makedirs(os.path.dirname(PACSTRAP_LOG), exist_ok=True)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    # Persist the FULL combined output so a future failure report can
    # point at exact URLs / conflict pairs without re-running the
    # install. The error returned to the user is still a tail since
    # Calamares' UI can only show a few lines.
    with open(PACSTRAP_LOG, "w") as f:
        f.write(f"$ {' '.join(cmd)}\n")
        f.write("=== stdout ===\n")
        f.write(result.stdout or "")
        f.write("\n=== stderr ===\n")
        f.write(result.stderr or "")
        f.write(f"\nrc={result.returncode}\n")

    if result.returncode != 0:
        return (
            f"pacstrap failed (rc={result.returncode})",
            f"Full log: {PACSTRAP_LOG}\n\n" + (result.stderr or "")[-2000:],
        )

    libcalamares.utils.debug("shedos_pacstrap: complete")
    return None
