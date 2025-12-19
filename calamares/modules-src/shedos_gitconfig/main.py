#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ShedOS Git Configuration Module
# Configures git with user information collected during installation
#

import os
import subprocess
import libcalamares
from libcalamares.utils import target_env_call, check_target_env_call

def pretty_name():
    return "Configuring git for developer workflow"

def run():
    """Configure git with user information."""

    # Get user info from global storage
    gs = libcalamares.globalstorage

    # Get user info from users module
    username = gs.value("username")
    fullname = gs.value("fullName")

    if not username:
        libcalamares.utils.warning("No username found in global storage")
        return None

    if not fullname:
        fullname = username

    # Email will be set by user after installation via welcome script
    email = None

    libcalamares.utils.debug(f"Configuring git for: {fullname}")

    root_mount = gs.value("rootMountPoint")
    if not root_mount:
        libcalamares.utils.warning("No root mount point found")
        return None

    # Path to user's home directory in the installed system
    user_home = os.path.join(root_mount, "home", username)
    gitconfig_path = os.path.join(user_home, ".gitconfig")

    libcalamares.utils.debug(f"Configuring git for user: {username}")
    libcalamares.utils.debug(f"Full name: {fullname}")
    libcalamares.utils.debug(f"Email: {email}")

    # Create .gitconfig content
    # Email will be added on first login
    gitconfig_content = f"""# ShedOS Git Configuration
# Generated during installation

[user]
    name = {fullname}
    # Set your email: git config --global user.email "your@email.com"

[init]
    defaultBranch = main

[core]
    editor = nvim
    autocrlf = input

[color]
    ui = auto

[pull]
    rebase = false

[push]
    default = current
    autoSetupRemote = true

[alias]
    st = status
    co = checkout
    br = branch
    ci = commit
    lg = log --oneline --graph --decorate
    last = log -1 HEAD
    unstage = reset HEAD --
"""


    try:
        # Write the gitconfig file
        with open(gitconfig_path, 'w') as f:
            f.write(gitconfig_content)

        # Set correct ownership (will be fixed by users module, but let's be safe)
        # We need to get the UID/GID that will be assigned to the user
        # For now, we'll set it to be owned by the user using chown in chroot

        libcalamares.utils.debug(f"Git config written to {gitconfig_path}")

        # Fix ownership using chroot
        check_target_env_call(['chown', f'{username}:{username}', f'/home/{username}/.gitconfig'])

        libcalamares.utils.debug("Git configuration complete")

    except Exception as e:
        libcalamares.utils.warning(f"Failed to configure git: {str(e)}")
        # Non-fatal error, continue with installation
        return None

    return None
