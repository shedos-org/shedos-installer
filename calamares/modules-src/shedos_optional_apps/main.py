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

    selected = _read_netinstall_selections()
    if not selected:
        libcalamares.utils.debug("shedos_optional_apps: nothing selected")
        return None

    libcalamares.utils.debug(f"shedos_optional_apps: selected {selected}")
    _run_yay(root, selected)
    return None


# Optional apps the netinstall screen offers. Filter the netinstall
# globalstorage payload down to this set so we never accidentally
# pacman-install something pacstrap already handled via shedos-meta,
# nor a non-AUR package via the AUR helper path below.
_ALLOWED_OPTIONAL = frozenset({
    "google-chrome",
    "postman-bin",
    "claude-code-bin",
    "jetbrains-toolbox",
})


def _read_netinstall_selections():
    gs = libcalamares.globalstorage
    selected = []
    for pkg in gs.value("packages") or []:
        if isinstance(pkg, str):
            selected.append(pkg)
    for op in gs.value("packageOperations") or []:
        if isinstance(op, dict) and op.get("operation") == "install":
            selected.extend(op.get("packages") or [])
    return [p for p in selected if p in _ALLOWED_OPTIONAL]


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
