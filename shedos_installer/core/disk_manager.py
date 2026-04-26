"""Disk management operations for ShedOS installer."""

import logging
from pathlib import Path
from typing import Optional

from shedos_installer.config import DiskConfig
from shedos_installer.utils.command import run_command
from shedos_installer.utils.hardware import is_uefi

logger = logging.getLogger(__name__)


class DiskManager:
    """Handles disk partitioning operations."""

    def __init__(self, config: DiskConfig) -> None:
        """Initialize disk manager."""
        self.config = config
        self.device = config.device

    def wipe_disk(self) -> bool:
        """Wipe all partitions and signatures from disk."""
        logger.info(f"Wiping disk: {self.device}")

        # Wipe filesystem signatures
        result = run_command(["wipefs", "-a", self.device])
        if not result.success:
            logger.error(f"Failed to wipe disk signatures: {result.stderr}")
            return False

        # Zero out the head of the disk (kills GPT/MBR + LVM headers).
        # The `seek=0 conv=notrunc` second pass overwrites the same
        # region without truncating any subsequent partition table.
        # A failed dd here means the device is read-only or has bad
        # blocks at offset 0 — neither is recoverable by partitioning,
        # so abort rather than report success.
        for dd_cmd in (
            ["dd", "if=/dev/zero", f"of={self.device}", "bs=1M", "count=100"],
            ["dd", "if=/dev/zero", f"of={self.device}", "bs=1M",
             "count=100", "seek=0", "conv=notrunc"],
        ):
            dd_result = run_command(dd_cmd)
            if not dd_result.success:
                logger.error(
                    f"Failed to zero disk head: {dd_result.stderr}"
                )
                return False

        # sync is best-effort — failure is logged but doesn't fail the
        # wipe, since the only non-success case is "no devices to sync"
        # which is benign.
        sync_result = run_command(["sync"])
        if not sync_result.success:
            logger.warning(f"sync after wipe returned non-zero: {sync_result.stderr}")

        logger.info("Disk wiped successfully")
        return True

    def create_partitions(self) -> bool:
        """Create partition table and partitions."""
        logger.info(f"Creating partitions on {self.device}")

        # Determine partition table type
        table_type = "gpt" if self.config.efi else "msdos"

        # Create partition table
        result = run_command(["parted", "-s", self.device, "mklabel", table_type])
        if not result.success:
            logger.error(f"Failed to create partition table: {result.stderr}")
            return False

        if self.config.efi:
            success = self._create_uefi_partitions()
        else:
            success = self._create_bios_partitions()

        if success:
            # Inform kernel of partition changes
            run_command(["partprobe", self.device])
            run_command(["sync"])
            # Wait for udev to settle
            run_command(["udevadm", "settle"])

        return success

    def _create_uefi_partitions(self) -> bool:
        """Create UEFI partition layout."""
        logger.info("Creating UEFI partition layout")

        commands = [
            # EFI partition (512MB)
            ["parted", "-s", self.device, "mkpart", "primary", "fat32", "1MiB", "513MiB"],
            ["parted", "-s", self.device, "set", "1", "esp", "on"],
            # Root partition (rest of disk)
            ["parted", "-s", self.device, "mkpart", "primary", "btrfs", "513MiB", "100%"],
        ]

        for cmd in commands:
            result = run_command(cmd)
            if not result.success:
                logger.error(f"Partition command failed: {' '.join(cmd)}")
                return False

        logger.info("UEFI partitions created")
        return True

    def _create_bios_partitions(self) -> bool:
        """Create BIOS partition layout."""
        logger.info("Creating BIOS partition layout")

        commands = [
            # BIOS boot partition (2MB)
            ["parted", "-s", self.device, "mkpart", "primary", "1MiB", "3MiB"],
            ["parted", "-s", self.device, "set", "1", "bios_grub", "on"],
            # Root partition (rest of disk)
            ["parted", "-s", self.device, "mkpart", "primary", "btrfs", "3MiB", "100%"],
        ]

        for cmd in commands:
            result = run_command(cmd)
            if not result.success:
                logger.error(f"Partition command failed: {' '.join(cmd)}")
                return False

        logger.info("BIOS partitions created")
        return True

    def get_partition_path(self, number: int) -> str:
        """Get the path to a partition by number."""
        # Handle nvme and regular disk naming
        if "nvme" in self.device or "mmcblk" in self.device:
            return f"{self.device}p{number}"
        return f"{self.device}{number}"

    @property
    def efi_partition(self) -> Optional[str]:
        """Get EFI partition path."""
        if self.config.efi:
            return self.get_partition_path(1)
        return None

    @property
    def root_partition(self) -> str:
        """Get root partition path."""
        return self.get_partition_path(2 if self.config.efi else 2)

    @property
    def boot_partition(self) -> Optional[str]:
        """Get boot partition path (BIOS only)."""
        if not self.config.efi:
            return self.get_partition_path(1)
        return None
