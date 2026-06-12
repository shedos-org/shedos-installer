"""Limine bootloader installation for ShedOS installer."""

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from shedos_installer.utils.command import run_command, run_chroot
from shedos_installer.utils.hardware import is_uefi

logger = logging.getLogger(__name__)


class LimineInstaller:
    """Handles Limine bootloader installation."""

    def __init__(
        self,
        mount_point: str = "/mnt",
        root_uuid: str = "",
        luks_uuid: Optional[str] = None,
        nvidia: bool = False,
    ) -> None:
        """Initialize Limine installer."""
        self.mount_point = Path(mount_point)
        self.root_uuid = root_uuid
        self.luks_uuid = luks_uuid
        self.nvidia = nvidia
        self.is_uefi = is_uefi()
        
        logger.info(f"LimineInstaller init: UEFI={self.is_uefi}, RootUUID={self.root_uuid}, LuksUUID={self.luks_uuid}")

    def install(self, disk_device: str) -> bool:
        """Install Limine bootloader."""
        logger.info("Installing Limine bootloader")

        if not self.root_uuid:
            logger.error("Root UUID is missing, cannot configure bootloader")
            return False
            
        if not self.is_uefi and not disk_device:
            logger.error("BIOS installation requires a target disk device (e.g. /dev/sda), but none provided.")
            return False

        try:
            if self.is_uefi:
                return self._install_uefi()
            else:
                return self._install_bios(disk_device)
        except Exception:
            logger.exception("Unexpected error during bootloader installation")
            return False

    def _install_uefi(self) -> bool:
        """Install Limine for UEFI systems."""
        logger.info("Installing Limine for UEFI")

        try:
            efi_dir = self.mount_point / "boot" / "efi" / "EFI" / "BOOT"
            efi_dir.mkdir(parents=True, exist_ok=True)

            limine_dir = self.mount_point / "boot" / "efi" / "EFI" / "limine"
            limine_dir.mkdir(parents=True, exist_ok=True)

            limine_src = Path("/usr/share/limine")
            bootx64_src = limine_src / "BOOTX64.EFI"

            if not bootx64_src.exists():
                logger.error(f"Limine EFI file not found: {bootx64_src}")
                return False

            logger.info(f"Copying {bootx64_src} to {efi_dir / 'BOOTX64.EFI'}")
            shutil.copy2(bootx64_src, efi_dir / "BOOTX64.EFI")

            logger.info(f"Copying {bootx64_src} to {limine_dir / 'BOOTX64.EFI'}")
            shutil.copy2(bootx64_src, limine_dir / "BOOTX64.EFI")

            if not self._create_config(limine_dir):
                return False

            # ESP root is where Limine looks by default; the /EFI/limine/
            # config alone is not enough.
            esp_root = self.mount_point / "boot" / "efi"
            if not self._create_config(esp_root):
                return False

            # Best-effort dual-boot + firmware registration; neither
            # may fail the install.
            self._setup_windows_chainload()
            self._register_nvram_entry()
            return True

        except Exception as e:
            logger.exception(f"UEFI installation failed: {e}")
            return False

    def _detect_windows_esp_uuid(self) -> Optional[str]:
        """Filesystem UUID of an ESP carrying the Windows boot manager,
        or None. The target ESP is checked in place; every other
        EFI-system partition is probed with a read-only mount."""
        bootmgfw = Path("EFI/Microsoft/Boot/bootmgfw.efi")
        target_esp = self.mount_point / "boot" / "efi"
        if (target_esp / bootmgfw).is_file():
            src = run_command(["findmnt", "-no", "SOURCE", str(target_esp)])
            if src.success and src.stdout.strip():
                fs_uuid = run_command(
                    ["lsblk", "-rno", "UUID", src.stdout.strip()])
                if fs_uuid.success and fs_uuid.stdout.strip():
                    return fs_uuid.stdout.strip()
            return None

        probe = run_command(["lsblk", "-rno", "PATH,PARTTYPE,UUID"])
        if not probe.success:
            return None
        esp_guid = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
        for line in probe.stdout.splitlines():
            fields = line.split()
            if len(fields) < 2 or fields[1].lower() != esp_guid:
                continue
            path = fields[0]
            fs_uuid = fields[2] if len(fields) > 2 else ""
            with tempfile.TemporaryDirectory(prefix="shedos-esp.") as td:
                # The target ESP is busy (mounted) and fails here,
                # which is fine — it was already checked above.
                if not run_command(["mount", "-o", "ro", path, td]).success:
                    continue
                try:
                    found = (Path(td) / bootmgfw).is_file()
                finally:
                    run_command(["umount", td])
            if found and fs_uuid:
                return fs_uuid
        return None

    def _setup_windows_chainload(self) -> None:
        """Write the Windows entry render-limine-config.sh appends on
        every regeneration. Without this, a dual-boot machine boots
        straight into ShedOS with no path back to Windows."""
        try:
            fs_uuid = self._detect_windows_esp_uuid()
        except Exception:
            logger.exception("Windows detection failed (non-fatal)")
            return
        if not fs_uuid:
            logger.info("No Windows boot manager found; single-boot config")
            return
        logger.info(f"Windows found on ESP {fs_uuid}; adding chainload entry")
        extra = self.mount_point / "etc" / "shedos" / "limine-extra-entries.conf"
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text(
            "# Written by the installer: Windows boot manager found on\n"
            f"# the ESP with filesystem UUID {fs_uuid}.\n"
            "# render-limine-config.sh appends this file verbatim to\n"
            "# limine.conf on every regeneration.\n"
            "/Windows\n"
            "    protocol: efi_chainload\n"
            f"    image_path: uuid({fs_uuid}):"
            "/EFI/Microsoft/Boot/bootmgfw.efi\n"
        )
        # Re-render so the entry lands in this install's limine.conf,
        # not just the next kernel upgrade's.
        run_chroot(["/usr/lib/shedos/render-limine-config.sh"],
                   str(self.mount_point))

    def _register_nvram_entry(self) -> None:
        """Register ShedOS with the firmware via efibootmgr. The
        removable-path BOOTX64.EFI copy keeps us bootable without it,
        but a real NVRAM entry makes firmware boot menus list ShedOS
        by name next to Windows."""
        esp = self.mount_point / "boot" / "efi"
        src = run_command(["findmnt", "-no", "SOURCE", str(esp)])
        if not src.success or not src.stdout.strip():
            logger.warning("efibootmgr: cannot resolve the ESP device; skipping")
            return
        dev = src.stdout.strip()
        pkname = run_command(["lsblk", "-rno", "PKNAME", dev])
        partn = run_command(["lsblk", "-rno", "PARTN", dev])
        if not (pkname.success and pkname.stdout.strip()
                and partn.success and partn.stdout.strip()):
            logger.warning(f"efibootmgr: cannot split {dev}; skipping")
            return
        disk = "/dev/" + pkname.stdout.strip()
        part = partn.stdout.strip()

        # Drop stale ShedOS entries from earlier installs so reinstalls
        # don't pile up duplicates.
        listing = run_command(["efibootmgr"])
        if listing.success:
            for line in listing.stdout.splitlines():
                if line.startswith("Boot") and line.rstrip().endswith("ShedOS"):
                    bootnum = line[4:8]
                    run_command(["efibootmgr", "-b", bootnum, "-B"])

        result = run_command([
            "efibootmgr", "--create", "--disk", disk, "--part", part,
            "--label", "ShedOS", "--loader", r"\EFI\limine\BOOTX64.EFI",
        ])
        if result.success:
            logger.info(f"efibootmgr: registered ShedOS ({disk} part {part})")
        else:
            logger.warning(f"efibootmgr failed (non-fatal): {result.stderr}")

    def _install_bios(self, disk_device: str) -> bool:
        """Install Limine for BIOS systems.

        Limine's BIOS stages read FAT12/16/32 and ISO9660 only, so
        limine-bios.sys, limine.conf and the kernels all live on the
        FAT partition the hybrid layout provides at /boot/efi —
        exactly the volume EFI installs boot from. The earlier
        version put them inside the btrfs @ subvolume, which Limine
        cannot read, and reported success anyway."""
        logger.info("Installing Limine for BIOS")

        try:
            fat_boot = self.mount_point / "boot" / "efi"
            if not fat_boot.is_dir() or not run_command(
                    ["findmnt", "-no", "SOURCE", str(fat_boot)]).success:
                logger.error(
                    "BIOS install needs the FAT boot partition mounted at "
                    "/boot/efi (created automatically on erase-disk "
                    "installs). Manual partitioning must include a FAT32 "
                    "partition mounted there — Limine cannot read btrfs."
                )
                return False

            limine_dir = fat_boot / "limine"
            limine_dir.mkdir(parents=True, exist_ok=True)

            bios_sys_src = Path("/usr/share/limine/limine-bios.sys")
            if not bios_sys_src.exists():
                logger.error(f"Limine BIOS file not found: {bios_sys_src}")
                return False

            logger.info(f"Copying {bios_sys_src} to {limine_dir}")
            shutil.copy2(bios_sys_src, limine_dir / "limine-bios.sys")

            # GPT requires an EF02 bios-boot partition for stage2 —
            # `limine bios-install` never uses the pre-partition gap on
            # GPT and errors without one. msdos embeds in the post-MBR
            # gap and takes no partition argument.
            pttype = run_command(["lsblk", "-rno", "PTTYPE", disk_device])
            table = pttype.stdout.strip().splitlines()[0] if (
                pttype.success and pttype.stdout.strip()) else ""
            install_cmd = ["limine", "bios-install", disk_device]
            if table == "gpt":
                partn = self._find_bios_boot_partn(disk_device)
                if not partn:
                    logger.error(
                        "GPT disk has no BIOS boot (EF02) partition; "
                        "limine bios-install has nowhere to embed its "
                        "stage2. Erase-disk installs create one "
                        "automatically; manual GPT layouts must include "
                        "an unformatted 8 MiB EF02 partition."
                    )
                    return False
                install_cmd.append(partn)

            logger.info(f"Running {' '.join(install_cmd)}")
            result = run_command(install_cmd)
            if not result.success:
                logger.error(f"limine bios-install failed: {result.stderr}")
                return False

            # limine.conf at the FAT volume root (same search path the
            # EFI install uses), kernels + initramfs beside it.
            if not self._create_config(fat_boot):
                return False
            return self._copy_kernels_to_esp()

        except Exception as e:
            logger.exception(f"BIOS installation failed: {e}")
            return False

    def _find_bios_boot_partn(self, disk_device: str) -> Optional[str]:
        """1-based partition number of the disk's BIOS boot (EF02)
        partition, or None."""
        bios_boot_guid = "21686148-6449-6e6f-744e-656564454649"
        probe = run_command(
            ["lsblk", "-rno", "PARTN,PARTTYPE", disk_device])
        if not probe.success:
            return None
        for line in probe.stdout.splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[1].lower() == bios_boot_guid:
                return fields[0]
        return None

    def _build_cmdline(self) -> str:
        """Compose the install-time kernel command line.

        Three classes of token belong here:

        1. Hardware/topology essentials that can't be derived after the
           fact — root=, rootflags=, rootfstype=, cryptdevice=,
           nvidia_drm.modeset=1.
        2. UX-critical, never-tunable tokens that must take effect on
           the very first kernel handoff (before `shedman apply` ever
           runs) — quiet, splash, loglevel=3, rd.udev.log_level=3,
           fbcon=nodefer. Together with clear-vt-text.sh (which wipes
           the VT text buffer Before=greetd.service) and the various
           stdio→journal redirects, these suppress the framebuffer
           console flash between Plymouth and Hyprland.

           console=tty1 was previously included here but had to be
           removed: any explicit `console=` value populates
           /sys/class/tty/console/active, and Plymouth's device-
           manager interprets that as a serial console and force-
           falls-back to the text-only `details` plugin for the entire
           session — including shutdown, where the graphical brand
           never gets to render. Letting the kernel default (tty0)
           stand keeps Plymouth in graphical mode; the other tokens
           still suppress the visible boot/login console text.

           fbcon=nodefer used to be paired with map:99 — the pair
           kept fbcon "active but mapped to a nonexistent fbdev" so
           every DRM-master gap painted black. But map:99 also
           permanently unmapped the FB console from every VT, which
           silently broke Ctrl+Alt+F<N> TTY switching post-boot. The
           other flash-suppression mitigations (clear-vt-text.sh,
           quiet, loglevel=3, rd.udev.log_level=3, journal
           redirects) cover the visible-flash case on their own,
           verified empirically on dev + test hardware. nodefer
           alone keeps fbcon ready without disabling VT mapping.

        3. The LSM stack with AppArmor enabled —
           lsm=landlock,lockdown,yama,integrity,apparmor,bpf. Stock
           linux-zen's CONFIG_LSM ships without apparmor, and lsm= is a
           full override of the kernel's LSM list, so the whole set is
           spelled out. It's baked in here (not a [kernel.cmdline] append)
           so AppArmor is enforcing from the very first boot, before any
           `shedman apply` runs; existing installs get the same token via
           shedos-system's _backfill_apparmor_lsm on upgrade.

        User-tunable tokens (nowatchdog, mitigations=*,
        split_lock_detect=off, nvme_core.default_ps_max_latency_us=*,
        etc.) are NOT included here. They live in
        /etc/shedos/system.toml's [kernel.cmdline].append and are
        merged in by `shedman apply`. Including them here would freeze
        them into the apply_core baseline (which seeds itself from the
        live cmdline on first apply) and make them un-removable via
        system.toml edits.
        """
        parts: list[str] = []
        if self.luks_uuid:
            mapper_name = f"luks-{self.luks_uuid}"
            # rd.luks.* is what sd-encrypt reads; cryptdevice= is kept
            # so the same cmdline still boots a legacy-initrd rescue
            # image. Each initrd style ignores the other's token.
            parts.append(f"rd.luks.name={self.luks_uuid}={mapper_name}")
            parts.append("rd.luks.options=discard")
            parts.append(
                f"cryptdevice=UUID={self.luks_uuid}:{mapper_name}:allow-discards"
            )
            parts.append(f"root=/dev/mapper/{mapper_name}")
        else:
            parts.append(f"root=UUID={self.root_uuid}")
        parts.extend([
            "rootflags=subvol=@",
            "rootfstype=btrfs",
            "rw",
            "quiet",
            "splash",
            "loglevel=3",
            "rd.udev.log_level=3",
            "fbcon=nodefer",
            "lsm=landlock,lockdown,yama,integrity,apparmor,bpf",
        ])
        if self.nvidia:
            parts.append("nvidia_drm.modeset=1")

        # Hibernation: when the partitioner created disk swap (the
        # "suspend" choice), point the systemd initrd at it. The
        # target fstab is the path-independent source — both install
        # flows write it before the bootloader step. Swapfiles (path
        # entries, no UUID=) are skipped; resume_offset plumbing is
        # not worth it for a layout the installer never creates.
        swap_uuid = self._fstab_swap_uuid()
        if swap_uuid:
            parts.append(f"resume=UUID={swap_uuid}")
        return " ".join(parts)

    def _fstab_swap_uuid(self) -> str | None:
        fstab = self.mount_point / "etc" / "fstab"
        try:
            for line in fstab.read_text().splitlines():
                fields = line.split()
                if len(fields) >= 3 and fields[2] == "swap" \
                        and fields[0].startswith("UUID="):
                    return fields[0].removeprefix("UUID=")
        except OSError:
            pass
        return None

    def _create_config(self, config_dir: Path) -> bool:
        """Render Limine configuration via the packaged renderer.

        The renderer at /usr/lib/shedos/render-limine-config.sh discovers
        every installed kernel under /usr/lib/modules/*/pkgbase and emits
        a multi-entry limine.conf with timeout=3. We invoke it inside the
        target chroot with SHEDOS_LIMINE_CMDLINE set so the very first
        config has the correct install-time cmdline (no existing
        limine.conf to read from yet).

        Two output paths matter for UEFI:
          - the /EFI/limine/ directory we land in
          - the ESP root (where Limine looks by default)
        and one for BIOS:
          - /boot/limine/

        The renderer writes to /boot/limine.conf inside the chroot. We
        then copy that file to the requested config_dir if it differs
        from /boot.
        """
        logger.info(f"Creating Limine configuration via packaged renderer for {config_dir}")

        cmdline = self._build_cmdline()

        # Path inside the chroot is just /boot, regardless of where
        # mount_point is anchored on the host.
        env_pairs = [f"SHEDOS_LIMINE_CMDLINE={cmdline}"]
        result = run_chroot(
            ["env", *env_pairs, "/usr/lib/shedos/render-limine-config.sh"],
            mount_point=str(self.mount_point),
        )
        if not result.success:
            logger.error(
                "render-limine-config.sh failed inside chroot: %s", result.stderr
            )
            return False

        boot_config = self.mount_point / "boot" / "limine.conf"
        if not boot_config.exists():
            logger.error("renderer reported success but %s is missing", boot_config)
            return False

        try:
            target_config = config_dir / "limine.conf"
            if target_config.resolve() != boot_config.resolve():
                shutil.copy2(boot_config, target_config)
                logger.info("Copied %s to %s", boot_config, target_config)
            return True
        except Exception:
            logger.exception("Failed to mirror limine.conf to %s", config_dir)
            return False


    def configure_mkinitcpio(self) -> bool:
        """Configure mkinitcpio for BTRFS and optional LUKS."""
        logger.info("Configuring mkinitcpio")

        kernel_path = self.mount_point / "boot" / "vmlinuz-linux-zen"
        if not kernel_path.exists():
            logger.error(f"Kernel not found at {kernel_path}")
            logger.error("linux-zen may not have been installed correctly")
            return False
        logger.info(f"Kernel found at {kernel_path}")

        # systemd-style initrd from the start: the legacy udev+keymap
        # stack is what migrate-mkinitcpio-hooks.sh exists to escape
        # (busybox keymap.bin breaks with current kbd), and both the
        # boot-failure recovery unit and hibernate resume only work
        # under the systemd initrd.
        hooks = ["base", "systemd", "autodetect", "modconf", "kms",
                 "keyboard", "sd-vconsole", "block", "plymouth"]

        if self.luks_uuid:
            hooks.append("sd-encrypt")

        # Boot-failure auto-recovery: counts boots that never reach the
        # greeter and falls back to a snapshot clone after three.
        hooks.append("shedos-recovery")

        # Skip fsck — btrfs handles its own integrity, and the fsck hook
        # can break boot on btrfs roots.
        hooks.append("filesystems")

        modules = "MODULES=(btrfs)"
        if self.nvidia:
            modules = "MODULES=(btrfs nvidia nvidia_modeset nvidia_uvm nvidia_drm)"

        # Plymouth needs these fonts inside the initramfs to render text.
        files = [
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "/usr/share/fonts/noto/NotoSans-Regular.ttf"
        ]
        files_line = f"FILES=({' '.join(files)})"

        hooks_line = f"HOOKS=({' '.join(hooks)})"

        conf_path = self.mount_point / "etc" / "mkinitcpio.conf"
        try:
            content = conf_path.read_text()

            # Replace MODULES/FILES/HOOKS lines so any archiso-specific
            # hooks (`archiso`, `archiso_loop_mnt`, etc.) on the live ISO
            # don't survive into the installed system.
            import re
            content = re.sub(r'^MODULES=\(.*\)$', modules, content, flags=re.MULTILINE)
            content = re.sub(r'^FILES=\(.*\)$', files_line, content, flags=re.MULTILINE)
            content = re.sub(r'^HOOKS=\(.*\)$', hooks_line, content, flags=re.MULTILINE)

            conf_path.write_text(content)
            logger.info(f"Updated mkinitcpio.conf with HOOKS=({' '.join(hooks)}) and FILES=({' '.join(files)})")

            logger.info("Regenerating initramfs...")
            result = run_chroot(
                ["mkinitcpio", "-P"],
                mount_point=str(self.mount_point),
            )
            if not result.success:
                logger.error(f"Failed to regenerate initramfs: {result.stderr}")
                if result.stdout:
                    logger.error(f"mkinitcpio stdout: {result.stdout}")
                return False

            # Limine's recovery menu loads the fallback variant; mkinitcpio -P
            # can exit 0 with one preset silently failing (e.g. disk full),
            # so check both files exist before declaring success.
            required_initramfs = [
                "initramfs-linux-zen.img",
                "initramfs-linux-zen-fallback.img",
            ]
            missing = [
                f for f in required_initramfs
                if not (self.mount_point / "boot" / f).exists()
            ]
            if missing:
                logger.error(f"initramfs files not created: {missing}")
                return False
            for f in required_initramfs:
                logger.info(f"initramfs created at {self.mount_point / 'boot' / f}")

            # Copy the freshly regenerated kernel + initramfs to the FAT
            # boot volume (the ESP — BIOS installs boot from the same
            # partition, since Limine reads only FAT/ISO9660). Must run
            # AFTER mkinitcpio so it picks up the variant with our final
            # HOOKS (LUKS + Plymouth).
            logger.info("Copying freshly generated kernels to the boot volume...")
            if not self._copy_kernels_to_esp():
                logger.error("Failed to copy regenerated kernels to the boot volume")
                return False

            return True
        except Exception as e:
            logger.exception(f"Failed to configure mkinitcpio: {e}")
            return False

    def _copy_kernels_to_esp(self) -> bool:
        """Copy kernel and initramfs to ESP after mkinitcpio regeneration."""
        efi_root = self.mount_point / "boot" / "efi"
        boot_src = self.mount_point / "boot"

        if not efi_root.exists():
            logger.warning(f"EFI root {efi_root} does not exist, attempting to create")
            try:
                efi_root.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create EFI root: {e}")
                return False

        files_to_copy = [
            "vmlinuz-linux-zen",
            "initramfs-linux-zen.img",
            "initramfs-linux-zen-fallback.img",
        ]
        success = True

        for filename in files_to_copy:
            src = boot_src / filename
            dst = efi_root / filename

            if src.exists():
                try:
                    logger.info(f"Copying {src} to {dst}")
                    shutil.copy2(src, dst)
                except Exception as e:
                    logger.error(f"Failed to copy {filename} to EFI partition: {e}")
                    success = False
            else:
                logger.warning(f"Kernel file not found: {src}")
                if "fallback" not in filename:
                    success = False

        return success