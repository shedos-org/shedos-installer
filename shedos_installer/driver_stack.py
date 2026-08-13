"""The NVIDIA package set, read from the file shedos-system publishes."""

from __future__ import annotations

import os
from pathlib import Path

# The same file /usr/lib/shedos/nvidia-reap reads, under the same override, so
# the list of packages a machine with no NVIDIA card gets stripped of exists
# once and both readers see the same thirteen names.
STACK_FILE = "/usr/share/shedos/nvidia-driver-stack"


def driver_stack() -> list[str]:
    """The stack in file order.

    Missing, unreadable or empty is an error rather than an empty list: a
    caller that installs nothing leaves an NVIDIA box on modesetting, and one
    that removes nothing leaves the whole stack on a machine that has no
    NVIDIA card at all. Both are silent, and both survive to the installed
    system.
    """
    path = Path(os.environ.get("SHEDOS_NVIDIA_STACK_FILE", STACK_FILE))
    packages = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not packages:
        raise OSError(f"{path} names no packages")
    return packages
