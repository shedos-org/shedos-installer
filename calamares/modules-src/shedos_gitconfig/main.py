#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Seed the new user's ~/.gitconfig with ShedOS defaults. user.name comes
from the Calamares users page (Full Name); user.email is filled in only
if the user entered it on the same page, in the optional developer
setup group. When they also ticked the SSH checkbox, an ed25519 key is
generated as the new user."""

import os
import re

import libcalamares
from libcalamares.utils import check_target_env_call, target_env_call

# A newline in name/email would let a crafted value inject extra gitconfig
# sections (e.g. a [core] sshCommand). Reject control chars before writing.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def pretty_name():
    return "Configuring git for developer workflow"


def run():
    gs = libcalamares.globalstorage

    username = gs.value("username")
    fullname = gs.value("fullName")
    email = gs.value("devinfoEmail") or ""
    want_ssh = bool(gs.value("devinfoSsh"))

    if not username:
        libcalamares.utils.warning("No username found in global storage")
        return None

    if not fullname:
        fullname = username

    if _CONTROL_CHARS.search(fullname):
        libcalamares.utils.warning(
            "Full name contains control characters; falling back to username"
        )
        fullname = username

    if email and not _EMAIL.match(email):
        libcalamares.utils.warning(
            "Skipping git user.email: value is not a valid address"
        )
        email = ""

    libcalamares.utils.debug(f"Configuring git for: {fullname}")

    root_mount = gs.value("rootMountPoint")
    if not root_mount:
        libcalamares.utils.warning("No root mount point found")
        return None

    user_home = os.path.join(root_mount, "home", username)
    gitconfig_path = os.path.join(user_home, ".gitconfig")

    user_block = f"    name = {fullname}\n"
    if email:
        user_block += f"    email = {email}\n"

    gitconfig_content = f"""# ShedOS Git Configuration
# Generated during installation

[user]
{user_block}
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

    except Exception as e:
        libcalamares.utils.warning(f"Failed to configure git: {str(e)}")
        return None

    if want_ssh and email:
        # ssh-keygen directly, not via `su - $user`: a login shell
        # would spawn oh-my-zsh's ssh-agent daemon, which pins the
        # chroot's /dev/shm bind and breaks Calamares' final umount.
        ssh_dir = f"/home/{username}/.ssh"
        target_env_call(['mkdir', '-p', ssh_dir])
        target_env_call(['chmod', '700', ssh_dir])
        rc = target_env_call([
            'ssh-keygen', '-t', 'ed25519', '-N', '', '-C', email,
            '-f', f'{ssh_dir}/id_ed25519',
        ])
        if rc != 0:
            libcalamares.utils.warning(
                f"ssh-keygen for {username} exited {rc}; "
                "the user can run ssh-keygen manually after first login"
            )
        else:
            target_env_call(['chown', '-R', f'{username}:{username}', ssh_dir])
            libcalamares.utils.debug(f"SSH ed25519 key generated for {username}")

    libcalamares.utils.debug("Git configuration complete")
    return None
