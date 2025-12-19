#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS Plymouth Configuration Module for Calamares

Configures Plymouth boot splash screen with ShedOS theme.
"""

import sys
from pathlib import Path

import libcalamares

# Add shedos_installer to Python path
INSTALLER_ROOT = Path("/opt/shedos-installer")
sys.path.insert(0, str(INSTALLER_ROOT))

from shedos_installer.utils.command import run_chroot


def pretty_name():
    """Return the display name for this module."""
    return "Configuring Plymouth boot splash"


def run():
    """
    Main entry point for the module.

    Configures Plymouth to use ShedOS theme.
    """
    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")
    if not root_mount_point:
        root_mount_point = "/tmp/calamares-root"

    root_mount = Path(root_mount_point)

    libcalamares.utils.debug("Configuring Plymouth with ShedOS theme")

    try:
        # Check if shedos theme exists
        theme_path = root_mount / "usr" / "share" / "plymouth" / "themes" / "shedos" / "shedos.plymouth"

        if not theme_path.exists():
            libcalamares.utils.warning(f"Plymouth shedos theme not found at {theme_path}")
            libcalamares.utils.warning("Skipping Plymouth configuration")
            return None

        # Set Plymouth theme to shedos (without -R flag first)
        result = run_chroot(
            ["plymouth-set-default-theme", "shedos"],
            mount_point=root_mount_point
        )

        if result.success:
            libcalamares.utils.debug("Plymouth theme set to 'shedos'")

            # Regenerate initramfs separately to avoid conflicts
            libcalamares.utils.debug("Regenerating initramfs with Plymouth theme...")
            regen_result = run_chroot(
                ["mkinitcpio", "-P"],
                mount_point=root_mount_point
            )

            if regen_result.success:
                libcalamares.utils.debug("Initramfs regenerated successfully")
            else:
                libcalamares.utils.warning(f"Could not regenerate initramfs: {regen_result.stderr}")
        else:
            libcalamares.utils.warning(f"Failed to set Plymouth theme: {result.stderr}")
            # Non-fatal, continue installation

    except Exception as e:
        libcalamares.utils.warning(f"Exception during Plymouth configuration: {e}")
        # Non-fatal, continue installation

    return None  # Success
