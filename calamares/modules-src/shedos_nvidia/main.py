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
from shedos_installer.utils.hardware import get_gpus, nvidia_open_supported


def pretty_name():
    return "Configuring NVIDIA drivers"


def _note_legacy_gpu():
    """When an NVIDIA card is present but unsupported by the open
    modules, leave a note explaining the nouveau fallback and the AUR
    legacy-branch path. Silent when there's no NVIDIA hardware."""
    gpus = get_gpus()
    legacy = [g for g in gpus if g.is_nvidia and not nvidia_open_supported(g)]
    if not legacy:
        return
    root_mount_point = libcalamares.globalstorage.value("rootMountPoint") \
        or "/tmp/calamares-root"
    try:
        note = Path(root_mount_point) / "etc/shedos/nvidia-legacy-gpu"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            "This machine's NVIDIA GPU predates Turing; the open kernel\n"
            "modules (the only NVIDIA driver in the repos since 590)\n"
            "cannot drive it. The desktop runs on nouveau/modesetting.\n"
            "For the proprietary legacy branch, see the AUR package\n"
            "nvidia-580xx-dkms and https://wiki.archlinux.org/title/NVIDIA\n"
            + "".join(f"GPU: {g.model}\n" for g in legacy)
        )
        libcalamares.utils.warning(
            f"NVIDIA GPU unsupported by open modules; note written to {note}"
        )
    except Exception as exc:
        libcalamares.utils.warning(f"Could not write legacy-GPU note: {exc}")


def run():
    install_nvidia = libcalamares.globalstorage.value("shedos_install_nvidia")

    if not install_nvidia:
        libcalamares.utils.debug("NVIDIA installation check: shedos_install_nvidia is False/None")
        _note_legacy_gpu()
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
        libcalamares.utils.debug(
            f"Read {len(nvidia_packages)} NVIDIA packages from {nvidia_pkg_file}"
        )
    else:
        nvidia_packages = [
            "nvidia-open-dkms",
            "nvidia-utils",
            "nvidia-settings",
            "egl-wayland",
            "libva-nvidia-driver",
        ]
        libcalamares.utils.warning(
            f"NVIDIA package list missing at {nvidia_pkg_file}; using fallback"
        )

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
        # Non-fatal — the installed system still boots via modesetting.
        # Persist a sentinel so first-boot tooling can prompt the user
        # to retry instead of silently shipping a broken NVIDIA stack.
        libcalamares.utils.warning(
            "NVIDIA driver install FAILED — manual repair needed:\n"
            f"  Re-run on first boot: pacman -S {' '.join(nvidia_packages)}\n"
            f"  Stderr tail: {(result.stderr or '')[-500:]}"
        )
        try:
            sentinel = Path(root_mount_point) / "etc/shedos/nvidia-install-failed"
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text("\n".join(nvidia_packages) + "\n")
        except Exception as exc:
            libcalamares.utils.warning(
                f"Could not write NVIDIA failure sentinel: {exc}"
            )

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
