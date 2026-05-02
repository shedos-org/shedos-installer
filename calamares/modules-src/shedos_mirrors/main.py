#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Refresh /etc/pacman.d/mirrorlist before pacstrap.

The boot-time shedos-mirrorlist.service runs once when the live ISO
comes up. If the user sat at Calamares' welcome screen for a while
(or the live env was suspended), the mirrorlist may be stale — slow
mirrors or ones that have rotated their content. Re-run reflector
with the same flags right before pacstrap reaches for them.

Non-fatal on failure. The boot-time list is at worst stale, not
absent.
"""

import subprocess
import libcalamares


REFLECTOR_ARGS = [
    "/usr/bin/reflector",
    "--save", "/etc/pacman.d/mirrorlist",
    "--sort", "rate",
    "--latest", "20",
    "--protocol", "https",
    "--age", "12",
    "--threads", "5",
]


def pretty_name():
    return "Refreshing mirror list..."


def run():
    libcalamares.utils.debug(
        "shedos_mirrors: " + " ".join(REFLECTOR_ARGS)
    )
    r = subprocess.run(
        REFLECTOR_ARGS,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if r.returncode != 0:
        libcalamares.utils.warning(
            f"reflector returned {r.returncode}; continuing with the "
            f"existing mirrorlist. stderr: "
            f"{(r.stderr or '').strip()[-500:]}"
        )
    return None
