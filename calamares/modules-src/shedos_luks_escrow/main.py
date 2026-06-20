#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Enroll the recovery key as an extra keyslot on every LUKS container the
system unlocks at boot.

The recoverykeyq view step (shown before the disk is touched) generates the
recovery key, displays it, gates progress until the user confirms they saved
it, and stashes it in globalstorage as `shedos_recovery_key`. This exec job
adds it to the root container AND any sibling LUKS container (the encrypted
swap used for hibernation lives in its own LUKS2 device): the boot cmdline
carries an rd.luks.name for each and unlocks them with tries=0, so the prompt
loops forever on any container the recovery key can't open. Enrolling only the
root container strands a recovery unlock at the swap prompt. No-op when
encryption was opted out."""

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
    # Every encrypted container the initramfs unlocks at boot, not just root —
    # the encrypted swap is a separate LUKS2 device with its own rd.luks.name.
    targets = [p for p in partitions
               if p.get("luksMapperName") and p.get("device")]
    if not targets:
        return None  # no LUKS container — nothing to enroll

    # Enroll every practical spelling so the key types at the BLIND LUKS boot
    # prompt regardless of Caps Lock or the grouping dashes: uppercase and
    # lowercase, each with and without dashes. A keyslot matches one exact byte
    # string, so each spelling needs its own slot; all derive from the same
    # secret, so the extra slots add no attack surface.
    forms = []
    for base in [recovery, recovery.lower()]:
        forms.append(base)
        stripped = base.replace("-", "")
        if stripped != base:
            forms.append(stripped)
    # De-dup (e.g. an all-digit key, where upper == lower).
    seen = set()
    forms = [f for f in forms if not (f in seen or seen.add(f))]

    for part in targets:
        device = part.get("device")
        # Calamares stores the partition LUKS passphrase in plaintext (only the
        # user-account password is obscured); use it as-is to authorize the add.
        passphrase = part.get("luksPassphrase")
        if not passphrase:
            return ("Recovery key not enrolled",
                    "The encryption passphrase for {} was not available "
                    "to authorize it.".format(device))

        for form in forms:
            # Each form goes in a private 0600 file under /run's tmpfs — never
            # on argv — and is removed straight after. The existing passphrase
            # authorizes the add via stdin. No trailing newline: the enrolled
            # key must byte-match what the user types at the boot prompt.
            fd, keyfile = tempfile.mkstemp(prefix="shedos-recovery-", dir="/run")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(form.encode())
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
                        detail or "cryptsetup luksAddKey failed on {}".format(device))
    return None
