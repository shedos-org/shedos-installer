"""BTRFS subvolume management for ShedOS installer."""

import logging
from pathlib import Path
from typing import Optional

from shedos_installer.config import (
    BtrfsSubvolume,
    DEFAULT_SUBVOLUMES,
    DEFAULT_BTRFS_MOUNT_OPTIONS,
    MOUNT_POINT,
)
from shedos_installer.utils.command import run_command

logger = logging.getLogger(__name__)


class BtrfsManager:
    """Handles BTRFS filesystem and subvolume operations."""

    def __init__(
        self,
        device: str,
        subvolumes: Optional[list[BtrfsSubvolume]] = None,
        mount_point: Path = MOUNT_POINT,
    ) -> None:
        """Initialize BTRFS manager."""
        self.device = device
        self.subvolumes = subvolumes or DEFAULT_SUBVOLUMES.copy()
        self.mount_point = mount_point

    def create_filesystem(self, label: str = "ShedOS") -> bool:
        """Create BTRFS filesystem on device."""
        logger.info(f"Creating BTRFS filesystem on {self.device}")

        # Ensure device exists
        from pathlib import Path
        if not Path(self.device).exists():
            logger.error(f"Device {self.device} does not exist")
            return False

        result = run_command([
            "mkfs.btrfs",
            "-f",  # Force
            "-L", label,
            self.device,
        ])

        if not result.success:
            logger.error(f"Failed to create BTRFS: {result.stderr}")
            return False

        # Wait for udev to recognize new filesystem
        run_command(["udevadm", "settle"])
        run_command(["sync"])

        logger.info("BTRFS filesystem created")
        return True

    def create_subvolumes(self) -> bool:
        """Create all configured subvolumes."""
        logger.info(f"Creating BTRFS subvolumes on {self.device}")

        # First mount the root filesystem
        self.mount_point.mkdir(parents=True, exist_ok=True)

        # Wait a moment for device to be ready
        import time
        time.sleep(1)

        logger.info(f"Mounting {self.device} at {self.mount_point}")
        result = run_command([
            "mount",
            "-t", "btrfs",
            "-o", "compress=zstd:1",
            self.device,
            str(self.mount_point),
        ])

        if not result.success:
            logger.error(f"Failed to mount {self.device} for subvolume creation: {result.stderr}")
            return False

        try:
            # Create each subvolume
            for subvol in self.subvolumes:
                subvol_path = self.mount_point / subvol.name.lstrip("@")
                if subvol.name == "@":
                    subvol_path = self.mount_point / "@"

                result = run_command([
                    "btrfs", "subvolume", "create",
                    str(self.mount_point / subvol.name),
                ])

                if not result.success:
                    logger.error(f"Failed to create subvolume {subvol.name}: {result.stderr}")
                    return False

                logger.debug(f"Created subvolume: {subvol.name}")

                # Disable CoW for subvolumes that don't need it
                if not subvol.cow:
                    run_command([
                        "chattr", "+C",
                        str(self.mount_point / subvol.name),
                    ])
                    logger.debug(f"Disabled CoW for: {subvol.name}")

            logger.info(f"Created {len(self.subvolumes)} subvolumes")
            return True

        finally:
            # Unmount
            run_command(["umount", str(self.mount_point)])

    def mount_subvolumes(self, efi_partition: Optional[str] = None) -> bool:
        """Mount all subvolumes to their mount points."""
        logger.info("Mounting BTRFS subvolumes")

        # Sort subvolumes by mountpoint depth (root first)
        sorted_subvols = sorted(
            self.subvolumes,
            key=lambda s: s.mountpoint.count("/"),
        )

        for subvol in sorted_subvols:
            mount_path = self.mount_point / subvol.mountpoint.lstrip("/")
            mount_path.mkdir(parents=True, exist_ok=True)

            # Build mount options
            options = f"subvol={subvol.name},{DEFAULT_BTRFS_MOUNT_OPTIONS}"

            result = run_command([
                "mount",
                "-t", "btrfs",
                "-o", options,
                self.device,
                str(mount_path),
            ])

            if not result.success:
                logger.error(f"Failed to mount {subvol.name}: {result.stderr}")
                return False

            logger.debug(f"Mounted {subvol.name} at {mount_path}")

        # Mount EFI partition if present
        if efi_partition:
            efi_mount = self.mount_point / "boot" / "efi"
            efi_mount.mkdir(parents=True, exist_ok=True)

            result = run_command([
                "mount",
                efi_partition,
                str(efi_mount),
            ])

            if not result.success:
                logger.error(f"Failed to mount EFI partition: {result.stderr}")
                return False

            logger.debug(f"Mounted EFI partition at {efi_mount}")

        logger.info("All subvolumes mounted")
        return True

    def unmount_all(self) -> bool:
        """Unmount all mounted subvolumes."""
        logger.info("Unmounting all subvolumes")

        # Sort by depth (deepest first)
        sorted_subvols = sorted(
            self.subvolumes,
            key=lambda s: s.mountpoint.count("/"),
            reverse=True,
        )

        # First unmount EFI
        efi_mount = self.mount_point / "boot" / "efi"
        if efi_mount.exists():
            run_command(["umount", str(efi_mount)])

        # Unmount subvolumes
        for subvol in sorted_subvols:
            mount_path = self.mount_point / subvol.mountpoint.lstrip("/")
            if mount_path.exists():
                run_command(["umount", str(mount_path)])

        logger.info("All subvolumes unmounted")
        return True

    def generate_fstab_entries(self, uuid: str, efi_uuid: Optional[str] = None) -> list[str]:
        """Generate fstab entries for all subvolumes."""
        entries = [
            "# /etc/fstab: static file system information.",
            "# <file system> <mount point> <type> <options> <dump> <pass>",
            "",
        ]

        # Sort subvolumes by mountpoint
        sorted_subvols = sorted(
            self.subvolumes,
            key=lambda s: s.mountpoint.count("/"),
        )

        for subvol in sorted_subvols:
            options = f"subvol={subvol.name},{DEFAULT_BTRFS_MOUNT_OPTIONS}"
            pass_num = 0  # BTRFS doesn't need fsck

            entry = f"UUID={uuid}  {subvol.mountpoint}  btrfs  {options}  0 {pass_num}"
            entries.append(entry)

        # EFI partition
        if efi_uuid:
            entries.append("")
            entries.append(f"UUID={efi_uuid}  /boot/efi  vfat  umask=0077  0 2")

        # tmpfs for /tmp if not using @temp subvolume
        entries.append("")
        entries.append("# tmpfs")
        entries.append("tmpfs  /tmp  tmpfs  defaults,noatime,mode=1777  0 0")

        return entries
