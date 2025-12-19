"""LUKS encryption management for ShedOS installer."""

import logging
from typing import Optional

from shedos_installer.utils.command import run_command

logger = logging.getLogger(__name__)


class LuksManager:
    """Handles LUKS encryption operations."""

    MAPPER_NAME = "cryptroot"

    def __init__(self, device: str, password: str) -> None:
        """Initialize LUKS manager."""
        self.device = device
        self.password = password
        self.mapper_path = f"/dev/mapper/{self.MAPPER_NAME}"

    def format_luks(self) -> bool:
        """Format device with LUKS encryption."""
        logger.info(f"Formatting {self.device} with LUKS")

        # Create LUKS container
        # Using echo to pipe password is not ideal, but works for installer
        result = run_command([
            "sh", "-c",
            f"echo -n '{self.password}' | cryptsetup luksFormat --type luks2 "
            f"--cipher aes-xts-plain64 --key-size 512 --hash sha512 "
            f"--iter-time 5000 --use-urandom {self.device} -"
        ])

        if not result.success:
            logger.error(f"Failed to format LUKS: {result.stderr}")
            return False

        logger.info("LUKS container created")
        return True

    def open_luks(self) -> Optional[str]:
        """Open LUKS container and return mapper device path."""
        logger.info(f"Opening LUKS container on {self.device}")

        result = run_command([
            "sh", "-c",
            f"echo -n '{self.password}' | cryptsetup open {self.device} {self.MAPPER_NAME} -"
        ])

        if not result.success:
            logger.error(f"Failed to open LUKS: {result.stderr}")
            return None

        logger.info(f"LUKS container opened at {self.mapper_path}")
        return self.mapper_path

    def close_luks(self) -> bool:
        """Close LUKS container."""
        logger.info("Closing LUKS container")

        result = run_command(["cryptsetup", "close", self.MAPPER_NAME])

        if not result.success:
            logger.error(f"Failed to close LUKS: {result.stderr}")
            return False

        logger.info("LUKS container closed")
        return True

    def get_uuid(self) -> Optional[str]:
        """Get the UUID of the LUKS container."""
        result = run_command(["cryptsetup", "luksUUID", self.device])

        if result.success:
            return result.stdout.strip()
        return None

    def add_to_crypttab(self, mount_point: str) -> bool:
        """Add entry to /etc/crypttab."""
        uuid = self.get_uuid()
        if not uuid:
            logger.error("Could not get LUKS UUID")
            return False

        crypttab_path = f"{mount_point}/etc/crypttab"
        entry = f"{self.MAPPER_NAME}  UUID={uuid}  none  luks\n"

        try:
            with open(crypttab_path, "a") as f:
                f.write(entry)
            logger.info("Added crypttab entry")
            return True
        except Exception as e:
            logger.error(f"Failed to write crypttab: {e}")
            return False
