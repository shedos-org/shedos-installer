#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS Finalization Module for Calamares

Final installation steps:
- Configure greetd for tuigreet login
- Enable systemd services
- Configure git for the user
"""

import os
from pathlib import Path

import libcalamares


# Services to enable
SERVICES = [
    "NetworkManager.service",
    "bluetooth.service",
    "greetd.service",
    "fstrim.timer",
]


def pretty_name():
    """Return the display name for this module."""
    return "Finalizing ShedOS installation"


def run():
    """Main entry point for the module."""
    libcalamares.utils.debug("shedos_finalize: Starting finalization")

    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")
    if not root_mount_point:
        libcalamares.utils.warning("shedos_finalize: No rootMountPoint found")
        return ("No root mount point found.", "")

    root_mount = Path(root_mount_point)
    libcalamares.utils.debug(f"shedos_finalize: Root mount: {root_mount}")

    # Get user information
    username = libcalamares.globalstorage.value("username")
    fullname = libcalamares.globalstorage.value("fullname") or username

    libcalamares.utils.debug(f"shedos_finalize: username={username}, fullname={fullname}")

    if not username:
        libcalamares.utils.warning("shedos_finalize: No username found")
        return None

    # CRITICAL: Configure greetd for tuigreet with Hyprland
    # This overrides the live ISO's auto-login config
    greetd_config = f"""[terminal]
vt = 1

[default_session]
# TUI greeter with Hyprland as default session
command = "tuigreet --time --remember --remember-session --cmd Hyprland"
user = "greeter"
"""
    greetd_config_path = root_mount / "etc" / "greetd" / "config.toml"

    try:
        greetd_config_path.parent.mkdir(parents=True, exist_ok=True)
        greetd_config_path.write_text(greetd_config)
        libcalamares.utils.debug("shedos_finalize: Wrote greetd config for tuigreet")

        # Create greeter user for greetd (if doesn't exist)
        os.system(f"arch-chroot {root_mount_point} useradd -M -G video -s /usr/bin/nologin greeter 2>/dev/null")
        os.system(f"arch-chroot {root_mount_point} passwd -l greeter 2>/dev/null")
        libcalamares.utils.debug("shedos_finalize: Created greeter user")

    except Exception as e:
        libcalamares.utils.warning(f"shedos_finalize: Could not configure greetd: {e}")

    # CRITICAL: Set zsh as default shell for the user
    # The Calamares users module's userShell setting may not always work
    libcalamares.utils.debug(f"shedos_finalize: Setting zsh as default shell for {username}")
    try:
        # Change user's shell to zsh
        result = os.system(f"arch-chroot {root_mount_point} chsh -s /usr/bin/zsh {username}")
        if result == 0:
            libcalamares.utils.debug(f"shedos_finalize: Set zsh as shell for {username}")
        else:
            libcalamares.utils.warning(f"shedos_finalize: chsh returned {result}")
        
        # Also ensure zsh is in /etc/shells
        shells_file = root_mount / "etc" / "shells"
        if shells_file.exists():
            shells_content = shells_file.read_text()
            if "/usr/bin/zsh" not in shells_content:
                with open(shells_file, "a") as f:
                    f.write("/usr/bin/zsh\n")
                libcalamares.utils.debug("shedos_finalize: Added /usr/bin/zsh to /etc/shells")
    except Exception as e:
        libcalamares.utils.warning(f"shedos_finalize: Could not set zsh shell: {e}")

    # Enable services
    enabled_count = 0
    for service in SERVICES:
        result = os.system(f"arch-chroot {root_mount_point} systemctl enable {service} 2>/dev/null")
        if result == 0:
            libcalamares.utils.debug(f"shedos_finalize: Enabled {service}")
            enabled_count += 1
        else:
            libcalamares.utils.debug(f"shedos_finalize: Could not enable {service}")

    libcalamares.utils.debug(f"shedos_finalize: Enabled {enabled_count} services")

    # Configure git for user
    if username and fullname:
        git_configs = [
            f'git config --global user.name "{fullname}"',
            'git config --global init.defaultBranch "main"',
            'git config --global core.editor "nvim"',
            'git config --global pull.rebase "false"',
        ]

        for cmd in git_configs:
            os.system(f"arch-chroot {root_mount_point} su - {username} -c '{cmd}' 2>/dev/null")

        libcalamares.utils.debug("shedos_finalize: Git configured")

    # Sync filesystems
    os.system("sync")

    libcalamares.utils.debug("shedos_finalize: Installation finalized successfully")
    return None  # Success
