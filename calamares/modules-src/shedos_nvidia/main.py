#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS NVIDIA Driver Module for Calamares

Handles NVIDIA GPU detection and proprietary driver installation.
Installs nvidia-dkms and related packages, and enables NVIDIA
systemd services for proper suspend/hibernate support.
"""

import sys
from pathlib import Path

import libcalamares

# Add shedos_installer to Python path
# The installer package is at /opt/shedos-installer/ in the live ISO
INSTALLER_ROOT = Path("/opt/shedos-installer")
sys.path.insert(0, str(INSTALLER_ROOT))

from shedos_installer.config import PACKAGE_DIR
from shedos_installer.utils.command import run_chroot
from shedos_installer.utils.hardware import get_gpus


def pretty_name():
    """Return the display name for this module."""
    return "Configuring NVIDIA drivers"


def run():
    """
    Main entry point for the module.

    Installs NVIDIA drivers if an NVIDIA GPU was detected and
    the user's profile supports it.
    """
    # Check if NVIDIA installation is needed
    install_nvidia = libcalamares.globalstorage.value("shedos_install_nvidia")

    if not install_nvidia:
        libcalamares.utils.debug("NVIDIA installation not requested, skipping")
        return None

    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")
    if not root_mount_point:
        root_mount_point = "/tmp/calamares-root"

    # Read NVIDIA packages from package list
    nvidia_packages = []
    nvidia_pkg_file = PACKAGE_DIR / "nvidia.txt"

    if nvidia_pkg_file.exists():
        content = nvidia_pkg_file.read_text()
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                nvidia_packages.append(line)
    else:
        # Fallback to essential NVIDIA packages
        nvidia_packages = [
            "nvidia-dkms",
            "nvidia-utils",
            "nvidia-settings",
            "egl-wayland",
            "libva-nvidia-driver",
        ]

    if not nvidia_packages:
        libcalamares.utils.warning("No NVIDIA packages found")
        return None

    libcalamares.utils.debug(f"Installing NVIDIA packages: {nvidia_packages}")

    # Install NVIDIA packages
    result = run_chroot(
        ["pacman", "-S", "--noconfirm", "--needed"] + nvidia_packages,
        mount_point=root_mount_point,
        timeout=600  # 10 minute timeout
    )

    if not result.success:
        libcalamares.utils.warning(f"NVIDIA package installation had issues: {result.stderr}")
        # Don't fail the installation - user can fix later

    # Enable NVIDIA systemd services for proper power management
    nvidia_services = [
        "nvidia-suspend.service",
        "nvidia-hibernate.service",
        "nvidia-resume.service",
    ]

    for service in nvidia_services:
        result = run_chroot(
            ["systemctl", "enable", service],
            mount_point=root_mount_point
        )
        if result.success:
            libcalamares.utils.debug(f"Enabled {service}")
        else:
            libcalamares.utils.warning(f"Could not enable {service}")

    # Log GPU information
    gpus = get_gpus()
    for gpu in gpus:
        if gpu.is_nvidia:
            libcalamares.utils.debug(f"NVIDIA GPU: {gpu.model}")
            if gpu.nvidia_series:
                libcalamares.utils.debug(f"Series: {gpu.nvidia_series}")

    libcalamares.utils.debug("NVIDIA driver configuration complete")

    return None  # Success
