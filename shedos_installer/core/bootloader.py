"""Limine bootloader installation for ShedOS installer."""

import logging
import shutil
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
            return self._create_config(esp_root)

        except Exception as e:
            logger.exception(f"UEFI installation failed: {e}")
            return False

    def _install_bios(self, disk_device: str) -> bool:
        """Install Limine for BIOS systems."""
        logger.info("Installing Limine for BIOS")

        try:
            boot_dir = self.mount_point / "boot" / "limine"
            boot_dir.mkdir(parents=True, exist_ok=True)

            limine_src = Path("/usr/share/limine")
            bios_sys_src = limine_src / "limine-bios.sys"

            if not bios_sys_src.exists():
                logger.error(f"Limine BIOS file not found: {bios_sys_src}")
                return False

            logger.info(f"Copying {bios_sys_src} to {boot_dir / 'limine-bios.sys'}")
            shutil.copy2(bios_sys_src, boot_dir / "limine-bios.sys")

            logger.info(f"Installing Limine to MBR of {disk_device}")
            result = run_command(["limine", "bios-install", disk_device])
            if not result.success:
                logger.error(f"Failed to install Limine to MBR: {result.stderr}")
                return False

            return self._create_config(boot_dir)

        except Exception as e:
            logger.exception(f"BIOS installation failed: {e}")
            return False

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
        return " ".join(parts)

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

        hooks = ["base", "udev", "autodetect", "modconf", "kms", "keyboard", "keymap", "consolefont", "block", "plymouth"]

        if self.luks_uuid:
            hooks.append("encrypt")

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

            if self.is_uefi:
                # Copy the freshly regenerated kernel + initramfs to the ESP.
                # Must run AFTER mkinitcpio so the ESP picks up the variant
                # with our final HOOKS (LUKS + Plymouth).
                logger.info("Copying freshly generated kernels to ESP...")
                if not self._copy_kernels_to_esp():
                    logger.error("Failed to copy regenerated kernels to ESP")
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