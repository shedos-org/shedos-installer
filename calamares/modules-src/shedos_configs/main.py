#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS Configuration Deployment Module for Calamares

Deploys pre-configured dotfiles to the user's home directory.
"""

import os
import shutil
from pathlib import Path

import libcalamares


# Hardcoded paths - don't rely on imports that may fail
CONFIG_DIR = Path("/opt/shedos-installer/configs")
BRANDING_DIR = Path("/opt/shedos-installer/branding")

# Configuration mappings - all configs to be deployed
# Format: (source_dirname, destination_relative_to_home)
ALL_CONFIGS = [
    # Desktop environment - all go to .config/hypr
    ("hyprland", ".config/hypr"),
    ("hypridle", ".config/hypr"),
    ("hyprlock", ".config/hypr"),

    # Other desktop apps
    ("waybar", ".config/waybar"),
    ("walker", ".config/walker"),
    ("kitty", ".config/kitty"),
    ("mako", ".config/mako"),
    ("rofi", ".config/rofi"),
    ("fastfetch", ".config/fastfetch"),

    # Shell and terminal
    ("starship", ".config"),
    ("tmux", ""),

    # Development tools
    ("nvim", ".config/nvim"),
    ("git", ".config/git"),
    ("mise", ".config/mise"),
    ("vscode", ".config/Code/User"),
]

# Files from zsh directory need special handling - they go directly to home
ZSH_FILES = [".zshrc", ".zprofile", ".p10k.zsh"]


def pretty_name():
    """Return the display name for this module."""
    return "Deploying ShedOS configurations"


def run():
    """
    Main entry point for the module.
    Copies pre-configured dotfiles to the new user's home directory.
    """
    libcalamares.utils.debug("shedos_configs: Starting configuration deployment")

    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")
    if not root_mount_point:
        libcalamares.utils.warning("shedos_configs: No rootMountPoint found")
        return ("No root mount point found.", "")

    root_mount = Path(root_mount_point)
    libcalamares.utils.debug(f"shedos_configs: Root mount point: {root_mount}")

    # Get username from global storage
    username = libcalamares.globalstorage.value("username")
    if not username:
        libcalamares.utils.warning("shedos_configs: No username found, skipping")
        return None  # Not an error, just nothing to do

    user_home = root_mount / "home" / username
    libcalamares.utils.debug(f"shedos_configs: User home: {user_home}")

    # Ensure home directory exists
    if not user_home.exists():
        libcalamares.utils.warning(f"shedos_configs: User home not found: {user_home}")
        # Try to create it
        try:
            user_home.mkdir(parents=True, exist_ok=True)
            libcalamares.utils.debug(f"shedos_configs: Created user home: {user_home}")
        except Exception as e:
            return (f"Could not create user home: {e}", "")

    # Check if CONFIG_DIR exists
    if not CONFIG_DIR.exists():
        libcalamares.utils.warning(f"shedos_configs: Config dir not found: {CONFIG_DIR}")
        return (f"Config directory not found: {CONFIG_DIR}", "")

    libcalamares.utils.debug(f"shedos_configs: Config dir found: {CONFIG_DIR}")
    libcalamares.utils.debug(f"shedos_configs: Contents: {list(CONFIG_DIR.iterdir())}")

    deployed_count = 0
    errors = []

    # Deploy all config directories
    for src_name, dest_rel in ALL_CONFIGS:
        src_path = CONFIG_DIR / src_name

        if not src_path.exists():
            libcalamares.utils.debug(f"shedos_configs: Skipping (not found): {src_name}")
            continue

        # Determine destination path
        if dest_rel:
            dest_path = user_home / dest_rel
        else:
            dest_path = user_home

        libcalamares.utils.debug(f"shedos_configs: Deploying {src_name} -> {dest_path}")

        try:
            # Ensure parent directory exists
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            if src_path.is_dir():
                # For directories, ensure dest exists for merging
                dest_path.mkdir(parents=True, exist_ok=True)
                # Copy all files from source to dest
                for item in src_path.iterdir():
                    item_dest = dest_path / item.name
                    if item.is_dir():
                        if item_dest.exists():
                            shutil.rmtree(item_dest)
                        shutil.copytree(item, item_dest)
                    else:
                        shutil.copy2(item, item_dest)
                libcalamares.utils.debug(f"shedos_configs: Copied dir contents: {src_name}")
            else:
                # Copy single file
                shutil.copy2(src_path, dest_path)
                libcalamares.utils.debug(f"shedos_configs: Copied file: {src_name}")

            deployed_count += 1

        except Exception as e:
            error_msg = f"Failed to deploy {src_name}: {e}"
            libcalamares.utils.warning(f"shedos_configs: {error_msg}")
            errors.append(error_msg)
            continue

    # Deploy zsh files (special handling - files go directly to home)
    zsh_dir = CONFIG_DIR / "zsh"
    if zsh_dir.exists():
        for filename in ZSH_FILES:
            src_file = zsh_dir / filename
            if src_file.exists():
                try:
                    dest_file = user_home / filename
                    shutil.copy2(src_file, dest_file)
                    libcalamares.utils.debug(f"shedos_configs: Copied {filename} to home")
                    deployed_count += 1
                except Exception as e:
                    libcalamares.utils.warning(f"shedos_configs: Failed to copy {filename}: {e}")
        # Also copy any other files in zsh directory
        for item in zsh_dir.iterdir():
            if item.name not in ZSH_FILES:
                try:
                    dest_file = user_home / item.name
                    if item.is_file():
                        shutil.copy2(item, dest_file)
                    else:
                        if dest_file.exists():
                            shutil.rmtree(dest_file)
                        shutil.copytree(item, dest_file)
                    libcalamares.utils.debug(f"shedos_configs: Copied zsh/{item.name}")
                except Exception as e:
                    libcalamares.utils.warning(f"shedos_configs: Failed to copy zsh/{item.name}: {e}")

    # Deploy wallpaper
    wallpaper_src = BRANDING_DIR / "wallpapers" / "shedos-default.png"
    if wallpaper_src.exists():
        try:
            hypr_dir = user_home / ".config" / "hypr"
            hypr_dir.mkdir(parents=True, exist_ok=True)
            wallpaper_dest = hypr_dir / "wallpaper.png"
            shutil.copy2(wallpaper_src, wallpaper_dest)
            libcalamares.utils.debug("shedos_configs: Wallpaper deployed")
        except Exception as e:
            libcalamares.utils.warning(f"shedos_configs: Could not deploy wallpaper: {e}")
    else:
        libcalamares.utils.debug(f"shedos_configs: Wallpaper not found: {wallpaper_src}")

    # Fix ownership of all deployed files
    libcalamares.utils.debug(f"shedos_configs: Fixing ownership for {username}")
    try:
        # Use os.system for simplicity in chroot context
        chroot_cmd = f"arch-chroot {root_mount_point} chown -R {username}:{username} /home/{username}"
        result = os.system(chroot_cmd)
        if result != 0:
            libcalamares.utils.warning(f"shedos_configs: chown command returned {result}")
    except Exception as e:
        libcalamares.utils.warning(f"shedos_configs: Could not fix ownership: {e}")

    # Verify deployment
    hyprland_conf = user_home / ".config" / "hypr" / "hyprland.conf"
    if hyprland_conf.exists():
        libcalamares.utils.debug(f"shedos_configs: Verified hyprland.conf exists: {hyprland_conf}")
        
        # Add hyprlock to startup for installed systems (login screen experience)
        # This makes hyprlock launch immediately when Hyprland starts
        try:
            content = hyprland_conf.read_text()
            # Add exec-once = hyprlock at the start of the startup section
            if "exec-once = hyprlock" not in content:
                # Insert after the "Startup Applications" comment section
                marker = "# Startup Applications"
                if marker in content:
                    # Find the line after the header separator
                    lines = content.split("\n")
                    for i, line in enumerate(lines):
                        if marker in line and i + 2 < len(lines):
                            # Insert after the separator line (usually "# ────...")
                            insert_index = i + 2
                            lines.insert(insert_index, "exec-once = hyprlock  # Login screen on startup")
                            content = "\n".join(lines)
                            break
                    hyprland_conf.write_text(content)
                    libcalamares.utils.debug("shedos_configs: Added hyprlock to startup for login screen")
        except Exception as e:
            libcalamares.utils.warning(f"shedos_configs: Could not add hyprlock to startup: {e}")
    else:
        libcalamares.utils.warning(f"shedos_configs: WARNING: hyprland.conf NOT found after deployment!")
        errors.append("hyprland.conf not found after deployment")

    libcalamares.utils.debug(f"shedos_configs: Deployed {deployed_count} configurations")

    if errors:
        # Log errors but don't fail the install
        libcalamares.utils.warning(f"shedos_configs: Completed with {len(errors)} errors")

    return None  # Success
