#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Stash the install-time recovery key on the target for the first-login tour.

The recoverykeyq view step generates the recovery key, displays it, and gates the
install until the user confirms they saved it, leaving it in globalstorage as
`shedos_recovery_key`; shedos_luks_escrow enrols it as a keyslot. This exec job runs
after unpackfs and drops the key at /var/lib/shedos/encrypt/recovery-key on the target,
where the first-boot tour shows it as a mandatory slide and then shreds it — the same
path the in-place `shedman encrypt` enrol writes, so both encryption routes converge on
one display. Best-effort: the key was already shown and acknowledged, so a write failure
here must never fail the install. No-op when encryption was opted out."""

import os

import libcalamares


def pretty_name():
    return "Saving the recovery key for first login"


def run():
    recovery = libcalamares.globalstorage.value("shedos_recovery_key")
    if not recovery:
        return None  # encryption opted out — nothing to stash

    root = libcalamares.globalstorage.value("rootMountPoint")
    if not root:
        libcalamares.utils.warning("shedos_recovery_stash: no rootMountPoint")
        return None

    try:
        stash_dir = os.path.join(root, "var/lib/shedos/encrypt")
        os.makedirs(stash_dir, exist_ok=True)
        # Wheel-writable dir: the tour (a wheel desktop user) must be able to
        # UNLINK the stash after showing it, and unlink needs write on the
        # parent dir, not the file. A wheel user already has disk access via
        # sudo, so this leaks nothing new.
        os.chmod(stash_dir, 0o770)
        stash = os.path.join(stash_dir, "recovery-key")
        with open(stash, "w") as f:
            f.write(recovery + "\n")
        # Wheel-readable so the tour can read it then shred it. chgrp in the
        # target so its wheel GID is used, not the host live ISO's.
        os.chmod(stash, 0o660)
        libcalamares.utils.target_env_call(
            ["chgrp", "wheel", "/var/lib/shedos/encrypt",
             "/var/lib/shedos/encrypt/recovery-key"]
        )
    except OSError as e:
        libcalamares.utils.warning(
            "shedos_recovery_stash: could not write the stash: {}".format(e)
        )
    return None
