"""Path constants for the Calamares custom modules."""

from pathlib import Path


# Live ISO layout. The Makefile copies the repo-root packages/ tree
# verbatim under INSTALLER_DIR; PACKAGE_DIR is the per-category subdir
# (audio.txt, nvidia.txt, …) that consumers like shedos_nvidia read.
INSTALLER_DIR = Path("/opt/shedos-installer")
PACKAGE_DIR = INSTALLER_DIR / "packages" / "official"
