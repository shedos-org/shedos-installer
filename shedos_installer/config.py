"""Configuration data classes for ShedOS installer."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class InstallProfile(Enum):
    """Installation profiles."""
    MINIMAL = "minimal"
    BASE = "base"
    DESKTOP = "desktop"
    DEVELOPER = "developer"
    FULL = "full"


class BootloaderType(Enum):
    """Bootloader types."""
    LIMINE = "limine"


class FilesystemType(Enum):
    """Filesystem types."""
    BTRFS = "btrfs"
    EXT4 = "ext4"


@dataclass
class BtrfsSubvolume:
    """BTRFS subvolume configuration."""
    name: str
    mountpoint: str
    cow: bool = True
    description: str = ""


# Default BTRFS subvolume layout
DEFAULT_SUBVOLUMES: list[BtrfsSubvolume] = [
    BtrfsSubvolume("@", "/", True, "Root filesystem"),
    BtrfsSubvolume("@home", "/home", True, "User data"),
    BtrfsSubvolume("@var", "/var", True, "Variable data"),
    BtrfsSubvolume("@snapshots", "/.snapshots", True, "Snapper snapshots"),
    BtrfsSubvolume("@log", "/var/log", False, "System logs"),
    BtrfsSubvolume("@cache", "/var/cache", False, "Cache files"),
    BtrfsSubvolume("@temp", "/tmp", False, "Temporary files"),
    BtrfsSubvolume("@pkg", "/var/cache/pacman/pkg", False, "Package cache"),
    BtrfsSubvolume("@srv", "/srv", True, "Server data"),
    BtrfsSubvolume("@opt", "/opt", True, "Optional software"),
    BtrfsSubvolume("@libvirt", "/var/lib/libvirt", False, "VM images"),
    BtrfsSubvolume("@docker", "/var/lib/docker", False, "Docker data"),
    BtrfsSubvolume("@database", "/var/lib/database", False, "Database storage"),
]

# Default BTRFS mount options
DEFAULT_BTRFS_MOUNT_OPTIONS = "compress=zstd:1,noatime,ssd,discard=async"


@dataclass
class DiskPartition:
    """Disk partition configuration."""
    device: str
    size_mb: int
    filesystem: str
    mountpoint: str
    label: str = ""
    flags: list[str] = field(default_factory=list)


@dataclass
class DiskConfig:
    """Disk configuration."""
    device: str
    efi: bool = True
    encryption: bool = False
    encryption_password: Optional[str] = None
    partitions: list[DiskPartition] = field(default_factory=list)
    subvolumes: list[BtrfsSubvolume] = field(default_factory=lambda: DEFAULT_SUBVOLUMES.copy())


@dataclass
class UserConfig:
    """User configuration."""
    username: str
    password: str
    full_name: str = ""
    email: str = ""
    groups: list[str] = field(default_factory=lambda: ["wheel", "video", "audio", "input", "storage"])
    shell: str = "/usr/bin/zsh"


@dataclass
class NetworkConfig:
    """Network configuration."""
    wifi_ssid: Optional[str] = None
    wifi_password: Optional[str] = None
    connection_type: str = "none"  # "ethernet", "wifi", "none"


@dataclass
class SystemConfig:
    """System configuration."""
    hostname: str = "shedos"
    locale: str = "en_US.UTF-8"
    timezone: str = "UTC"
    keyboard: str = "us"


@dataclass
class InstallConfig:
    """Complete installation configuration."""
    profile: InstallProfile = InstallProfile.DEVELOPER
    disk: Optional[DiskConfig] = None
    user: Optional[UserConfig] = None
    network: Optional[NetworkConfig] = None
    system: SystemConfig = field(default_factory=SystemConfig)
    bootloader: BootloaderType = BootloaderType.LIMINE
    install_nvidia: bool = True
    enable_aur: bool = True
    enable_flatpak: bool = True


# Paths
INSTALLER_DIR = Path("/opt/shedos-installer")
# Package lists are shipped with the Python package
PACKAGE_DIR = Path(__file__).parent / "packages"
CONFIG_DIR = INSTALLER_DIR / "configs"
MOUNT_POINT = Path("/mnt")


# Package list files for each profile
PROFILE_PACKAGES: dict[InstallProfile, list[str]] = {
    InstallProfile.MINIMAL: ["base.txt"],
    InstallProfile.BASE: ["base.txt", "audio.txt", "fonts.txt"],
    InstallProfile.DESKTOP: [
        "base.txt", "audio.txt", "fonts.txt", "desktop.txt",
    ],
    InstallProfile.DEVELOPER: [
        "base.txt", "audio.txt", "fonts.txt", "desktop.txt",
        "system-programming.txt", "development.txt", "devops.txt",
        "databases.txt", "tui-tools.txt",
    ],
    InstallProfile.FULL: [
        "base.txt", "audio.txt", "fonts.txt", "desktop.txt",
        "system-programming.txt", "development.txt", "devops.txt",
        "cloud-cli.txt", "databases.txt", "ai-ml.txt", "media.txt",
        "browsers.txt", "office.txt", "communication.txt", "privacy.txt",
        "utilities.txt", "virtualization.txt", "network-tools.txt",
        "tui-tools.txt", "api-testing.txt", "power-mgmt.txt",
        "printing.txt", "music.txt",
    ],
}
