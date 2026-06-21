"""Secure Boot key provisioning for the ShedOS installer.

Per-box keys, never a shared CA: `sbctl create-keys` mints this machine's own
PK/KEK/db into the target root, and we enroll them into firmware ONLY when the
box is in Setup Mode (PK cleared). Outside Setup Mode we leave the boot chain
unsigned — signing with keys the firmware hasn't enrolled would produce images
it rejects, so a self-signed image is worse than an unsigned one there; the user
finishes enrollment later via `shedman secureboot enroll` after entering Setup
Mode. BIOS boxes have no Secure Boot at all and we touch no firmware variables.

When we do provision, we rewrite /etc/kernel/uki.conf (shipped keyless) to the
signing form so ukify signs every UKI from then on. We never copy the db key out
of sbctl's own store — uki.conf and the build-uki.sh placer both read it from
/var/lib/sbctl/keys/db. Only the PCR-11 signing key is ShedOS's own, under
/etc/shedos/secureboot/.
"""

import logging
from pathlib import Path

from shedos_installer.utils.command import run_chroot

logger = logging.getLogger(__name__)

# ShedOS's per-box PCR-11 signing key (sbctl owns the SB db key under
# /var/lib/sbctl). The UKI carries a signed PCR-11 prediction so passwordless
# TPM2 unlock survives kernel updates; this key signs it.
PCR_DIR = "etc/shedos/secureboot"
DB_KEY = "/var/lib/sbctl/keys/db/db.key"
DB_CERT = "/var/lib/sbctl/keys/db/db.pem"
STUB = "/usr/lib/systemd/boot/efi/linuxx64.efi.stub"
UKI_CONF = "etc/kernel/uki.conf"
# sbctl invoked under arch-chroot: landlock would sandbox away the bind-mounted
# efivars and key store, so disable it on every call.
SBCTL = ["sbctl", "--disable-landlock"]


class SecureBootEnroller:
    """Mints + enrolls this box's Secure Boot keys into the target root."""

    def __init__(self, mount_point: str, uefi: bool = True) -> None:
        self.mount_point = Path(mount_point)
        self.uefi = uefi

    def probe_setup_mode(self) -> bool:
        """True when firmware is in Setup Mode (PK cleared) so our keys can be
        enrolled without a physical key-clear. The installer runs on the same
        firmware the target will boot, so the host SetupMode var is authoritative."""
        var = Path(
            "/sys/firmware/efi/efivars/"
            "SetupMode-8be4df61-93ca-11d2-aa0d-00e098032b8c"
        )
        try:
            data = var.read_bytes()
        except OSError:
            return False
        # 4-byte attribute prefix, then a single bool byte.
        return len(data) >= 5 and data[4] == 1

    def generate_keys(self) -> bool:
        """Mint the per-box SB db keypair (sbctl, into the target) and a per-box
        PCR-11 signing keypair. Returns False only on a failure that would leave
        the box mis-signed."""
        # --disable-landlock: sbctl's landlock sandbox can deny the paths
        # arch-chroot bind-mounts (efivars, the key store) and fail silently;
        # the installer already runs as root in a trusted target chroot.
        keys = run_chroot(SBCTL + ["create-keys"], mount_point=str(self.mount_point))
        if not keys.success:
            logger.error("sbctl create-keys failed: %s", keys.stderr)
            return False

        sb = self.mount_point / PCR_DIR
        sb.mkdir(parents=True, exist_ok=True)
        priv = f"/{PCR_DIR}/pcr-private.pem"
        pub = f"/{PCR_DIR}/pcr-public.pem"
        gen = run_chroot([
            "openssl", "genpkey", "-algorithm", "RSA",
            "-pkeyopt", "rsa_keygen_bits:2048", "-out", priv,
        ], mount_point=str(self.mount_point))
        if not gen.success:
            logger.error("PCR key generation failed: %s", gen.stderr)
            return False
        run_chroot(["openssl", "rsa", "-pubout", "-in", priv, "-out", pub],
                   mount_point=str(self.mount_point))
        run_chroot(["chmod", "600", priv], mount_point=str(self.mount_point))
        return True

    def rewrite_uki_conf(self) -> None:
        """Rewrite the shipped keyless /etc/kernel/uki.conf to the signing form
        so ukify signs every UKI (sbsign with the box db key + the PCR-11
        prediction). Leaving the keyless form would build unsigned images."""
        conf = self.mount_point / UKI_CONF
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(
            "# Rewritten by the installer once per-box keys exist. ukify signs\n"
            "# every UKI with the box db key and a PCR-11 prediction.\n"
            "[UKI]\n"
            f"Stub={STUB}\n"
            f"SecureBootPrivateKey={DB_KEY}\n"
            f"SecureBootCertificate={DB_CERT}\n"
            "\n"
            "[PCRSignature:initrd]\n"
            f"PCRPrivateKey=/{PCR_DIR}/pcr-private.pem\n"
            f"PCRPublicKey=/{PCR_DIR}/pcr-public.pem\n"
            "Phases=enter-initrd\n"
            "PCRBanks=sha256\n"
        )

    def arm(self) -> bool:
        """The single IRREVERSIBLE step: enroll this box's PK/KEK/db into
        firmware so Secure Boot is enforced from the next boot. Call ONLY after
        the ENTIRE signed chain — the Limine copies AND every placed UKI — is
        verified, so any upstream failure leaves Secure Boot off and the box
        bootable. --microsoft is ALWAYS included: discrete-GPU and NIC option
        ROMs are signed by the Microsoft UEFI CA, so ShedOS-only keys make
        firmware refuse the option ROM under Secure Boot — a black-screen brick
        even on a single-boot box. Keeping the MS CA is the standard tradeoff
        (the rollback exposure is documented)."""
        cmd = SBCTL + ["enroll-keys", "--microsoft", "--yes-this-might-brick-my-machine"]
        res = run_chroot(cmd, mount_point=str(self.mount_point))
        if not res.success:
            logger.error(
                "Secure Boot: arming FAILED — keys are on disk and the chain is "
                "signed, but the firmware did not accept them, so Secure Boot is "
                "NOT active. The box boots normally; complete it with `shedman "
                "secureboot enroll`."
            )
            return False
        return True

    def sign_targets(self, targets: list[str]) -> None:
        """sbsign each Limine EFI copy with the box db key. Paths are on-host
        paths under the mounted ESP; sbctl signs in place. Best-effort here —
        verify_signed() is the hard gate that blocks arming on a failed sign."""
        for t in targets:
            if not Path(t).exists():
                logger.warning("Secure Boot: sign target missing: %s", t)
                continue
            res = run_chroot(SBCTL + ["sign", "-s", t.replace(str(self.mount_point), "", 1)],
                             mount_point=str(self.mount_point))
            if not res.success:
                logger.warning("sbctl sign failed for %s (non-fatal): %s", t, res.stderr)

    def verify_signed(self, targets: list[str]) -> bool:
        """sbverify every Limine copy against the box db cert — the same
        backstop uki-place.sh gives the UKIs. A copy that did not actually get
        signed must block arming, or firmware rejects it at the next boot and
        the box is unbootable under Secure Boot."""
        for t in targets:
            rel = t.replace(str(self.mount_point), "", 1)
            res = run_chroot(["sbverify", "--cert", DB_CERT, rel],
                             mount_point=str(self.mount_point))
            if not res.success:
                logger.error("Secure Boot: %s is not validly signed: %s", rel, res.stderr)
                return False
        return True

    def provision(self, limine_copies: list[str]) -> bool:
        """Mint keys, rewrite uki.conf to its signing form, and sign + VERIFY
        the Limine EFI copies — everything EXCEPT the irreversible firmware
        arming, which the caller does last via arm() once the UKIs are placed.
        Returns True only when the box is in Setup Mode and every Limine copy is
        signed and sbverify-confirmed (safe to arm); False means leave the chain
        unsigned and NEVER arm. Best-effort: never raises, never aborts the
        install — the box always boots."""
        if not self.uefi:
            logger.info("Secure Boot: BIOS target, nothing to provision")
            return False
        if not self.probe_setup_mode():
            logger.info(
                "Secure Boot: firmware not in Setup Mode — leaving the boot "
                "chain unsigned; finish with `shedman secureboot enroll` after "
                "clearing the platform key"
            )
            return False
        if not self.generate_keys():
            return False
        self.rewrite_uki_conf()
        self.sign_targets(limine_copies)
        if not self.verify_signed(limine_copies):
            logger.error(
                "Secure Boot: the Limine copies are not validly signed — NOT "
                "arming Secure Boot, so the box stays bootable. Re-run `shedman "
                "secureboot enroll` once resolved."
            )
            return False
        return True
