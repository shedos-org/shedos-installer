#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Install user-picked optional apps after pacstrap.

pacman handles official + [shedos] sources; yay-in-chroot (as the new
user) handles AUR proprietaries that aren't republished. Failures are
logged as warnings but never abort the install — user can re-run via
`shedman install <pkg>` post-boot.
"""

import shlex
import subprocess

import libcalamares


# Packages sourced from pacman repos (official + [shedos]).
# Everything else is treated as AUR and installed via yay.
PACMAN_SOURCED = {"code"}


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

    pacman_pkgs = [p for p in selected if p in PACMAN_SOURCED]
    aur_pkgs = [p for p in selected if p not in PACMAN_SOURCED]

    if pacman_pkgs:
        _run_pacman(root, pacman_pkgs)
    if aur_pkgs:
        _run_yay(root, aur_pkgs)

    return None


def _run_pacman(root, pkgs):
    cmd = ["arch-chroot", root, "pacman", "-S", "--needed", "--noconfirm", *pkgs]
    libcalamares.utils.debug(f"shedos_optional_apps: pacman: {shlex.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        libcalamares.utils.warning(
            f"shedos_optional_apps: pacman returned {r.returncode}; "
            f"stderr: {(r.stderr or '').strip()[-1000:]}"
        )


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
