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
        except Exception as e:
            logger.exception("Unexpected error during bootloader installation")
            return False

    def _install_uefi(self) -> bool:
        """Install Limine for UEFI systems."""
        logger.info("Installing Limine for UEFI")

        try:
            # Create EFI directory structure
            efi_dir = self.mount_point / "boot" / "efi" / "EFI" / "BOOT"
            efi_dir.mkdir(parents=True, exist_ok=True)

            limine_dir = self.mount_point / "boot" / "efi" / "EFI" / "limine"
            limine_dir.mkdir(parents=True, exist_ok=True)

            # Copy Limine files
            limine_src = Path("/usr/share/limine")
            bootx64_src = limine_src / "BOOTX64.EFI"

            if not bootx64_src.exists():
                logger.error(f"Limine EFI file not found: {bootx64_src}")
                return False

            # Copy BOOTX64.EFI to BOOT directory (fallback)
            logger.info(f"Copying {bootx64_src} to {efi_dir / 'BOOTX64.EFI'}")
            shutil.copy2(bootx64_src, efi_dir / "BOOTX64.EFI")

            # Copy BOOTX64.EFI to limine directory
            logger.info(f"Copying {bootx64_src} to {limine_dir / 'BOOTX64.EFI'}")
            shutil.copy2(bootx64_src, limine_dir / "BOOTX64.EFI")

            # Create config in /EFI/limine/ directory
            if not self._create_config(limine_dir):
                return False

            # CRITICAL: Also create config at ESP root where Limine looks by default
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

    def _create_config(self, config_dir: Path) -> bool:
        """Create Limine configuration file."""
        logger.info("Creating Limine configuration")

        # Build kernel command line
        cmdline_parts = []

        if self.luks_uuid:
            cmdline_parts.append(f"cryptdevice=UUID={self.luks_uuid}:cryptroot")
            cmdline_parts.append("root=/dev/mapper/cryptroot")
        else:
            cmdline_parts.append(f"root=UUID={self.root_uuid}")

        cmdline_parts.extend([
            "rootflags=subvol=@",
            "rootfstype=btrfs",
            "rw",
            "quiet",
            "splash",
        ])

        if self.nvidia:
            cmdline_parts.append("nvidia_drm.modeset=1")

        cmdline = " ".join(cmdline_parts)

        # Determine kernel URI
        # Limine cannot access files inside BTRFS subvolumes using uuid() syntax
        # Solution: Always copy kernel/initramfs to ESP and use boot(): protocol
        logger.info("Copying kernels to ESP for Limine access")
        if not self._ensure_kernels_on_esp():
            return False

        kernel_uri = "boot():"
        module_uri = "boot():"

        config = f"""# ShedOS Limine Configuration
timeout: 0

/ShedOS Linux
    protocol: linux
    kernel_path: {kernel_uri}/vmlinuz-linux
    kernel_cmdline: {cmdline}
    module_path: {module_uri}/initramfs-linux.img

/ShedOS Linux (Fallback)
    protocol: linux
    kernel_path: {kernel_uri}/vmlinuz-linux
    kernel_cmdline: {cmdline.replace('quiet splash', '')}
    module_path: {module_uri}/initramfs-linux-fallback.img
"""

        try:
            config_path = config_dir / "limine.conf"
            config_path.write_text(config)
            logger.info(f"Created {config_path}")

            # Create a backup/reference copy in /boot
            # This helps users find the config if they look in standard places
            boot_config = self.mount_point / "boot" / "limine.conf"
            boot_config.write_text(config)
            
            return True
        except Exception as e:
            logger.exception(f"Failed to write limine.conf: {e}")
            return False

    def _ensure_kernels_on_esp(self) -> bool:
        """Copy kernels to EFI partition for LUKS booting."""
        logger.info("Copying kernels to EFI partition (LUKS requirement)...")
        
        efi_root = self.mount_point / "boot" / "efi"
        boot_src = self.mount_point / "boot"
        
        # Ensure destination directory exists
        if not efi_root.exists():
            logger.warning(f"EFI root {efi_root} does not exist, attempting to create")
            try:
                efi_root.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create EFI root: {e}")
                return False
        
        files_to_copy = ["vmlinuz-linux", "initramfs-linux.img", "initramfs-linux-fallback.img"]
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
                # Don't fail strictly if fallback is missing, but warn
                if "fallback" not in filename:
                    success = False
                    
        return success

    def configure_mkinitcpio(self) -> bool:
        """Configure mkinitcpio for BTRFS and optional LUKS."""
        logger.info("Configuring mkinitcpio")

        # Verify kernel exists before proceeding
        kernel_path = self.mount_point / "boot" / "vmlinuz-linux"
        if not kernel_path.exists():
            logger.error(f"Kernel not found at {kernel_path}")
            logger.error("The linux package may not have been installed correctly")
            return False
        logger.info(f"Kernel found at {kernel_path}")

        hooks = ["base", "udev", "autodetect", "modconf", "kms", "keyboard", "keymap", "consolefont", "block", "plymouth"]

        if self.luks_uuid:
            hooks.append("encrypt")

        hooks.extend(["filesystems", "fsck"])

        # Add btrfs module
        modules = "MODULES=(btrfs)"
        if self.nvidia:
            modules = "MODULES=(btrfs nvidia nvidia_modeset nvidia_uvm nvidia_drm)"

        hooks_line = f"HOOKS=({' '.join(hooks)})"

        # Read current mkinitcpio.conf
        conf_path = self.mount_point / "etc" / "mkinitcpio.conf"
        try:
            content = conf_path.read_text()

            # Replace MODULES and HOOKS lines (remove any archiso-specific hooks)
            import re
            content = re.sub(r'^MODULES=\(.*\)$', modules, content, flags=re.MULTILINE)
            content = re.sub(r'^HOOKS=\(.*\)$', hooks_line, content, flags=re.MULTILINE)

            conf_path.write_text(content)
            logger.info(f"Updated mkinitcpio.conf with HOOKS=({' '.join(hooks)})")

            # Regenerate initramfs with verbose output for debugging
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

            # Verify initramfs was created
            initramfs_path = self.mount_point / "boot" / "initramfs-linux.img"
            if not initramfs_path.exists():
                logger.error(f"initramfs not created at {initramfs_path}")
                return False
            logger.info(f"initramfs created at {initramfs_path}")

            return True
        except Exception as e:
            logger.exception(f"Failed to configure mkinitcpio: {e}")
            return False