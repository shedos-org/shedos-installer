"""Main orchestrator for ShedOS installer."""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from shedos_installer.config import InstallConfig, InstallProfile
from shedos_installer.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="ShedOS Installer - Calamares Graphical Installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  shedos-installer              Start the Calamares graphical installer
  shedos-installer --debug      Start with debug logging enabled
        """,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=Path("/var/log/shedos-installer.log"),
        help="Log file path (default: /var/log/shedos-installer.log)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate installation without making changes (not supported with Calamares)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.2.0",
    )
    return parser.parse_args()


def check_requirements() -> bool:
    """Check if system meets requirements for installation."""
    errors: list[str] = []

    # Check if running as root
    if os.geteuid() != 0:
        errors.append("Installer must be run as root")

    # Check for Calamares
    import shutil
    if shutil.which("calamares") is None:
        errors.append("Calamares not found. Please install calamares package.")

    # Check for required commands used by custom modules
    required_commands = ["pacstrap", "genfstab", "arch-chroot", "mkfs.btrfs", "parted", "rsync"]
    for cmd in required_commands:
        if shutil.which(cmd) is None:
            errors.append(f"Required command not found: {cmd}")

    if errors:
        for error in errors:
            logger.error(error)
        return False
    return True


def launch_calamares(debug: bool = False) -> int:
    """Launch Calamares graphical installer."""
    cmd = ["calamares"]

    if debug:
        cmd.append("-d")  # Debug mode

    logger.info(f"Launching Calamares: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except FileNotFoundError:
        logger.error("Calamares executable not found")
        print("Error: Calamares is not installed. Please install it first.")
        return 1
    except Exception as e:
        logger.exception(f"Failed to launch Calamares: {e}")
        return 1


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(args.log_file, log_level)

    logger.info("Starting ShedOS Installer")

    # Warn about dry-run
    if args.dry_run:
        logger.warning("--dry-run is not supported with Calamares installer")
        print("Warning: --dry-run is not supported with Calamares. Ignoring.")

    # Check requirements
    if not check_requirements():
        print("Error: System requirements not met. Check the log for details.")
        return 1

    # Launch Calamares
    try:
        return launch_calamares(debug=args.debug)
    except KeyboardInterrupt:
        logger.info("Installation cancelled by user")
        print("\nInstallation cancelled.")
        return 130
    except Exception as e:
        logger.exception("Unexpected error during installation")
        print(f"\nError: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
