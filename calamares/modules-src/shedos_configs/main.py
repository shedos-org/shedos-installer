#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS Configuration Deployment Module for Calamares

Deploys pre-configured dotfiles to the user's home directory.
Includes configurations for:
- Hyprland (Wayland compositor)
- Waybar (status bar)
- Walker (application launcher)
- Kitty (terminal emulator)
- Mako (notification daemon)
- Neovim (text editor)
- Zsh (shell)
"""

import shutil
import sys
from pathlib import Path

import libcalamares

# Add shedos_installer to Python path
# The installer package is at /opt/shedos-installer/ in the live ISO
INSTALLER_ROOT = Path("/opt/shedos-installer")
sys.path.insert(0, str(INSTALLER_ROOT))

from shedos_installer.config import CONFIG_DIR
from shedos_installer.utils.command import run_chroot


# Configuration mappings by profile
# All profiles get base configs (nvim, zsh)
# Desktop profiles (desktop/developer/full) get desktop environment configs

BASE_CONFIGS = [
    ("nvim", ".config/nvim"),
    ("zsh", ""),  # .zshrc, .zprofile go to home directly
]

DESKTOP_CONFIGS = [
    ("hyprland", ".config/hypr"),
    ("waybar", ".config/waybar"),
    ("walker", ".config/walker"),
    ("kitty", ".config/kitty"),
    ("mako", ".config/mako"),
    ("hypridle", ".config/hypr"),
    ("hyprlock", ".config/hypr"),
]


def pretty_name():
    """Return the display name for this module."""
    return "Deploying ShedOS configurations"


def run():
    """
    Main entry point for the module.

    Copies pre-configured dotfiles to the new user's home directory.
    """
    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")
    if not root_mount_point:
        root_mount_point = "/tmp/calamares-root"

    root_mount = Path(root_mount_point)

    # Get username from global storage
    username = libcalamares.globalstorage.value("username")

    if not username:
        libcalamares.utils.warning("No username found, skipping config deployment")
        return None

    user_home = root_mount / "home" / username

    # Ensure home directory exists
    if not user_home.exists():
        libcalamares.utils.warning(f"User home directory not found: {user_home}")
        return None

    libcalamares.utils.debug(f"Deploying configs to {user_home}")

    # Detect profile from netinstall package selection
    # If hyprland is selected, it's a desktop profile
    packages = libcalamares.globalstorage.value("netinstallPackages") or []
    has_desktop = "hyprland" in packages or "waybar" in packages

    profile = "desktop" if has_desktop else "base"
    libcalamares.utils.debug(f"Detected profile: {profile} (hyprland in packages: {has_desktop})")

    # Determine which configs to deploy based on profile
    configs_to_deploy = BASE_CONFIGS.copy()

    if has_desktop:
        configs_to_deploy.extend(DESKTOP_CONFIGS)
        libcalamares.utils.debug("Including desktop environment configs")

    # Check if CONFIG_DIR exists
    if not CONFIG_DIR.exists():
        libcalamares.utils.warning(f"Config directory not found: {CONFIG_DIR}")
        return None

    deployed_count = 0

    for src_name, dest_rel in configs_to_deploy:
        src_path = CONFIG_DIR / src_name

        if not src_path.exists():
            libcalamares.utils.debug(f"Config source not found, skipping: {src_name}")
            continue

        # Determine destination path
        if dest_rel:
            dest_path = user_home / dest_rel
        else:
            dest_path = user_home

        # Ensure parent directory exists
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if src_path.is_dir():
                # Copy entire directory
                if dest_path.exists() and dest_path.is_dir():
                    # Merge with existing directory
                    libcalamares.utils.debug(f"Merging directory: {src_path} -> {dest_path}")
                    shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
                else:
                    libcalamares.utils.debug(f"Copying directory: {src_path} -> {dest_path}")
                    shutil.copytree(src_path, dest_path)
            else:
                # Copy single file
                libcalamares.utils.debug(f"Copying file: {src_path} -> {dest_path}")
                shutil.copy2(src_path, dest_path)

            deployed_count += 1
            libcalamares.utils.debug(f"Successfully deployed: {src_name}")

        except Exception as e:
            libcalamares.utils.warning(f"Failed to deploy {src_name}: {e}")
            # Continue to next config instead of crashing
            continue

    # Deploy wallpaper for desktop profiles
    if has_desktop:
        wallpaper_src = CONFIG_DIR.parent / "branding" / "wallpapers" / "shedos-default.png"
        if wallpaper_src.exists():
            try:
                wallpaper_dest = user_home / ".config" / "hypr" / "wallpaper.png"
                wallpaper_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(wallpaper_src, wallpaper_dest)
                libcalamares.utils.debug("Wallpaper deployed successfully")
            except Exception as e:
                libcalamares.utils.warning(f"Could not deploy wallpaper: {e}")

    # Deploy first-login script for git email setup
    first_login_script = CONFIG_DIR.parent / "system" / "shedos-first-login.sh"
    if first_login_script.exists():
        try:
            # Copy script to user's local bin
            local_bin = user_home / ".local" / "bin"
            local_bin.mkdir(parents=True, exist_ok=True)

            script_dest = local_bin / "shedos-first-login"
            shutil.copy2(first_login_script, script_dest)
            script_dest.chmod(0o755)

            # Add to .zshrc to run on first login
            zshrc_path = user_home / ".zshrc"
            zshrc_addition = "\n# ShedOS first-login setup (git email)\n~/.local/bin/shedos-first-login\n"

            if zshrc_path.exists():
                with open(zshrc_path, 'a') as f:
                    f.write(zshrc_addition)
            else:
                zshrc_path.write_text(zshrc_addition)

            libcalamares.utils.debug("First-login script deployed")
        except Exception as e:
            libcalamares.utils.warning(f"Could not deploy first-login script: {e}")

    # Fix ownership of all deployed files
    if deployed_count > 0:
        result = run_chroot(
            ["chown", "-R", f"{username}:{username}", f"/home/{username}"],
            mount_point=root_mount_point
        )

        if not result.success:
            libcalamares.utils.warning(f"Could not fix ownership: {result.stderr}")

    libcalamares.utils.debug(f"Deployed {deployed_count} configurations")

    return None  # Success
