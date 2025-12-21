#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# ShedOS Git Configuration Module
# Configures git with user information collected during installation
#

import os
import libcalamares
from libcalamares.utils import check_target_env_call

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

    libcalamares.utils.debug(f"Configuring git for: {fullname}")

    root_mount = gs.value("rootMountPoint")
    if not root_mount:
        libcalamares.utils.warning("No root mount point found")
        return None

    # Path to user's home directory in the installed system
    user_home = os.path.join(root_mount, "home", username)
    gitconfig_path = os.path.join(user_home, ".gitconfig")

    # Email will be configured by user on first login
    gitconfig_content = f"""# ShedOS Git Configuration
# Generated during installation
# Set your email: git config --global user.email "your@email.com"

[user]
    name = {fullname}

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
        # Ensure home directory exists
        os.makedirs(user_home, exist_ok=True)
        
        # Write the gitconfig file
        with open(gitconfig_path, 'w') as f:
            f.write(gitconfig_content)

        libcalamares.utils.debug(f"Git config written to {gitconfig_path}")

        # Fix ownership using chroot
        check_target_env_call(['chown', f'{username}:{username}', f'/home/{username}/.gitconfig'])

        libcalamares.utils.debug("Git configuration complete")

    except Exception as e:
        libcalamares.utils.warning(f"Failed to configure git: {str(e)}")
        return None

    return None
