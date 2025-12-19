#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS Finalization Module for Calamares

Final installation steps:
- Enable systemd services
- Configure git for the user
- Perform cleanup tasks
"""

import sys
from pathlib import Path

import libcalamares

# Add shedos_installer to Python path
INSTALLER_ROOT = Path("/opt/shedos-installer")
sys.path.insert(0, str(INSTALLER_ROOT))

from shedos_installer.utils.command import run_chroot, run_command


# Base services enabled for all profiles
BASE_SERVICES = [
    "NetworkManager.service",
    "bluetooth.service",
    "greetd.service",
    "fstrim.timer",
]

# Additional services for developer/full profiles
DEVELOPER_SERVICES = [
    "postgresql.service",
    "redis.service",
]


def pretty_name():
    """Return the display name for this module."""
    return "Finalizing ShedOS installation"


def run():
    """
    Main entry point for the module.

    Enables services, configures git, and performs final cleanup.
    """
    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")
    if not root_mount_point:
        root_mount_point = "/tmp/calamares-root"

    root_mount = Path(root_mount_point)

    # Get user information
    username = libcalamares.globalstorage.value("username")
    fullname = libcalamares.globalstorage.value("fullname") or username

    # Detect profile from netinstall package selection
    packages = libcalamares.globalstorage.value("netinstallPackages") or []
    has_desktop = "hyprland" in packages or "waybar" in packages
    has_docker = "docker" in packages

    profile = "full" if (has_desktop and has_docker) else ("desktop" if has_desktop else "base")

    libcalamares.utils.debug(f"Finalizing installation for user: {username}")
    libcalamares.utils.debug(f"Detected profile: {profile} (packages: {len(packages)} items)")

    # Determine which services to enable
    services_to_enable = BASE_SERVICES.copy()

    if profile in ["developer", "full"]:
        services_to_enable.extend(DEVELOPER_SERVICES)

    # Enable services
    enabled_count = 0
    for service in services_to_enable:
        result = run_chroot(
            ["systemctl", "enable", service],
            mount_point=root_mount_point
        )

        if result.success:
            libcalamares.utils.debug(f"Enabled: {service}")
            enabled_count += 1
        else:
            # Some services might not be installed, that's okay
            libcalamares.utils.debug(f"Could not enable {service} (may not be installed)")

    libcalamares.utils.debug(f"Enabled {enabled_count} services")

    # Configure git for user
    if username and fullname:
        # Git configuration commands to run as the user
        git_configs = [
            f'git config --global user.name "{fullname}"',
            'git config --global init.defaultBranch "main"',
            'git config --global core.editor "nvim"',
            'git config --global pull.rebase "false"',
        ]

        for cmd in git_configs:
            result = run_command([
                "arch-chroot", root_mount_point,
                "su", "-", username, "-c", cmd
            ])

            if result.success:
                libcalamares.utils.debug(f"Git configured: {cmd.split('--global ')[1] if '--global' in cmd else cmd}")

        libcalamares.utils.debug(f"Git configured for {username}")

    # Configure greetd for desktop profiles
    if has_desktop:
        greetd_config_path = root_mount / "etc" / "greetd" / "config.toml"
        greetd_config = """[terminal]
vt = 1

[default_session]
# TUI greeter with Hyprland as default
command = "tuigreet --time --remember --remember-session --cmd Hyprland"
user = "greeter"
"""
        try:
            greetd_config_path.parent.mkdir(parents=True, exist_ok=True)
            greetd_config_path.write_text(greetd_config)

            # Create greeter user for greetd
            run_chroot(
                ["useradd", "-M", "-G", "video", "-s", "/usr/bin/nologin", "greeter"],
                mount_point=root_mount_point
            )
            # Lock the greeter account
            run_chroot(
                ["passwd", "-l", "greeter"],
                mount_point=root_mount_point
            )

            libcalamares.utils.debug("Greetd configured for Hyprland with greeter user")
        except Exception as e:
            libcalamares.utils.warning(f"Could not configure greetd: {e}")

    # Sync filesystems
    run_command(["sync"])

    # Final message
    libcalamares.utils.debug("ShedOS installation finalized successfully")

    return None  # Success
