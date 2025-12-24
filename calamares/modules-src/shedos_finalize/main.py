#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS Finalization Module for Calamares

Final installation steps:
- Configure greetd for auto-login (hyprlock handles authentication)
- Clean up live ISO-specific files (motd, shedos-live.sh, issue)
- Initialize pacman keyring for the installed system
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
    "iwd.service",
    # "greetd.service",  # Removed: User wants SDDM
    "sddm.service",      # Added: User wants SDDM enabled explicitly
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

    # Clean up live ISO-specific files that shouldn't be in the installed system
    live_iso_files = [
        root_mount / "etc" / "profile.d" / "shedos-live.sh",
        root_mount / "etc" / "motd",
    ]

    for file_path in live_iso_files:
        try:
            if file_path.exists():
                file_path.unlink()
                libcalamares.utils.debug(f"shedos_finalize: Removed live ISO file {file_path}")
        except Exception as e:
            libcalamares.utils.warning(f"shedos_finalize: Could not remove {file_path}: {e}")

    # Replace /etc/issue with a simpler version for the installed system
    issue_path = root_mount / "etc" / "issue"
    issue_content = """
shedOS
Kernel: \\r on \\m
TTY: \\l

"""
    try:
        issue_path.write_text(issue_content)
        libcalamares.utils.debug("shedos_finalize: Updated /etc/issue for installed system")
    except Exception as e:
        libcalamares.utils.warning(f"shedos_finalize: Could not update /etc/issue: {e}")

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

    # CRITICAL: Initialize pacman keyring for the installed system
    # Without this, users cannot install packages after installation
    libcalamares.utils.debug("shedos_finalize: Setting up pacman and keyring")
    
    # First sync package databases
    result = os.system(f"arch-chroot {root_mount_point} pacman -Sy --noconfirm 2>/dev/null")
    if result == 0:
        libcalamares.utils.debug("shedos_finalize: pacman -Sy succeeded")
    else:
        libcalamares.utils.warning(f"shedos_finalize: pacman -Sy failed with code {result}")
    
    # Initialize keyring
    keyring_cmds = [
        "pacman-key --init",
        "pacman-key --populate archlinux",
    ]
    for kcmd in keyring_cmds:
        result = os.system(f"arch-chroot {root_mount_point} {kcmd} 2>/dev/null")
        if result == 0:
            libcalamares.utils.debug(f"shedos_finalize: {kcmd} succeeded")
        else:
            libcalamares.utils.warning(f"shedos_finalize: {kcmd} failed with code {result}")

    # Install required font packages
    libcalamares.utils.debug("shedos_finalize: Installing font packages")
    font_packages = ["ttf-font-awesome", "ttf-nerd-fonts-symbols"]
    result = os.system(f"arch-chroot {root_mount_point} pacman -S --noconfirm {' '.join(font_packages)} 2>/dev/null")
    if result == 0:
        libcalamares.utils.debug("shedos_finalize: Font packages installed")
    else:
        libcalamares.utils.warning(f"shedos_finalize: Font package installation failed with code {result}")
    
    # Update font cache
    result = os.system(f"arch-chroot {root_mount_point} fc-cache -fv 2>/dev/null")
    if result == 0:
        libcalamares.utils.debug("shedos_finalize: Font cache updated")
    else:
        libcalamares.utils.warning(f"shedos_finalize: Font cache update failed with code {result}")

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

    # Create standard XDG user directories (Desktop, Documents, Downloads, etc.)
    if username:
        libcalamares.utils.debug(f"shedos_finalize: Creating XDG user directories for {username}")
        result = os.system(f"arch-chroot {root_mount_point} su - {username} -c 'xdg-user-dirs-update' 2>/dev/null")
        if result == 0:
            libcalamares.utils.debug("shedos_finalize: XDG user directories created")
        else:
            libcalamares.utils.warning(f"shedos_finalize: xdg-user-dirs-update failed with code {result}")

        # Create user 'projects' and 'work' directories (Request: specific settings in finalize)
        for user_dir in ["projects", "work"]:
            dir_path = root_mount / "home" / username / user_dir
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                # Set ownership (uid:gid)
                # We need to find the uid/gid of the user in the chroot...
                # Simpler: run mkdir as the user via su
                os.system(f"arch-chroot {root_mount_point} su - {username} -c 'mkdir -p ~/{user_dir}'")
                libcalamares.utils.debug(f"shedos_finalize: Created ~/{user_dir}")
            except Exception as e:
                libcalamares.utils.warning(f"shedos_finalize: Could not create ~/{user_dir}: {e}")

    # Force SDDM Theme to Catppuccin
    # Calamares displaymanager module might have written defaults (breeze). We overwrite/ensure this.
    sddm_theme_config = """[Theme]
Current=catppuccin-mocha-mauve
"""
    sddm_config_dir = root_mount / "etc" / "sddm.conf.d"
    sddm_theme_path = sddm_config_dir / "theme.conf"
    
    try:
        sddm_config_dir.mkdir(parents=True, exist_ok=True)
        sddm_theme_path.write_text(sddm_theme_config)
        libcalamares.utils.debug("shedos_finalize: Enforced Catppuccin SDDM theme")
        
        # CLEANUP: Remove Live ISO Autologin Config
        live_autologin_path = sddm_config_dir / "live-session-autologin.conf"
        if live_autologin_path.exists():
            live_autologin_path.unlink()
            libcalamares.utils.debug("shedos_finalize: REMOVED live-session-autologin.conf")
        
        # CREATE: New User Autologin Config (Manual Fallback)
        # If displaymanager module failed to create it (or basicSetup=false prevented it), we do it here.
        new_autologin_path = sddm_config_dir / "autologin.conf"
        autologin_content = f"""[Autologin]
User={username}
Session=hyprland
Relogin=false
"""
        # Always write this to ensure the new user gets autologin
        new_autologin_path.write_text(autologin_content)
        libcalamares.utils.debug(f"shedos_finalize: CREATED autologin.conf for user {username}")

        # Remove any 'breeze' setting from other potential SDDM configs Calamares might have touched
        # E.g. /etc/sddm.conf or other files in .d
        for conf_file in sddm_config_dir.glob("*.conf"):
            if conf_file.name == "theme.conf":
                continue
            
            try:
                content = conf_file.read_text()
                if "Current=breeze" in content:
                    new_content = content.replace("Current=breeze", "Current=catppuccin-mocha-mauve")
                    conf_file.write_text(new_content)
                    libcalamares.utils.debug(f"shedos_finalize: Replaced breeze in {conf_file.name}")
            except Exception as e:
                libcalamares.utils.warning(f"shedos_finalize: Failed checking {conf_file}: {e}")

    except Exception as e:
        libcalamares.utils.warning(f"shedos_finalize: Could not configure SDDM theme/autologin: {e}")

    # Sync filesystems
    os.system("sync")

    libcalamares.utils.debug("shedos_finalize: Installation finalized successfully")
    return None  # Success
