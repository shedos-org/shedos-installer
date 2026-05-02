#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Pacstrap shedOS to /target.

Inherits the live ISO's /etc/pacman.conf ([core], [extra], [multilib],
[shedos]); shedos-meta pulls every shedos-* + republished AUR + the
kernel + firmware. Output streams line-by-line so the Calamares
progress UI doesn't freeze during the ~30 min install; on failure we
return both the head and the tail of captured output (early errors
land near the head, resolver conflicts near the tail).
"""

import os
import subprocess
from collections import deque

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

# Operational backstop for virtual-provider conflicts. shedos-meta's
# rendered conflicts=() is the primary defense; pacstrap forwards
# --ignore through to pacman as a second layer in case a future render
# forgets an entry. Keep this list in sync with shedos_conflicts in
# scripts/render-meta-depends.sh.
IGNORE_PROVIDERS = [
    "jack2",
    "iptables-legacy",
    "booster",
    "dracut",
    "jdk21-openjdk",
    "jdk25-openjdk",
    "qt6-multimedia-gstreamer",
    "pipewire-media-session",
    "gnu-free-fonts",
    "ttf-bitstream-vera",
    "ttf-croscore",
    "ttf-droid",
    "ttf-ibm-plex",
    "ttf-input",
    "ttf-input-nerd",
    "ttf-roboto",
]


def pretty_name():
    return "Installing shedOS to disk..."


def _stream_pacstrap(cmd, log_path):
    """Run pacstrap, tee output to log_path AND libcalamares.utils.debug,
    return (returncode, head, tail) for failure-message construction."""
    head: list[str] = []
    tail: deque[str] = deque(maxlen=30)
    HEAD_LIMIT = 30

    with open(log_path, "w") as logf:
        logf.write(f"$ {' '.join(cmd)}\n")
        logf.flush()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            logf.write(line)
            logf.flush()
            stripped = line.rstrip("\n")
            if stripped:
                libcalamares.utils.debug(f"pacstrap: {stripped}")
            if len(head) < HEAD_LIMIT:
                head.append(stripped)
            tail.append(stripped)
        rc = proc.wait()
        logf.write(f"\nrc={rc}\n")
    return rc, head, list(tail)


def run():
    root = libcalamares.globalstorage.value("rootMountPoint")
    if not root:
        return ("No root mount point", "")

    packages = list(BASE_PACKAGES)
    if libcalamares.globalstorage.value("shedos_install_nvidia"):
        packages.extend(NVIDIA_PACKAGES)

    # -c uses the host package cache; --ignore= passes through to pacman.
    ignore = ",".join(IGNORE_PROVIDERS)
    cmd = ["pacstrap", "-c", root, *packages, f"--ignore={ignore}"]
    libcalamares.utils.debug(f"shedos_pacstrap: {' '.join(cmd)}")

    os.makedirs(os.path.dirname(PACSTRAP_LOG), exist_ok=True)
    rc, head, tail = _stream_pacstrap(cmd, PACSTRAP_LOG)

    if rc != 0:
        head_block = "\n".join(head) if head else "(no head captured)"
        tail_block = "\n".join(tail) if tail else "(no tail captured)"
        msg = (
            f"Full log: {PACSTRAP_LOG}\n\n"
            f"--- first {len(head)} lines ---\n{head_block}\n\n"
            f"--- last {len(tail)} lines ---\n{tail_block}"
        )
        return (f"pacstrap failed (rc={rc})", msg)

    libcalamares.utils.debug("shedos_pacstrap: complete")
    return None
