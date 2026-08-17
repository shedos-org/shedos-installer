#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Post-skel touches to the new user's home: the default wallpaper,
ownership, and the shedos-sync-configs manifest. Dotfiles themselves
reach the user via /etc/skel. WiFi-profile persistence lives in
shedos_finalize, not here."""

import os
import shutil
import subprocess
from pathlib import Path

import libcalamares


# shedos-branding ships the wallpaper; the ISO build used to copy it in
# beside the installer, which is why this used to name /opt.
WALLPAPER = Path("/usr/share/shedos/wallpapers/shedos-default.png")


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

    errors = []

    if WALLPAPER.exists():
        try:
            hypr_dir = user_home / ".config" / "hypr"
            hypr_dir.mkdir(parents=True, exist_ok=True)
            wallpaper_dest = hypr_dir / "wallpaper.png"
            shutil.copy2(WALLPAPER, wallpaper_dest)
            libcalamares.utils.debug("shedos_configs: Wallpaper deployed")
        except Exception as e:
            libcalamares.utils.warning(f"shedos_configs: Could not deploy wallpaper: {e}")
    else:
        libcalamares.utils.debug(f"shedos_configs: Wallpaper not found: {WALLPAPER}")

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

    if errors:
        libcalamares.utils.warning(f"shedos_configs: Completed with {len(errors)} errors")

    return None
