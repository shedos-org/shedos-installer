#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Enroll the recovery key as a second LUKS keyslot on the root container.

The recoverykeyq view step (shown before the disk is touched) generates
the recovery key, displays it, gates progress until the user confirms they
saved it, and stashes it in globalstorage as `shedos_recovery_key`. This
job runs in the exec phase and adds it as a second keyslot, authorized by
the passphrase the user set. No-op when encryption was opted out."""

import os
import subprocess
import tempfile

import libcalamares


def pretty_name():
    return "Enrolling recovery key"


def run():
    recovery = libcalamares.globalstorage.value("shedos_recovery_key")
    if not recovery:
        return None  # encryption opted out — nothing to enroll

    partitions = libcalamares.globalstorage.value("partitions") or []
    root = next(
        (p for p in partitions
         if p.get("mountPoint") == "/" and p.get("luksMapperName")),
        None,
    )
    if not root:
        return None  # no LUKS root — nothing to enroll

    device = root.get("device")
    # Calamares stores the partition LUKS passphrase in plaintext (only the
    # user-account password is obscured); the historical luksbootkeyfile job
    # wrote it raw to the keyfile. Use it as-is — deobscuring corrupts it.
    passphrase = root.get("luksPassphrase")
    if not device or not passphrase:
        return ("Recovery key not enrolled",
                "The encryption passphrase was not available to authorize it.")

    # The new (recovery) key goes in a private 0600 file under /run's
    # tmpfs — never on argv — and is removed straight after. The existing
    # passphrase authorizes the add via stdin. No trailing newline: the
    # enrolled key must byte-match what the user types at the boot prompt.
    fd, keyfile = tempfile.mkstemp(prefix="shedos-recovery-", dir="/run")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(recovery.encode())
        proc = subprocess.run(
            ["cryptsetup", "luksAddKey", "--key-file=-", device, keyfile],
            input=passphrase.encode(),
            capture_output=True,
        )
    finally:
        try:
            os.unlink(keyfile)
        except OSError:
            pass

    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        return ("Recovery key enrollment failed",
                detail or "cryptsetup luksAddKey failed")
    return None
