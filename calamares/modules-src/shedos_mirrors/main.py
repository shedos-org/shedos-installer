#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Refresh /etc/pacman.d/mirrorlist mid-install.

The boot-time shedos-mirrorlist.service runs once when the live ISO
comes up. If the user sat at Calamares' welcome screen for a while
(or the live env was suspended), the mirrorlist may be stale.

Both this module and the systemd unit exec /usr/lib/shedos/
refresh-mirrorlist.sh, the single source of truth for ShedOS's
reflector flag set. Tune the flags there.

Non-fatal on failure. The boot-time list is at worst stale, not
absent.
"""

import subprocess
import libcalamares


REFLECTOR_SCRIPT = "/usr/lib/shedos/refresh-mirrorlist.sh"


def pretty_name():
    return "Refreshing mirror list..."


def run():
    libcalamares.utils.debug(f"shedos_mirrors: exec {REFLECTOR_SCRIPT}")
    r = subprocess.run(
        [REFLECTOR_SCRIPT],
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
