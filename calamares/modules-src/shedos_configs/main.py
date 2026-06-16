#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Deploy pre-configured dotfiles to the new user's home. Most dotfiles
now reach the user via /etc/skel; this module handles the residual
legacy /opt/shedos-installer/configs path, the oh-my-zsh seed, and
the shedos-sync-configs manifest. WiFi-profile persistence lives in
shedos_finalize, not here."""

import os
import shutil
import subprocess
from pathlib import Path

import libcalamares


CONFIG_DIR = Path("/opt/shedos-installer/configs")
BRANDING_DIR = Path("/opt/shedos-installer/branding")

# (source_dirname, destination_relative_to_home)
ALL_CONFIGS = [
    ("hyprland", ".config/hypr"),
    ("hypridle", ".config/hypr"),

    ("waybar", ".config/waybar"),
    ("walker", ".config/walker"),
    ("kitty", ".config/kitty"),
    ("mako", ".config/mako"),
    ("rofi", ".config/rofi"),
    ("fastfetch", ".config/fastfetch"),

    ("starship", ".config"),
    ("tmux", ""),

    ("nvim", ".config/nvim"),
    ("git", ".config/git"),
    ("mise", ".config/mise"),
    ("vscode", ".config/Code/User"),
]

# zsh files go directly to ~/, not under .config/.
ZSH_FILES = [".zshrc", ".zprofile", ".p10k.zsh"]


def pretty_name():
    return "Deploying ShedOS configurations"


def _deploy_dir(src, dest):
    """Copy src→dest without blindly rmtree-ing a home dir. useradd -m seeds
    these paths from /etc/skel, so move any existing dest aside as a transient
    rollback, copy, then drop the backup on success (restore it on failure)."""
    bak = None
    if dest.exists() or dest.is_symlink():
        bak = dest.with_name(dest.name + ".shedos-bak")
        if bak.exists() or bak.is_symlink():
            shutil.rmtree(bak)
        os.replace(dest, bak)
    try:
        shutil.copytree(src, dest)
    except Exception:
        if bak is not None:
            if dest.exists():
                shutil.rmtree(dest)
            os.replace(bak, dest)
        raise
    if bak is not None:
        shutil.rmtree(bak)


def run():
    libcalamares.utils.debug("shedos_configs: Starting configuration deployment")

    root_mount_point = libcalamares.globalstorage.value("rootMountPoint")
    if not root_mount_point:
        libcalamares.utils.warning("shedos_configs: No rootMountPoint found")
        return ("No root mount point found.", "")

    root_mount = Path(root_mount_point)
    libcalamares.utils.debug(f"shedos_configs: Root mount point: {root_mount}")

    username = libcalamares.globalstorage.value("username")
    if not username:
        libcalamares.utils.warning("shedos_configs: No username found, skipping")
        return None

    user_home = root_mount / "home" / username
    libcalamares.utils.debug(f"shedos_configs: User home: {user_home}")

    if not user_home.exists():
        libcalamares.utils.warning(f"shedos_configs: User home not found: {user_home}")
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

    for src_name, dest_rel in ALL_CONFIGS if have_legacy_configs else []:
        src_path = CONFIG_DIR / src_name

        if not src_path.exists():
            libcalamares.utils.debug(f"shedos_configs: Skipping (not found): {src_name}")
            continue

        if dest_rel:
            dest_path = user_home / dest_rel
        else:
            dest_path = user_home

        libcalamares.utils.debug(f"shedos_configs: Deploying {src_name} -> {dest_path}")

        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            if src_path.is_dir():
                dest_path.mkdir(parents=True, exist_ok=True)
                for item in src_path.iterdir():
                    item_dest = dest_path / item.name
                    if item.is_dir():
                        _deploy_dir(item, item_dest)
                    else:
                        shutil.copy2(item, item_dest)
                libcalamares.utils.debug(f"shedos_configs: Copied dir contents: {src_name}")
            else:
                shutil.copy2(src_path, dest_path)
                libcalamares.utils.debug(f"shedos_configs: Copied file: {src_name}")

            deployed_count += 1

        except Exception as e:
            error_msg = f"Failed to deploy {src_name}: {e}"
            libcalamares.utils.warning(f"shedos_configs: {error_msg}")
            errors.append(error_msg)
            continue

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
        for item in zsh_dir.iterdir():
            if item.name not in ZSH_FILES:
                try:
                    dest_file = user_home / item.name
                    if item.is_file():
                        shutil.copy2(item, dest_file)
                    else:
                        _deploy_dir(item, dest_file)
                    libcalamares.utils.debug(f"shedos_configs: Copied zsh/{item.name}")
                except Exception as e:
                    libcalamares.utils.warning(f"shedos_configs: Failed to copy zsh/{item.name}: {e}")

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
            _deploy_dir(omz_src, omz_dest)

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

    libcalamares.utils.debug(f"shedos_configs: Fixing ownership for {username}")
    try:
        # argv-list, never shell=True with f-string interpolation —
        # a path with spaces (e.g. /mnt/SSD 2/) would break the shell form.
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

    hyprland_conf = user_home / ".config" / "hypr" / "hyprland.conf"
    if hyprland_conf.exists():
        libcalamares.utils.debug(f"shedos_configs: Verified hyprland.conf exists: {hyprland_conf}")
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

    # Initialize the pacman DB now so /var/lib/pacman/sync/{core,extra}.db
    # exists on first boot. Otherwise the user's first `pacman -S` call
    # has to do an offline-style init that has previously regressed.
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

    libcalamares.utils.debug(f"shedos_configs: Deployed {deployed_count} configurations")

    if errors:
        libcalamares.utils.warning(f"shedos_configs: Completed with {len(errors)} errors")

    return None
