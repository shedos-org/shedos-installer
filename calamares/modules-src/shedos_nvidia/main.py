#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Install nvidia-open-dkms + companions in the target root and enable
nvidia-{suspend,hibernate,resume}.service so suspend works on first
boot. Skipped when no installed GPU is driveable by the open modules."""

import sys
from pathlib import Path

import libcalamares

INSTALLER_ROOT = Path("/opt/shedos-installer")
sys.path.insert(0, str(INSTALLER_ROOT))

from shedos_installer.utils.command import run_chroot
from shedos_installer.utils.hardware import (
    get_gpus,
    gpu_env_lines,
    nvidia_open_supported,
    should_install_nvidia,
)


def pretty_name():
    return "Configuring NVIDIA drivers"


# Kept in sync with nvidia-reap in shedos-system. Named in full because
# pacstrap installs everything as explicit, so -Rns never cascades.
DRIVER_STACK = [
    "nvidia-open-dkms",
    "nvidia-utils",
    "nvidia-settings",
    "nvidia-prime",
    "libva-nvidia-driver",
    "nvidia-container-toolkit",
    "libnvidia-container",
    "libxnvctrl",
    "egl-wayland",
    "egl-wayland2",
    "egl-gbm",
    "egl-x11",
    "eglexternalplatform",
]


def _remove_nvidia_stack(root_mount_point, keep_firmware):
    """The target is a clone of the live ISO, so the stack starts out
    present. keep_firmware: nouveau loads it on legacy nvidia cards."""
    candidates = DRIVER_STACK + ([] if keep_firmware else ["linux-firmware-nvidia"])
    installed = [
        p for p in candidates
        if run_chroot(["pacman", "-Qq", p], mount_point=root_mount_point).success
    ]
    if not installed:
        return
    result = run_chroot(
        ["pacman", "-Rns", "--noconfirm"] + installed,
        mount_point=root_mount_point,
        timeout=600,
    )
    if not result.success:
        libcalamares.utils.warning(
            "Could not remove the unused nvidia stack; leaving it installed:\n"
            f"  {(result.stderr or '')[-500:]}"
        )


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
    gpus = get_gpus()
    if not should_install_nvidia(gpus):
        libcalamares.utils.debug("No NVIDIA GPU the open modules can drive — skipping")
        _note_legacy_gpu()
        root_mount_point = libcalamares.globalstorage.value("rootMountPoint") \
            or "/tmp/calamares-root"
        _remove_nvidia_stack(
            root_mount_point,
            keep_firmware=any(g.is_nvidia for g in gpus),
        )
        return None

    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")
    if not root_mount_point:
        root_mount_point = "/tmp/calamares-root"

    # The stack rides the live clone, so this is a heal for a partial
    # clone rather than a fresh install; --needed makes it a no-op when
    # everything is already in place.
    nvidia_packages = DRIVER_STACK + ["linux-firmware-nvidia"]
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

    for gpu in gpus:
        if gpu.is_nvidia:
            libcalamares.utils.debug(f"NVIDIA GPU: {gpu.model}")
            if gpu.nvidia_series:
                libcalamares.utils.debug(f"Series: {gpu.nvidia_series}")

    # The session GPU env uwsm sources before Hyprland: on Optimus this keeps the
    # integrated GPU primary and offloads per-app via prime-run; on a pure nvidia
    # box it makes nvidia the render GPU. Empty topologies never reach here.
    env_lines = gpu_env_lines(gpus)
    if env_lines:
        try:
            uwsm_env = Path(root_mount_point) / "etc/uwsm/env"
            uwsm_env.parent.mkdir(parents=True, exist_ok=True)
            uwsm_env.write_text("\n".join(env_lines) + "\n")
            libcalamares.utils.debug(f"Wrote GPU env to {uwsm_env}")
        except Exception as exc:
            libcalamares.utils.warning(f"Could not write GPU env: {exc}")

    libcalamares.utils.debug("NVIDIA driver configuration complete")

    return None
