#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Install user-picked optional apps after pacstrap.

All picker items are AUR proprietaries (not republished to [shedos]),
so install via yay-in-chroot as the new user. Failures are logged as
warnings but never abort the install — user can re-run via
`shedman install <pkg>` post-boot.
"""

import shlex
import subprocess

import libcalamares


def pretty_name():
    return "Installing optional apps..."


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    if not root:
        return ("No rootMountPoint", "")

    raw = libcalamares.globalstorage.value("packagechooser_apps") or ""
    selected = [p.strip() for p in raw.split(",") if p.strip()]
    if not selected:
        libcalamares.utils.debug("shedos_optional_apps: nothing selected")
        return None

    libcalamares.utils.debug(f"shedos_optional_apps: selected {selected}")
    _run_yay(root, selected)
    return None


def _run_yay(root, pkgs):
    username = libcalamares.globalstorage.value("username")
    if not username:
        libcalamares.utils.warning(
            f"shedos_optional_apps: no username, skipping AUR: {pkgs}"
        )
        return

    yay_cmd = (
        "yay -S --needed --noconfirm "
        "--answerclean N --answerdiff N --answeredit N "
        "--cleanafter --removemake --mflags=--skippgpcheck "
        f"{shlex.join(pkgs)}"
    )
    cmd = ["arch-chroot", root, "sudo", "-u", username, "bash", "-c", yay_cmd]
    libcalamares.utils.debug(f"shedos_optional_apps: yay (as {username}): {yay_cmd}")
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        libcalamares.utils.warning(
            f"shedos_optional_apps: yay returned {r.returncode}; "
            f"stderr: {(r.stderr or '').strip()[-1000:]}"
        )
