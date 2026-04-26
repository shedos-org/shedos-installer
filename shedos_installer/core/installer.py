"""Main installer orchestrator for ShedOS."""

import logging
import shlex
import shutil
from pathlib import Path
from typing import Optional

from shedos_installer.config import (
    InstallConfig,
    MOUNT_POINT,
    PACKAGE_DIR,
    CONFIG_DIR,
    PROFILE_PACKAGES,
)
from shedos_installer.core.disk_manager import DiskManager
from shedos_installer.core.btrfs_manager import BtrfsManager
from shedos_installer.core.luks_manager import LuksManager
from shedos_installer.core.bootloader import LimineInstaller
from shedos_installer.utils.command import run_command, run_chroot
from shedos_installer.utils.hardware import get_gpus

logger = logging.getLogger(__name__)


class Installer:
    """Main installation orchestrator."""

    def __init__(self, config: InstallConfig) -> None:
        """Initialize installer."""
        self.config = config
        self.mount_point = MOUNT_POINT

        # Initialize managers
        self.disk_manager: Optional[DiskManager] = None
        self.btrfs_manager: Optional[BtrfsManager] = None
        self.luks_manager: Optional[LuksManager] = None

        # Track state
        self.root_device = ""
        self.root_uuid = ""
        self.efi_uuid = ""

    def partition_disk(self) -> bool:
        """Partition the target disk."""
        if not self.config.disk:
            logger.error("No disk configuration")
            return False

        self.disk_manager = DiskManager(self.config.disk)

        # Wipe disk
        if not self.disk_manager.wipe_disk():
            return False

        # Create partitions
        if not self.disk_manager.create_partitions():
            return False

        # Set root device
        self.root_device = self.disk_manager.root_partition

        logger.info("Disk partitioning complete")
        return True

    def create_filesystems(self) -> bool:
        """Create filesystems on partitions."""
        if not self.disk_manager:
            return False

        # Format EFI partition
        if self.config.disk.efi and self.disk_manager.efi_partition:
            result = run_command([
                "mkfs.fat", "-F32", "-n", "EFI",
                self.disk_manager.efi_partition,
            ])
            if not result.success:
                logger.error("Failed to format EFI partition")
                return False

            # Get EFI UUID
            result = run_command(["blkid", "-s", "UUID", "-o", "value", self.disk_manager.efi_partition])
            if result.success:
                self.efi_uuid = result.stdout.strip()

        # Handle encryption if enabled
        root_device = self.disk_manager.root_partition

        if self.config.disk.encryption and self.config.disk.encryption_password:
            self.luks_manager = LuksManager(
                root_device,
                self.config.disk.encryption_password,
            )
            if not self.luks_manager.format_luks():
                return False

            root_device = self.luks_manager.open_luks()
            if not root_device:
                return False

        # Create BTRFS filesystem
        self.btrfs_manager = BtrfsManager(
            root_device,
            self.config.disk.subvolumes,
            self.mount_point,
        )

        if not self.btrfs_manager.create_filesystem():
            return False

        # Create subvolumes
        if not self.btrfs_manager.create_subvolumes():
            return False

        # Get root UUID
        result = run_command(["blkid", "-s", "UUID", "-o", "value", root_device])
        if result.success:
            self.root_uuid = result.stdout.strip()

        logger.info("Filesystems created")
        return True

    def mount_partitions(self) -> bool:
        """Mount all partitions."""
        if not self.btrfs_manager:
            return False

        efi_part = None
        if self.disk_manager and self.disk_manager.efi_partition:
            efi_part = self.disk_manager.efi_partition

        return self.btrfs_manager.mount_subvolumes(efi_part)

    def install_base(self) -> bool:
        """Install base system."""
        # Check for live environment for fast install
        if Path("/run/archiso/airootfs").exists():
            logger.info("Live environment detected. Using fast image copy...")
            if self._install_from_live_image():
                return True
            logger.warning("Fast install failed, falling back to pacstrap...")

        import subprocess
        import os
        logger.info("Installing base system with pacstrap")

        # Read base packages
        packages = self._get_packages()
        logger.info(f"Installing {len(packages)} packages...")

        # Pre-loaded package cache location (in /opt to avoid mkarchiso cleanup)
        cache_dir = Path("/opt/shedos-pkg-cache")

        # Build pacstrap command
        cmd = ["pacstrap"]

        # Use local cache if available (for instant installation)
        if cache_dir.exists() and any(cache_dir.glob("*.pkg.tar.*")):
            pkg_count = len(list(cache_dir.glob("*.pkg.tar.*")))
            logger.info(f"Using pre-loaded package cache ({pkg_count} packages) for instant installation")
            cmd.extend(["--cachedir", str(cache_dir)])
        else:
            logger.info("Pre-loaded cache not found, downloading packages...")

        cmd.append(str(self.mount_point))
        cmd.extend(packages)

        logger.info(f"Running pacstrap with {len(packages)} packages...")

        try:
            # Set environment to avoid some gpg issues
            env = os.environ.copy()
            env["GNUPGHOME"] = "/etc/pacman.d/gnupg"

            result = subprocess.run(cmd, timeout=3600, env=env)
            if result.returncode != 0:
                logger.error(f"pacstrap failed with exit code {result.returncode}")
                return False
        except subprocess.TimeoutExpired:
            logger.error("pacstrap timed out")
            return False
        except Exception as e:
            logger.error(f"pacstrap error: {e}")
            return False

        # Initialize keyring in the new system
        logger.info("Initializing pacman keyring in new system...")
        keyring_cmds = [
            ["arch-chroot", str(self.mount_point), "pacman-key", "--init"],
            ["arch-chroot", str(self.mount_point), "pacman-key", "--populate", "archlinux"],
        ]
        for kcmd in keyring_cmds:
            subprocess.run(kcmd, timeout=300)

        # Verify installation succeeded by checking for key files
        if not (self.mount_point / "etc" / "os-release").exists():
            logger.error("Base system not installed correctly")
            return False

        logger.info("Base system installed")
        return True

    def _install_from_live_image(self) -> bool:
        """Install by copying the live image filesystem (rsync)."""
        logger.info("Copying live filesystem to target...")
        
        # We copy from root
        src = "/"
        
        # Rsync command with exclusions
        # -a: archive (recursive, symlinks, perms, times, group, owner, devices)
        # -A: ACLs
        # -X: xattrs
        # -H: hard links
        # -S: sparse files (good for disk images if any)
        cmd = [
            "rsync", "-aAXHS", "--info=progress2",
            "--exclude=/dev/*",
            "--exclude=/proc/*",
            "--exclude=/sys/*",
            "--exclude=/tmp/*",
            "--exclude=/run/*",
            "--exclude=/mnt/*",
            "--exclude=/media/*",
            "--exclude=/lost+found",
            "--exclude=/opt/shedos-pkg-cache", # Don't copy the cache bloat
            "--exclude=/etc/fstab", # Will be generated
            "--exclude=/etc/crypttab", # Will be generated if needed
            "--exclude=/etc/machine-id", # Will be generated
            "--exclude=/root/.bash_history",
            "--exclude=/home/*/.bash_history",
            src, str(self.mount_point)
        ]
        
        result = run_command(cmd, timeout=1800)
        if not result.success:
            logger.error(f"Rsync failed: {result.stderr}")
            return False

        # Cleanup live-specific artifacts
        self._cleanup_live_artifacts()

        # Copy kernel from archiso boot location if not in /boot
        # The kernel should be in the squashfs, but archiso might have it elsewhere
        kernel_dst = self.mount_point / "boot" / "vmlinuz-linux"

        if not kernel_dst.exists():
            logger.info("Kernel not found in /boot, searching archiso locations...")

            # Try multiple possible locations (install_dir can be 'shedos' or 'arch')
            archiso_locations = [
                Path("/run/archiso/bootmnt/shedos/boot/x86_64"),
                Path("/run/archiso/bootmnt/arch/boot/x86_64"),
                Path("/run/archiso/airootfs/boot"),
            ]

            for archiso_boot in archiso_locations:
                archiso_kernel = archiso_boot / "vmlinuz-linux"
                if archiso_kernel.exists():
                    logger.info(f"Found kernel at {archiso_kernel}")
                    shutil.copy2(archiso_kernel, kernel_dst)
                    logger.info(f"Copied kernel to {kernel_dst}")

                    # Also copy initramfs if available
                    for initramfs in ["initramfs-linux.img", "initramfs-linux-fallback.img"]:
                        src = archiso_boot / initramfs
                        dst = self.mount_point / "boot" / initramfs
                        if src.exists() and not dst.exists():
                            shutil.copy2(src, dst)
                            logger.info(f"Copied {initramfs}")
                    break
            else:
                logger.warning("Could not find kernel in any archiso location")

        logger.info("Filesystem copied successfully")
        return True

    def _cleanup_live_artifacts(self) -> None:
        """Remove configuration specific to the live environment."""
        # Remove cloud-init or live-user configs if they exist
        paths_to_remove = [
            self.mount_point / "etc/systemd/system/getty@tty1.service.d/autologin.conf",
            self.mount_point / "etc/sudoers.d/g_wheel", # Archiso default
            self.mount_point / "root/.automated_script.sh",
            self.mount_point / "root/.zlogin",
        ]

        for p in paths_to_remove:
            if p.exists():
                try:
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                except Exception as e:
                    logger.warning(f"Failed to remove {p}: {e}")

        # Remove archiso-specific mkinitcpio files
        archiso_preset = self.mount_point / "etc" / "mkinitcpio.d" / "archiso.preset"
        if archiso_preset.exists():
            try:
                archiso_preset.unlink()
                logger.info("Removed archiso mkinitcpio preset")
            except Exception as e:
                logger.warning(f"Failed to remove archiso preset: {e}")

        # Ensure standard linux preset exists with correct configuration
        preset_dir = self.mount_point / "etc" / "mkinitcpio.d"
        preset_dir.mkdir(parents=True, exist_ok=True)
        linux_preset = preset_dir / "linux.preset"

        # Always write the correct preset for installed system
        linux_preset_content = """# mkinitcpio preset file for the 'linux' package

ALL_config="/etc/mkinitcpio.conf"
ALL_kver="/boot/vmlinuz-linux"

PRESETS=('default' 'fallback')

default_image="/boot/initramfs-linux.img"

fallback_options="-S autodetect"
"""
        try:
            linux_preset.write_text(linux_preset_content)
            logger.info("Created standard linux mkinitcpio preset")
        except Exception as e:
            logger.warning(f"Failed to write linux preset: {e}")

        # Re-create empty directories for mount points
        for d in ["dev", "proc", "sys", "tmp", "run", "mnt"]:
            (self.mount_point / d).mkdir(exist_ok=True)
        (self.mount_point / "tmp").chmod(0o1777)

    def generate_fstab(self) -> bool:
        """Generate fstab file."""
        logger.info("Generating fstab")

        result = run_command(["genfstab", "-U", str(self.mount_point)])
        if not result.success:
            logger.error("Failed to generate fstab")
            return False

        fstab_path = self.mount_point / "etc" / "fstab"
        try:
            fstab_path.write_text(result.stdout)
            logger.info("fstab generated")
            return True
        except Exception as e:
            logger.error(f"Failed to write fstab: {e}")
            return False

    def configure_system(self) -> bool:
        """Configure the installed system."""
        logger.info("Configuring system")

        # Set timezone
        run_chroot([
            "ln", "-sf",
            f"/usr/share/zoneinfo/{self.config.system.timezone}",
            "/etc/localtime",
        ], str(self.mount_point))
        run_chroot(["hwclock", "--systohc"], str(self.mount_point))

        # Set locale
        locale_gen = self.mount_point / "etc" / "locale.gen"
        content = locale_gen.read_text()
        content = content.replace(f"#{self.config.system.locale}", self.config.system.locale)
        locale_gen.write_text(content)
        run_chroot(["locale-gen"], str(self.mount_point))

        locale_conf = self.mount_point / "etc" / "locale.conf"
        locale_conf.write_text(f"LANG={self.config.system.locale}\n")

        # Set hostname
        hostname_file = self.mount_point / "etc" / "hostname"
        hostname_file.write_text(f"{self.config.system.hostname}\n")

        # Set hosts file
        hosts_file = self.mount_point / "etc" / "hosts"
        hosts_content = f"""127.0.0.1       localhost
::1             localhost
127.0.1.1       {self.config.system.hostname}.localdomain {self.config.system.hostname}
"""
        hosts_file.write_text(hosts_content)

        # Configure sudoers
        sudoers_dir = self.mount_point / "etc" / "sudoers.d"
        sudoers_dir.mkdir(exist_ok=True)
        wheel_sudoers = sudoers_dir / "wheel"
        wheel_sudoers.write_text("%wheel ALL=(ALL:ALL) ALL\n")
        wheel_sudoers.chmod(0o440)

        # Add crypttab entry if using encryption
        if self.luks_manager:
            self.luks_manager.add_to_crypttab(str(self.mount_point))

        logger.info("System configured")
        return True

    def install_bootloader(self) -> bool:
        """Install Limine bootloader."""
        logger.info("Installing bootloader")

        # Detect NVIDIA
        gpus = get_gpus()
        has_nvidia = any(gpu.is_nvidia for gpu in gpus)

        luks_uuid = None
        if self.luks_manager:
            luks_uuid = self.luks_manager.get_uuid()

        limine = LimineInstaller(
            mount_point=str(self.mount_point),
            root_uuid=self.root_uuid,
            luks_uuid=luks_uuid,
            nvidia=has_nvidia and self.config.install_nvidia,
        )

        disk_device = self.config.disk.device if self.config.disk else ""

        if not limine.install(disk_device):
            return False

        if not limine.configure_mkinitcpio():
            return False

        logger.info("Bootloader installed")
        return True

    def create_user(self) -> bool:
        """Create user account."""
        if not self.config.user:
            logger.error("No user configuration")
            return False

        user = self.config.user
        logger.info(f"Creating user: {user.username}")

        # Create user with groups
        groups = ",".join(user.groups)
        result = run_chroot([
            "useradd", "-m",
            "-G", groups,
            "-s", user.shell,
            "-c", user.full_name or user.username,
            user.username,
        ], str(self.mount_point))

        if not result.success:
            logger.error(f"Failed to create user: {result.stderr}")
            return False

        # Set password — pass user:pass via stdin to chpasswd. Going
        # through `sh -c "echo ... | chpasswd"` would interpolate the
        # password into a shell string, which breaks (or worse, executes
        # arbitrary code) for passwords containing apostrophes / dollar
        # signs / backticks.
        result = run_command(
            ["arch-chroot", str(self.mount_point), "chpasswd"],
            input=f"{user.username}:{user.password}\n",
        )

        if not result.success:
            logger.error("Failed to set user password")
            return False

        # Configure git for user
        self._configure_git(user)

        logger.info(f"User {user.username} created")
        return True

    def _configure_git(self, user) -> None:
        """Configure git for the user."""
        git_name = user.full_name or user.username
        git_email = user.email

        if git_name:
            run_command([
                "arch-chroot", str(self.mount_point),
                "su", "-", user.username, "-c",
                f'git config --global user.name "{git_name}"'
            ])
            logger.info(f"Git user.name set to: {git_name}")

        if git_email:
            run_command([
                "arch-chroot", str(self.mount_point),
                "su", "-", user.username, "-c",
                f'git config --global user.email "{git_email}"'
            ])
            logger.info(f"Git user.email set to: {git_email}")

        # Set sensible git defaults
        git_defaults = [
            ("init.defaultBranch", "main"),
            ("core.editor", "nvim"),
            ("pull.rebase", "false"),
        ]
        for key, value in git_defaults:
            run_command([
                "arch-chroot", str(self.mount_point),
                "su", "-", user.username, "-c",
                f'git config --global {key} "{value}"'
            ])

    def install_packages(self) -> bool:
        """Install additional packages for selected profile."""
        logger.info("Installing profile packages")

        # Get AUR packages separately
        packages = self._get_packages(include_base=False)
        aur_packages = self._get_aur_packages()

        # Pre-loaded package cache location (in /opt to avoid mkarchiso cleanup)
        cache_dir = Path("/opt/shedos-pkg-cache")

        if packages:
            cmd = ["pacman", "-S", "--noconfirm", "--needed"]

            # Use local cache if available
            if cache_dir.exists() and any(cache_dir.glob("*.pkg.tar.*")):
                cmd.extend(["--cachedir", str(cache_dir)])

            cmd.extend(packages)

            result = run_chroot(
                cmd,
                str(self.mount_point),
                timeout=1800,
            )
            if not result.success:
                logger.warning(f"Some packages may have failed: {result.stderr}")

        # Install yay for AUR
        if self.config.enable_aur and aur_packages:
            self._install_yay()
            self._install_aur_packages(aur_packages)

        logger.info("Package installation complete")
        return True

    def copy_configs(self) -> bool:
        """Copy configuration files to installed system."""
        logger.info("Copying configurations")

        # Source and destination mappings
        config_mappings = [
            ("hyprland", ".config/hypr"),
            ("waybar", ".config/waybar"),
            ("walker", ".config/walker"),
            ("kitty", ".config/kitty"),
            ("mako", ".config/mako"),
            ("nvim", ".config/nvim"),
            ("zsh", ""),  # Special handling
        ]

        if not self.config.user:
            return False

        user_home = self.mount_point / "home" / self.config.user.username

        for src_name, dest_rel in config_mappings:
            src_path = CONFIG_DIR / src_name
            if not src_path.exists():
                continue

            if dest_rel:
                dest_path = user_home / dest_rel
            else:
                dest_path = user_home

            dest_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                if src_path.is_dir():
                    shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_path, dest_path)
                logger.debug(f"Copied {src_name} to {dest_path}")
            except Exception as e:
                logger.warning(f"Failed to copy {src_name}: {e}")

        # Fix ownership
        run_chroot([
            "chown", "-R",
            f"{self.config.user.username}:{self.config.user.username}",
            f"/home/{self.config.user.username}",
        ], str(self.mount_point))

        logger.info("Configurations copied")
        return True

    def enable_services(self) -> bool:
        """Enable system services."""
        logger.info("Enabling services")

        services = [
            "NetworkManager",
            "bluetooth",
            "greetd",
            "fstrim.timer",
        ]

        # Add optional services
        if self.config.install_nvidia:
            services.extend([
                "nvidia-suspend",
                "nvidia-hibernate",
                "nvidia-resume",
            ])

        # Database services
        services.extend(["postgresql", "redis"])

        for service in services:
            result = run_chroot(
                ["systemctl", "enable", service],
                str(self.mount_point),
            )
            if not result.success:
                logger.warning(f"Failed to enable {service}")

        logger.info("Services enabled")
        return True

    def finalize(self) -> bool:
        """Finalize installation."""
        logger.info("Finalizing installation")

        # Sync
        run_command(["sync"])

        # Unmount
        if self.btrfs_manager:
            self.btrfs_manager.unmount_all()

        # Close LUKS
        if self.luks_manager:
            self.luks_manager.close_luks()

        logger.info("Installation finalized")
        return True

    def _get_packages(self, include_base: bool = True) -> list[str]:
        """Get list of packages to install."""
        packages: list[str] = []

        package_files = PROFILE_PACKAGES.get(self.config.profile, [])

        for pkg_file in package_files:
            if not include_base and pkg_file == "base.txt":
                continue

            pkg_path = PACKAGE_DIR / pkg_file
            if pkg_path.exists():
                content = pkg_path.read_text()
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        packages.append(line)

        # Add NVIDIA packages if needed
        if self.config.install_nvidia:
            nvidia_path = PACKAGE_DIR / "nvidia.txt"
            if nvidia_path.exists():
                content = nvidia_path.read_text()
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        packages.append(line)

        return list(set(packages))  # Remove duplicates

    def _get_aur_packages(self) -> list[str]:
        """Get list of AUR packages."""
        packages: list[str] = []

        aur_path = PACKAGE_DIR / "aur.txt"
        if aur_path.exists():
            content = aur_path.read_text()
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    packages.append(line)

        return packages

    def _install_yay(self) -> bool:
        """Install yay AUR helper."""
        logger.info("Installing yay AUR helper")

        # Clone and build yay as user
        if not self.config.user:
            return False

        username = self.config.user.username

        commands = [
            "cd /tmp && git clone https://aur.archlinux.org/yay-bin.git",
            "cd /tmp/yay-bin && makepkg -si --noconfirm",
            "rm -rf /tmp/yay-bin",
        ]

        for cmd in commands:
            result = run_command([
                "arch-chroot", str(self.mount_point),
                "su", "-", username, "-c", cmd,
            ])
            if not result.success:
                logger.error(
                    "yay bootstrap step failed (%s): %s", cmd, result.stderr
                )
                return False

        return True

    def _install_aur_packages(self, packages: list[str]) -> bool:
        """Install AUR packages using yay."""
        if not packages or not self.config.user:
            return True

        logger.info(f"Installing {len(packages)} AUR packages")

        username = self.config.user.username
        # `su -c` takes a single shell command, so we can't avoid the
        # shell here. Defense in depth: shlex.quote each package name
        # so a list entry containing whitespace or shell metacharacters
        # can't break out of the yay invocation.
        pkg_str = " ".join(shlex.quote(p) for p in packages)

        result = run_command([
            "arch-chroot", str(self.mount_point),
            "su", "-", username, "-c",
            f"yay -S --noconfirm --needed {pkg_str}",
        ], timeout=3600)

        return result.success
