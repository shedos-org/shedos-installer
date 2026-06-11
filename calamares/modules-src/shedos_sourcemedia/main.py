#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Resolve the live medium's airootfs.sfs to a stable path for unpackfs.

unpackfs.conf needs a static source path, but the squashfs lives in
two different places depending on how the ISO was booted: under
/run/archiso/bootmnt on an ordinary boot, or /run/archiso/copytoram
when copytoram=y moved the image to RAM (at which point the boot
medium may be gone entirely). Symlink whichever exists to
/run/shedos/airootfs.sfs — the path unpackfs.conf points at."""

import os
import libcalamares

_CANDIDATES = (
    "/run/archiso/copytoram/airootfs.sfs",
    "/run/archiso/bootmnt/shedos/x86_64/airootfs.sfs",
)

_LINK = "/run/shedos/airootfs.sfs"


def pretty_name():
    return "Locating the installation image..."


def run():
    for candidate in _CANDIDATES:
        if os.path.isfile(candidate):
            os.makedirs(os.path.dirname(_LINK), exist_ok=True)
            if os.path.lexists(_LINK):
                os.unlink(_LINK)
            os.symlink(candidate, _LINK)
            libcalamares.utils.debug(
                f"shedos_sourcemedia: {_LINK} -> {candidate}"
            )
            return None
    return (
        "Installation image not found",
        "airootfs.sfs is missing from both the boot medium and the "
        "copytoram location; the live environment looks broken.",
    )
