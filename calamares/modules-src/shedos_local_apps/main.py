#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import glob
import os
import shutil
import subprocess
from pathlib import Path

import libcalamares


HOST_AUR_DIR = "/shedos-payload/aur"


def pretty_name():
    return "Installing bundled developer apps..."


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    if not root:
        return ("No rootMountPoint", "")

    pkgs = sorted(glob.glob(f"{HOST_AUR_DIR}/*.pkg.tar.zst"))
    if not pkgs:
        libcalamares.utils.warning(
            f"shedos_local_apps: no .pkg.tar.zst at {HOST_AUR_DIR}; skipping"
        )
        return None

    target_cache = Path(root) / "var/cache/pacman/pkg"
    target_cache.mkdir(parents=True, exist_ok=True)
    in_target_paths = []
    for pkg in pkgs:
        dest = target_cache / os.path.basename(pkg)
        try:
            shutil.copy2(pkg, dest)
            in_target_paths.append(f"/var/cache/pacman/pkg/{os.path.basename(pkg)}")
        except Exception as exc:
            libcalamares.utils.warning(
                f"shedos_local_apps: could not stage {pkg}: {exc}"
            )

    if not in_target_paths:
        return None

    cmd = [
        "arch-chroot", root,
        "pacman", "-U", "--noconfirm", "--needed",
        *in_target_paths,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        libcalamares.utils.warning(
            f"shedos_local_apps: pacman -U rc={r.returncode}: "
            f"{(r.stderr or '').strip()[-1000:]}"
        )
    return None
