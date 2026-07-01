"""Hardware detection utilities for ShedOS installer."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from shedos_installer.utils.command import run_command

logger = logging.getLogger(__name__)


@dataclass
class DiskInfo:
    """Information about a disk device."""
    device: str
    size_bytes: int
    size_human: str
    model: str
    serial: str
    removable: bool
    partitions: list[str]

    @property
    def size_gb(self) -> float:
        """Return size in gigabytes."""
        return self.size_bytes / (1024**3)


@dataclass
class PartitionInfo:
    """Information about a partition."""
    device: str
    size_bytes: int
    filesystem: str
    label: str
    mountpoint: Optional[str]
    uuid: str


@dataclass
class GpuInfo:
    """Information about a GPU."""
    vendor: str
    model: str
    pci_id: str
    driver: str
    is_nvidia: bool
    nvidia_series: Optional[str]  # e.g., "GeForce RTX 30", "GeForce GTX 10"
    pci_addr: str = ""            # PCI bus address, e.g. "0000:01:00.0"


def get_disks() -> list[DiskInfo]:
    """Get list of available disks."""
    disks: list[DiskInfo] = []

    # Use lsblk to get disk information
    result = run_command([
        "lsblk", "-J", "-b", "-o",
        "NAME,SIZE,MODEL,SERIAL,RM,TYPE,MOUNTPOINT"
    ])

    if not result.success:
        logger.error("Failed to get disk information")
        return disks

    import json
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.error("Failed to parse lsblk output")
        return disks

    for device in data.get("blockdevices", []):
        if device.get("type") != "disk":
            continue

        # Skip loop devices and other non-physical devices
        name = device.get("name", "")
        if name.startswith(("loop", "sr", "zram")):
            continue

        partitions = []
        for child in device.get("children", []):
            if child.get("type") == "part":
                partitions.append(f"/dev/{child['name']}")

        disk = DiskInfo(
            device=f"/dev/{name}",
            size_bytes=int(device.get("size", 0)),
            size_human=_format_size(int(device.get("size", 0))),
            model=(device.get("model") or "").strip() or "Unknown",
            serial=(device.get("serial") or "").strip() or "Unknown",
            removable=device.get("rm", False),
            partitions=partitions,
        )
        disks.append(disk)
        logger.debug(f"Found disk: {disk.device} ({disk.size_human})")

    return disks


def get_partitions(device: str) -> list[PartitionInfo]:
    """Get partitions on a disk."""
    partitions: list[PartitionInfo] = []

    result = run_command([
        "lsblk", "-J", "-b", "-o",
        "NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT,UUID", device
    ])

    if not result.success:
        return partitions

    import json
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return partitions

    for dev in data.get("blockdevices", []):
        for child in dev.get("children", []):
            if child.get("type", "part") == "part":
                partitions.append(PartitionInfo(
                    device=f"/dev/{child['name']}",
                    size_bytes=int(child.get("size", 0)),
                    filesystem=child.get("fstype", "") or "",
                    label=child.get("label", "") or "",
                    mountpoint=child.get("mountpoint"),
                    uuid=child.get("uuid", "") or "",
                ))

    return partitions


def get_gpus() -> list[GpuInfo]:
    """Detect GPUs in the system."""
    gpus: list[GpuInfo] = []

    # Use lspci to find GPUs
    result = run_command(["lspci", "-Dnn"])
    if not result.success:
        return gpus

    # GPUs enumerate under three PCI classes: VGA compatible controller [0300],
    # 3D controller [0302] (muxless Optimus dGPUs), and Display controller [0380].
    gpu_pattern = re.compile(
        r"([0-9a-f:\.]+)\s+(?:VGA compatible controller|3D controller|"
        r"Display controller).*?:\s+(.*?)\s+\[([0-9a-f:]+)\]",
        re.IGNORECASE
    )

    for line in result.stdout.splitlines():
        match = gpu_pattern.search(line)
        if match:
            pci_addr = match.group(1)
            description = match.group(2)
            vendor_device = match.group(3)

            is_nvidia = "nvidia" in description.lower()
            nvidia_series = None
            driver = "unknown"

            if is_nvidia:
                driver = "nvidia"
                # Try to detect NVIDIA series
                if any(x in description for x in ["RTX 50", "RTX 5"]):
                    nvidia_series = "Blackwell"
                elif any(x in description for x in ["RTX 40", "RTX 4"]):
                    nvidia_series = "Ada Lovelace"
                elif any(x in description for x in ["RTX 30", "RTX 3"]):
                    nvidia_series = "Ampere"
                elif any(x in description for x in ["RTX 20", "RTX 2", "GTX 16"]):
                    nvidia_series = "Turing"
                elif any(x in description for x in ["GTX 10", "GTX 9"]):
                    nvidia_series = "Pascal/Maxwell"
            elif "amd" in description.lower() or "radeon" in description.lower():
                driver = "amdgpu"
            elif "intel" in description.lower():
                driver = "i915"

            # Determine vendor
            if is_nvidia:
                vendor = "NVIDIA"
            elif "amd" in description.lower():
                vendor = "AMD"
            elif "intel" in description.lower():
                vendor = "Intel"
            else:
                vendor = "Unknown"

            gpus.append(GpuInfo(
                vendor=vendor,
                model=description,
                pci_id=vendor_device,
                driver=driver,
                is_nvidia=is_nvidia,
                nvidia_series=nvidia_series,
                pci_addr=pci_addr,
            ))
            logger.debug(f"Found GPU: {vendor} - {description}")

    return gpus


def nvidia_open_supported(gpu: "GpuInfo") -> bool:
    """Whether NVIDIA's open kernel modules can drive this GPU.

    The 590 driver dropped Maxwell/Pascal entirely and Arch's main
    packages are the open modules (Turing and newer). Pre-Turing
    cards need an AUR-only legacy branch we can't install from the
    offline ISO. Unknown series on an NVIDIA card means it's newer
    than our name patterns - assume supported.
    """
    if not gpu.is_nvidia:
        return False
    return gpu.nvidia_series != "Pascal/Maxwell"


def should_install_nvidia(gpus: list["GpuInfo"]) -> bool:
    """Whether to install the nvidia stack and enable its services: any present
    GPU the open kernel modules can drive. The driver rides every install via the
    live clone, so a supported card always wants the matching suspend/resume
    services — there is no profile gate."""
    return any(nvidia_open_supported(gpu) for gpu in gpus)


def gpu_topology(gpus: list["GpuInfo"]) -> str:
    """The GPU layout that decides the display env: 'hybrid' when an nvidia dGPU
    sits alongside an Intel/AMD GPU (Optimus), 'nvidia-only' when nvidia is the
    sole GPU, else 'other'."""
    has_nvidia = any(g.is_nvidia for g in gpus)
    has_other = any(not g.is_nvidia for g in gpus)
    if has_nvidia and has_other:
        return "hybrid"
    if has_nvidia:
        return "nvidia-only"
    return "other"


def gpu_env_lines(gpus: list["GpuInfo"]) -> list[str]:
    """Lines for /etc/shedos/gpu-env.sh, sourced by the session launcher before
    Hyprland starts (AQ_DRM_DEVICES is read at backend init, too early for the
    Hyprland `env` config). Empty for a single Intel/AMD GPU.

    Hybrid keeps the iGPU primary — the dGPU is offloaded per-app with prime-run,
    and the global nvidia env is deliberately omitted since it breaks iGPU VAAPI.
    nvidia-only makes nvidia the render GPU."""
    def node(g: "GpuInfo") -> str:
        return f"/dev/dri/by-path/pci-{g.pci_addr}-card"

    topo = gpu_topology(gpus)
    if topo == "hybrid":
        igpu = next(g for g in gpus if not g.is_nvidia)
        dgpu = next(g for g in gpus if g.is_nvidia)
        return [
            "# Optimus: Hyprland renders on the integrated GPU; run an app on the",
            "# NVIDIA GPU with `prime-run <app>`.",
            f"export AQ_DRM_DEVICES={node(igpu)}:{node(dgpu)}",
        ]
    if topo == "nvidia-only":
        nv = next(g for g in gpus if g.is_nvidia)
        return [
            f"export AQ_DRM_DEVICES={node(nv)}",
            "export GBM_BACKEND=nvidia-drm",
            "export __GLX_VENDOR_LIBRARY_NAME=nvidia",
            "export LIBVA_DRIVER_NAME=nvidia",
        ]
    return []


def detect_other_os() -> list[dict[str, str]]:
    """Detect other operating systems for dual-boot."""
    other_os: list[dict[str, str]] = []

    # Check for Windows
    result = run_command(["os-prober"])
    if result.success and result.stdout.strip():
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 3:
                other_os.append({
                    "partition": parts[0],
                    "name": parts[2] if len(parts) > 2 else "Unknown OS",
                    "type": parts[3] if len(parts) > 3 else "Unknown",
                })

    # Also check EFI entries
    result = run_command(["efibootmgr", "-v"])
    if result.success:
        for line in result.stdout.splitlines():
            if "Windows" in line:
                if not any(os.get("name", "").startswith("Windows") for os in other_os):
                    other_os.append({
                        "partition": "EFI",
                        "name": "Windows Boot Manager",
                        "type": "efi",
                    })

    return other_os


def is_uefi() -> bool:
    """Check if system is booted in UEFI mode."""
    return Path("/sys/firmware/efi").exists()


def get_cpu_info() -> dict[str, str]:
    """Get CPU information."""
    info = {"vendor": "", "model": "", "cores": "0", "threads": "0"}

    try:
        with open("/proc/cpuinfo") as f:
            cpuinfo = f.read()

        for line in cpuinfo.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                if key == "vendor_id":
                    info["vendor"] = value
                elif key == "model name":
                    info["model"] = value
                elif key == "cpu cores":
                    info["cores"] = value
                elif key == "siblings":
                    info["threads"] = value
    except Exception as e:
        logger.error(f"Failed to read CPU info: {e}")

    return info


def get_memory_info() -> dict[str, int]:
    """Get memory information in bytes."""
    info = {"total": 0, "available": 0, "swap_total": 0}

    try:
        import psutil
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        info["total"] = mem.total
        info["available"] = mem.available
        info["swap_total"] = swap.total
    except Exception as e:
        logger.error(f"Failed to get memory info: {e}")

    return info


def _format_size(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


# WiFi/Network utilities

@dataclass
class WifiNetwork:
    """Information about a WiFi network."""
    ssid: str
    signal_strength: int
    security: str
    connected: bool = False


def get_wifi_networks() -> list[WifiNetwork]:
    """Scan for available WiFi networks using nmcli."""
    networks: list[WifiNetwork] = []

    # Check if wifi device exists
    result = run_command(["nmcli", "-t", "-f", "TYPE,STATE", "device"])
    if not result.success:
        return networks

    has_wifi = any("wifi" in line for line in result.stdout.splitlines())
    if not has_wifi:
        return networks

    # Scan for networks (ignore errors, scan might already be running)
    run_command(["nmcli", "device", "wifi", "rescan"], timeout=10)

    # Get network list
    result = run_command([
        "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,ACTIVE", "device", "wifi", "list"
    ])

    if not result.success:
        return networks

    seen_ssids: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 4 and parts[0] and parts[0] not in seen_ssids:
            seen_ssids.add(parts[0])
            try:
                signal = int(parts[1]) if parts[1].isdigit() else 0
            except ValueError:
                signal = 0
            networks.append(WifiNetwork(
                ssid=parts[0],
                signal_strength=signal,
                security=parts[2] or "open",
                connected=parts[3] == "yes"
            ))

    return sorted(networks, key=lambda n: -n.signal_strength)


def connect_wifi(ssid: str, password: str) -> bool:
    """Connect to a WiFi network."""
    if password:
        result = run_command([
            "nmcli", "device", "wifi", "connect", ssid,
            "password", password
        ], timeout=30)
    else:
        result = run_command([
            "nmcli", "device", "wifi", "connect", ssid
        ], timeout=30)
    return result.success


def get_connection_status() -> dict[str, str]:
    """Get current network connection status."""
    status = {"type": "none", "ip": "", "ssid": ""}

    result = run_command(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device"])
    if not result.success:
        return status

    for line in result.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1] == "connected":
            if parts[0] == "wifi":
                status["type"] = "wifi"
                status["ssid"] = parts[2]
            elif parts[0] == "ethernet":
                status["type"] = "ethernet"

            # Get IP address
            ip_result = run_command(["hostname", "-I"])
            if ip_result.success and ip_result.stdout.split():
                status["ip"] = ip_result.stdout.split()[0]
            break

    return status
