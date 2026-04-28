#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Seed the new user's ~/.gitconfig with ShedOS defaults. user.email is
left for the welcome script — we only have user.name (Calamares fullname)
to work with at install time."""

import os
import libcalamares
from libcalamares.utils import check_target_env_call

def pretty_name():
    return "Configuring git for developer workflow"

def run():
    gs = libcalamares.globalstorage

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

    user_home = os.path.join(root_mount, "home", username)
    gitconfig_path = os.path.join(user_home, ".gitconfig")

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
        os.makedirs(user_home, exist_ok=True)

        with open(gitconfig_path, 'w') as f:
            f.write(gitconfig_content)

        libcalamares.utils.debug(f"Git config written to {gitconfig_path}")

        check_target_env_call(['chown', f'{username}:{username}', f'/home/{username}/.gitconfig'])

        libcalamares.utils.debug("Git configuration complete")

    except Exception as e:
        libcalamares.utils.warning(f"Failed to configure git: {str(e)}")
        return None

    return None
