#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Install the default-shipped proprietary developer apps via yay-in-chroot.

These vendor binaries cannot be republished under the shedOS signing
key (vendor EULAs forbid third-party redistribution). Running yay
inside the target chroot at install time is legally equivalent to the
user running `yay -S` themselves — vendor CDN → user's machine, never
through shedOS infrastructure. Failures here are non-fatal; the user
can retry post-boot via `shedman install`.
"""

import shlex
import subprocess

import libcalamares


DEFAULT_INSTALL = (
    "google-chrome",
    "postman-bin",
    "claude-code-bin",
    "jetbrains-toolbox",
)


def pretty_name():
    return "Installing default developer apps..."


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    if not root:
        return ("No rootMountPoint", "")

    username = libcalamares.globalstorage.value("username")
    if not username:
        libcalamares.utils.warning(
            f"shedos_optional_apps: no username in globalstorage, "
            f"skipping {list(DEFAULT_INSTALL)}"
        )
        return None

    if not _can_sudo_passwordless(root, username):
        return None

    libcalamares.utils.debug(
        f"shedos_optional_apps: default-installing {list(DEFAULT_INSTALL)}"
    )
    _run_yay(root, username, DEFAULT_INSTALL)
    return None


def _can_sudo_passwordless(root, username):
    """Probe whether <username> can sudo without a password inside the
    target. yay calls sudo internally with no TTY; without NOPASSWD the
    pacman invocation fails mid-build with a cryptic error. Surface the
    misconfiguration up-front instead.

    Returns True iff the probe succeeds. False is a non-fatal warning —
    the user can install the apps post-boot via shedman.
    """
    probe = ["arch-chroot", root, "sudo", "-u", username, "-n", "sudo", "-n", "true"]
    r = subprocess.run(probe, capture_output=True, text=True, check=False)
    if r.returncode == 0:
        return True

    libcalamares.utils.warning(
        f"shedos_optional_apps: {username} cannot sudo without a password "
        f"inside the target. Skipping yay-in-chroot — user can run "
        f"`shedman install` post-boot. Verify "
        f"/etc/sudoers.d/wheel exists and contains a NOPASSWD rule for "
        f"the wheel group, and that {username} is in wheel "
        f"(per Calamares users.conf defaultGroups). "
        f"sudo stderr: {(r.stderr or '').strip()[-300:]}"
    )
    return False


def _run_yay(root, username, pkgs):
    yay_cmd = (
        "yay -S --needed --noconfirm "
        "--answerclean N --answerdiff N --answeredit N "
        "--cleanafter --removemake --mflags=--skippgpcheck "
        f"{shlex.join(pkgs)}"
    )
    cmd = ["arch-chroot", root, "sudo", "-u", username, "bash", "-c", yay_cmd]
    libcalamares.utils.debug(
        f"shedos_optional_apps: yay (as {username}): {yay_cmd}"
    )
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        libcalamares.utils.warning(
            f"shedos_optional_apps: yay returned {r.returncode}; "
            f"the user can re-run via `shedman install` post-boot. "
            f"stderr: {(r.stderr or '').strip()[-1000:]}"
        )
