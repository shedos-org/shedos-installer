#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Install nvidia-open-dkms + companions in the target root and enable
nvidia-{suspend,hibernate,resume}.service so suspend works on first
boot. Skipped entirely when shedos_install_nvidia globalstorage key is
falsy."""

import sys
from pathlib import Path

import libcalamares

INSTALLER_ROOT = Path("/opt/shedos-installer")
sys.path.insert(0, str(INSTALLER_ROOT))

from shedos_installer.config import PACKAGE_DIR
from shedos_installer.utils.command import run_chroot
from shedos_installer.utils.hardware import get_gpus


def pretty_name():
    return "Configuring NVIDIA drivers"


def run():
    install_nvidia = libcalamares.globalstorage.value("shedos_install_nvidia")

    if not install_nvidia:
        libcalamares.utils.debug("NVIDIA installation check: shedos_install_nvidia is False/None")
        return None

    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")
    if not root_mount_point:
        root_mount_point = "/tmp/calamares-root"

    nvidia_packages = []
    nvidia_pkg_file = PACKAGE_DIR / "nvidia.txt"

    if nvidia_pkg_file.exists():
        content = nvidia_pkg_file.read_text()
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                nvidia_packages.append(line)
    else:
        nvidia_packages = [
            "nvidia-open-dkms",
            "nvidia-utils",
            "nvidia-settings",
            "egl-wayland",
            "libva-nvidia-driver",
        ]

    if not nvidia_packages:
        libcalamares.utils.warning("No NVIDIA packages found")
        return None

    libcalamares.utils.debug(f"Installing NVIDIA packages: {nvidia_packages}")

    result = run_chroot(
        ["pacman", "-S", "--noconfirm", "--needed"] + nvidia_packages,
        mount_point=root_mount_point,
        timeout=600,
    )

    if not result.success:
        # Non-fatal: user can `pacman -S` the failed packages post-install.
        libcalamares.utils.warning(f"NVIDIA package installation had issues: {result.stderr}")

    nvidia_services = [
        "nvidia-suspend.service",
        "nvidia-hibernate.service",
        "nvidia-resume.service",
    ]

    for service in nvidia_services:
        result = run_chroot(
            ["systemctl", "enable", service],
            mount_point=root_mount_point,
        )
        if result.success:
            libcalamares.utils.debug(f"Enabled {service}")
        else:
            libcalamares.utils.warning(f"Could not enable {service}")

    gpus = get_gpus()
    for gpu in gpus:
        if gpu.is_nvidia:
            libcalamares.utils.debug(f"NVIDIA GPU: {gpu.model}")
            if gpu.nvidia_series:
                libcalamares.utils.debug(f"Series: {gpu.nvidia_series}")

    libcalamares.utils.debug("NVIDIA driver configuration complete")

    return None
