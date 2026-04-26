#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ShedOS Configuration Deployment Module for Calamares

Deploys pre-configured dotfiles to the user's home directory.
"""

import os
import shutil
import subprocess
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

    # CONFIG_DIR is the legacy staging area under /opt/shedos-installer/configs,
    # populated by the Makefile from archiso/airootfs/etc/skel/. Since the
    # Phase-1 packaging rework, dotfiles reach the new user's home via
    # /etc/skel/ (shipped by the shedos-hyprland/shedos-nvim packages) and
    # useradd -m. The legacy copy is redundant but kept as a safety net if the
    # dir happens to exist. A missing CONFIG_DIR is NOT an error — we must
    # still run the manifest-seed step below.
    deployed_count = 0
    errors = []
    have_legacy_configs = CONFIG_DIR.exists()
    if have_legacy_configs:
        libcalamares.utils.debug(f"shedos_configs: Legacy config dir: {CONFIG_DIR}")
    else:
        libcalamares.utils.debug(
            f"shedos_configs: Legacy config dir not found ({CONFIG_DIR}); "
            "skipping legacy deployment (dotfiles come from /etc/skel)"
        )

    # Deploy all config directories
    for src_name, dest_rel in ALL_CONFIGS if have_legacy_configs else []:
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

    # Seed Oh My Zsh into the installed user's home.
    #
    # /etc/skel ships .zshrc which sources $ZSH/oh-my-zsh.sh where
    # $ZSH=$HOME/.oh-my-zsh. The oh-my-zsh-git package installs the framework
    # to /usr/share/oh-my-zsh — useradd -m does NOT copy anything from there.
    # Without this seed the user's first shell spawn errors with
    # "no such file or directory: $HOME/.oh-my-zsh/oh-my-zsh.sh".
    # Parallels the live-ISO copy in archiso/airootfs/root/customize_airootfs.sh.
    omz_src = root_mount / "usr/share/oh-my-zsh"
    omz_dest = user_home / ".oh-my-zsh"
    if omz_src.is_dir():
        try:
            if omz_dest.exists():
                shutil.rmtree(omz_dest)
            shutil.copytree(omz_src, omz_dest)

            # Symlink powerlevel10k into OMZ's custom-themes dir so .zshrc's
            # ZSH_THEME="powerlevel10k/powerlevel10k" resolves.
            p10k_src = Path("/usr/share/zsh-theme-powerlevel10k")
            p10k_link = omz_dest / "custom/themes/powerlevel10k"
            p10k_link.parent.mkdir(parents=True, exist_ok=True)
            if p10k_link.exists() or p10k_link.is_symlink():
                p10k_link.unlink()
            # Store the target as an absolute in-target path — symlinks
            # resolve relative to the booted system, not the live ISO.
            p10k_link.symlink_to(p10k_src)

            libcalamares.utils.debug(
                f"shedos_configs: Seeded oh-my-zsh + p10k for {username}"
            )
        except Exception as e:
            libcalamares.utils.warning(
                f"shedos_configs: Could not seed oh-my-zsh: {e}"
            )
    else:
        libcalamares.utils.warning(
            f"shedos_configs: {omz_src} missing — oh-my-zsh-git not installed? "
            f"User's .zshrc will fail on first shell spawn."
        )

    # Fix ownership of all deployed files
    libcalamares.utils.debug(f"shedos_configs: Fixing ownership for {username}")
    try:
        # subprocess.run with an argv list — never construct a shell
        # string from interpolated paths/usernames. A path containing
        # spaces (e.g. user mounts target on /mnt/SSD 2/) would break
        # the os.system() form silently.
        result = subprocess.run(
            [
                "arch-chroot", str(root_mount_point), "chown", "-R",
                f"{username}:{username}", f"/home/{username}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            libcalamares.utils.warning(
                f"shedos_configs: chown returned {result.returncode}: {result.stderr}"
            )
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

    # Seed shedos-sync-configs last-seen manifest.
    #
    # Puts the 3-way merge state machine into a valid initial state: each file
    # shipped under /usr/share/shedos/<pkg>/defaults/ by a ShedOS package gets
    # its sha256 recorded at ~/.local/state/shedos/last-seen/<relpath>.sha256
    # in the new user's home. Without this seed the first
    # `shedos-sync-configs` run after an upgrade would classify every managed
    # file as "user-modified" (last_sha unreadable → != dst_sha) and spray
    # .shedosnew everywhere (Case D in the sync algorithm).
    libcalamares.utils.debug("shedos_configs: Seeding shedos-sync-configs manifest")
    try:
        import hashlib

        shedos_defaults_root = root_mount / "usr/share/shedos"
        manifest_root = user_home / ".local/state/shedos/last-seen"

        # Exclusions mirrored from /usr/bin/shedos-sync-configs — runtime
        # state, not config.
        excludes = (
            ".config/nvim/lazy-lock.json",
            ".config/nvim/lazyvim.json",
        )

        seeded = 0
        if shedos_defaults_root.is_dir():
            for pkg_dir in shedos_defaults_root.iterdir():
                defaults_dir = pkg_dir / "defaults"
                if not defaults_dir.is_dir():
                    continue
                for src_file in defaults_dir.rglob("*"):
                    if not src_file.is_file():
                        continue
                    rel = src_file.relative_to(defaults_dir)
                    rel_str = str(rel)
                    if rel_str in excludes:
                        continue
                    sha = hashlib.sha256(src_file.read_bytes()).hexdigest()
                    manifest_path = manifest_root / f"{rel}.sha256"
                    manifest_path.parent.mkdir(parents=True, exist_ok=True)
                    manifest_path.write_text(sha + "\n")
                    seeded += 1

        libcalamares.utils.debug(
            f"shedos_configs: Seeded {seeded} manifest entries"
        )

        if manifest_root.exists():
            chown_res = subprocess.run(
                [
                    "arch-chroot", str(root_mount_point), "chown", "-R",
                    f"{username}:{username}", f"/home/{username}/.local",
                ],
                capture_output=True,
                text=True,
            )
            if chown_res.returncode != 0:
                libcalamares.utils.warning(
                    f"shedos_configs: chown of .local returned "
                    f"{chown_res.returncode}: {chown_res.stderr}"
                )
    except Exception as e:
        libcalamares.utils.warning(
            f"shedos_configs: Could not seed sync-configs manifest: {e}"
        )

    # Initialize Pacman DB (fix for missing core/extra db regression)
    # Running this during install guarantees the DB exists on first boot
    libcalamares.utils.debug("shedos_configs: Initializing pacman databases...")
    try:
        res = subprocess.run(
            ["arch-chroot", str(root_mount_point), "pacman", "-Sy", "--noconfirm"],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            libcalamares.utils.warning(
                f"shedos_configs: pacman -Sy returned {res.returncode}: {res.stderr}"
            )
        else:
            libcalamares.utils.debug("shedos_configs: Pacman DB initialized successfully")
    except Exception as e:
        libcalamares.utils.warning(f"shedos_configs: Failed to init pacman db: {e}")

    # Persist NetworkManager Connections (WiFi)
    # Calamares networkcfg module can be flaky, so we manually copy active connections
    # CRITICAL: In live session, secrets are often in keyring. We must force them to file first.
    libcalamares.utils.debug("shedos_configs: Persisting NetworkManager connections...")
    try:
        # 1. Find active WiFi connection UUIDs
        try:
            output = subprocess.check_output(
                ["nmcli", "-t", "-f", "UUID,TYPE,DEVICE",
                 "connection", "show", "--active"],
                text=True,
            ).strip()

            for line in output.split('\n'):
                if not line:
                    continue
                parts = line.split(':')
                if len(parts) >= 2 and parts[1] == "802-11-wireless":
                    uuid = parts[0]
                    libcalamares.utils.debug(f"shedos_configs: Found active WiFi UUID: {uuid}")

                    # 2. Force secrets to be stored in file (0) instead of keyring
                    # 3. Make connection available to all users (permissions="")
                    # 4. Save changes to disk immediately
                    # All argv-list (no shell) — UUIDs come from nmcli but
                    # using shell=True with f-string interpolation here
                    # would shell-inject if any value ever carried a shell
                    # metacharacter.
                    subprocess.run(
                        ["nmcli", "connection", "modify", uuid,
                         "802-11-wireless-security.psk-flags", "0"],
                        check=False,
                    )
                    subprocess.run(
                        ["nmcli", "connection", "modify", uuid,
                         "connection.permissions", ""],
                        check=False,
                    )
                    subprocess.run(
                        ["nmcli", "connection", "save", uuid],
                        check=False,
                    )
                    libcalamares.utils.debug(f"shedos_configs: Forced persistence for {uuid}")
        except Exception as nm_e:
            libcalamares.utils.warning(f"shedos_configs: Failed to prepare NM connections: {nm_e}")

        # 5. Copy the connection files
        source_connections = Path("/etc/NetworkManager/system-connections")
        target_connections = root_mount / "etc/NetworkManager/system-connections"

        nm_count = 0
        if not source_connections.exists() or not source_connections.is_dir():
            libcalamares.utils.warning(
                f"shedos_configs: {source_connections} missing on live ISO; "
                f"no NetworkManager profiles to persist"
            )
        else:
            nm_sources = sorted(p.name for p in source_connections.iterdir())
            libcalamares.utils.debug(
                f"shedos_configs: NM source listing: {nm_sources}"
            )
            if not nm_sources:
                libcalamares.utils.warning(
                    "shedos_configs: /etc/NetworkManager/system-connections is "
                    "empty — user may have joined wifi via iwd only (that's OK, "
                    "iwd profiles are copied separately below)"
                )
            target_connections.mkdir(parents=True, exist_ok=True)
            for conn_file in source_connections.iterdir():
                if conn_file.is_file() and not conn_file.name.endswith(".example"):
                    dest = target_connections / conn_file.name
                    shutil.copy2(conn_file, dest)
                    os.chmod(dest, 0o600)
                    nm_count += 1
            if nm_count > 0:
                libcalamares.utils.debug(
                    f"shedos_configs: Copied {nm_count} NM connection profiles"
                )
                chown_res = subprocess.run(
                    ["chown", "-R", "root:root", str(target_connections)],
                    capture_output=True,
                    text=True,
                )
                if chown_res.returncode != 0:
                    libcalamares.utils.warning(
                        f"shedos_configs: chown of NM target returned "
                        f"{chown_res.returncode}: {chown_res.stderr}"
                    )
            nm_landed = sorted(p.name for p in target_connections.iterdir())
            libcalamares.utils.debug(
                f"shedos_configs: NM target listing: {nm_landed}"
            )

        # 6. Also persist iwd profiles. The waybar network icon launches impala
        # (an iwd TUI), so most users connect via iwd — whose profiles live in
        # /var/lib/iwd/*.psk, NOT in NetworkManager's dir. Without this copy,
        # wifi credentials entered during install are lost on reboot.
        source_iwd = Path("/var/lib/iwd")
        target_iwd = root_mount / "var/lib/iwd"
        iwd_count = 0
        if not source_iwd.exists() or not source_iwd.is_dir():
            libcalamares.utils.warning(
                f"shedos_configs: {source_iwd} missing on live ISO; "
                f"no iwd profiles to persist"
            )
        else:
            try:
                iwd_sources = sorted(p.name for p in source_iwd.iterdir())
                libcalamares.utils.debug(
                    f"shedos_configs: iwd source listing: {iwd_sources}"
                )
            except PermissionError as pe:
                libcalamares.utils.warning(
                    f"shedos_configs: Cannot read /var/lib/iwd (need root): {pe}"
                )
                iwd_sources = []
            target_iwd.mkdir(parents=True, exist_ok=True)
            try:
                for psk_file in source_iwd.iterdir():
                    if psk_file.is_file() and psk_file.suffix in (".psk", ".open", ".8021x"):
                        dest = target_iwd / psk_file.name
                        shutil.copy2(psk_file, dest)
                        os.chmod(dest, 0o600)
                        iwd_count += 1
            except PermissionError as pe:
                libcalamares.utils.warning(
                    f"shedos_configs: Cannot read /var/lib/iwd (need root): {pe}"
                )
            if iwd_count > 0:
                libcalamares.utils.debug(
                    f"shedos_configs: Copied {iwd_count} iwd profiles"
                )
                os.chmod(target_iwd, 0o700)
                iwd_chown = subprocess.run(
                    ["chown", "-R", "root:root", str(target_iwd)],
                    capture_output=True,
                    text=True,
                )
                if iwd_chown.returncode != 0:
                    libcalamares.utils.warning(
                        f"shedos_configs: chown of iwd target returned "
                        f"{iwd_chown.returncode}: {iwd_chown.stderr}"
                    )
            if target_iwd.exists():
                iwd_landed = sorted(p.name for p in target_iwd.iterdir())
                libcalamares.utils.debug(
                    f"shedos_configs: iwd target listing: {iwd_landed}"
                )

        # 7. Bold warning if both sources came up empty — the user will have
        # to re-enter wifi on first boot. This is the symptom we're trying to
        # catch loud, not silent.
        if nm_count == 0 and iwd_count == 0:
            libcalamares.utils.warning(
                "shedos_configs: WiFi profiles NOT persisted — user will have "
                "to re-enter wifi password on first boot. Both "
                "/etc/NetworkManager/system-connections and /var/lib/iwd were "
                "empty or unreadable on the live ISO."
            )

        # 8. Make NetworkManager use iwd as its WiFi backend in the installed
        # system. Both services are enabled (shedos_finalize SERVICES list) and
        # without this config they fight over the WiFi device. With iwd as the
        # backend, NM presents iwd's stored profiles as its own on boot.
        nm_conf_d = root_mount / "etc/NetworkManager/conf.d"
        nm_conf_d.mkdir(parents=True, exist_ok=True)
        (nm_conf_d / "wifi_backend.conf").write_text(
            "# shedOS: route NetworkManager WiFi through iwd (see /var/lib/iwd/)\n"
            "[device]\n"
            "wifi.backend=iwd\n"
        )
        libcalamares.utils.debug("shedos_configs: Wrote NM wifi_backend.conf (iwd)")

        # 9. Ship the live-ISO psk-flags=0 NM drop-in to the installed system
        # too. Without this, any wifi joined for the FIRST time AFTER install
        # reverts to agent-owned secrets (stored in the user's login keyring
        # only) and won't auto-connect on a cold boot.
        nm_defaults_src = Path(
            "/etc/NetworkManager/conf.d/20-connection-defaults.conf"
        )
        nm_defaults_dst = nm_conf_d / "20-connection-defaults.conf"
        if nm_defaults_src.exists():
            shutil.copy2(nm_defaults_src, nm_defaults_dst)
            libcalamares.utils.debug(
                f"shedos_configs: Copied {nm_defaults_src.name} to target"
            )
        else:
            libcalamares.utils.warning(
                f"shedos_configs: {nm_defaults_src} missing on live ISO; "
                f"new wifi connections on the installed system won't persist"
            )
    except Exception as e:
        libcalamares.utils.warning(f"shedos_configs: Failed to persist wifi profiles: {e}")

    libcalamares.utils.debug(f"shedos_configs: Deployed {deployed_count} configurations")

    if errors:
        # Log errors but don't fail the install
        libcalamares.utils.warning(f"shedos_configs: Completed with {len(errors)} errors")

    return None  # Success
