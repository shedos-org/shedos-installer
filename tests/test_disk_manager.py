"""Tests for shedos_installer.core.disk_manager.DiskManager."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shedos_installer.config import DiskConfig
from shedos_installer.core.disk_manager import DiskManager
from tests.conftest import make_result


def _disk(efi: bool = True, device: str = "/dev/sda") -> DiskManager:
    return DiskManager(DiskConfig(device=device, efi=efi))


def test_wipe_disk_runs_wipefs_and_zeroes_with_dd(
    mock_run_command: MagicMock,
) -> None:
    assert _disk().wipe_disk() is True
    calls = [c.args[0] for c in mock_run_command.call_args_list]
    assert calls[0] == ["wipefs", "-a", "/dev/sda"]
    # dd zeroes the head; the second dd zeroes again with seek=0 conv=notrunc.
    assert calls[1][:5] == ["dd", "if=/dev/zero", "of=/dev/sda", "bs=1M", "count=100"]
    assert calls[-1] == ["sync"]


def test_wipe_disk_propagates_wipefs_failure(
    mock_run_command: MagicMock,
) -> None:
    mock_run_command.return_value = make_result(returncode=1, stderr="busy")
    assert _disk().wipe_disk() is False


def test_wipe_disk_propagates_dd_failure(
    mock_run_command: MagicMock,
) -> None:
    """wipefs succeeds, but dd fails — the wipe must report failure
    rather than silently proceeding to partition a non-zeroed disk
    (data-loss risk on the previous partition table)."""
    def side(cmd, *args, **kwargs):
        if cmd[0] == "wipefs":
            return make_result(returncode=0)
        if cmd[0] == "dd":
            return make_result(returncode=1, stderr="device read-only")
        return make_result()
    mock_run_command.side_effect = side
    assert _disk().wipe_disk() is False


def test_wipe_disk_logs_warning_on_sync_failure_but_succeeds(
    mock_run_command: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """sync after wipe is best-effort; failure logs a warning but the
    wipe itself succeeds (the actual zeroing already happened)."""
    def side(cmd, *args, **kwargs):
        if cmd[0] == "sync":
            return make_result(returncode=1, stderr="busy")
        return make_result()
    mock_run_command.side_effect = side
    with caplog.at_level("WARNING"):
        assert _disk().wipe_disk() is True
    assert any("sync after wipe" in r.message for r in caplog.records)


def test_create_partitions_uefi_uses_gpt_label(
    mock_run_command: MagicMock,
) -> None:
    assert _disk(efi=True).create_partitions() is True
    parted_calls = [
        c.args[0] for c in mock_run_command.call_args_list
        if c.args[0][0] == "parted"
    ]
    assert ["parted", "-s", "/dev/sda", "mklabel", "gpt"] in parted_calls


def test_create_partitions_bios_uses_msdos_label(
    mock_run_command: MagicMock,
) -> None:
    assert _disk(efi=False).create_partitions() is True
    parted_calls = [
        c.args[0] for c in mock_run_command.call_args_list
        if c.args[0][0] == "parted"
    ]
    assert ["parted", "-s", "/dev/sda", "mklabel", "msdos"] in parted_calls


def test_create_uefi_partitions_creates_efi_then_root_with_esp_flag(
    mock_run_command: MagicMock,
) -> None:
    assert _disk(efi=True).create_partitions() is True
    parted_calls = [
        c.args[0] for c in mock_run_command.call_args_list
        if c.args[0][0] == "parted"
    ]
    # EFI partition: 1MiB → 513MiB, fat32, esp flag set
    assert ["parted", "-s", "/dev/sda", "mkpart", "primary", "fat32", "1MiB", "513MiB"] in parted_calls
    assert ["parted", "-s", "/dev/sda", "set", "1", "esp", "on"] in parted_calls
    # Root: 513MiB → 100%
    assert ["parted", "-s", "/dev/sda", "mkpart", "primary", "btrfs", "513MiB", "100%"] in parted_calls


def test_create_bios_partitions_creates_bios_grub_then_root(
    mock_run_command: MagicMock,
) -> None:
    assert _disk(efi=False).create_partitions() is True
    parted_calls = [
        c.args[0] for c in mock_run_command.call_args_list
        if c.args[0][0] == "parted"
    ]
    # 2MiB BIOS boot at the head
    assert ["parted", "-s", "/dev/sda", "mkpart", "primary", "1MiB", "3MiB"] in parted_calls
    assert ["parted", "-s", "/dev/sda", "set", "1", "bios_grub", "on"] in parted_calls
    # Root from 3MiB → 100%
    assert ["parted", "-s", "/dev/sda", "mkpart", "primary", "btrfs", "3MiB", "100%"] in parted_calls


def test_get_partition_path_nvme_inserts_p_separator() -> None:
    d = _disk(device="/dev/nvme0n1")
    assert d.get_partition_path(1) == "/dev/nvme0n1p1"
    assert d.get_partition_path(2) == "/dev/nvme0n1p2"


def test_get_partition_path_mmcblk_inserts_p_separator() -> None:
    d = _disk(device="/dev/mmcblk0")
    assert d.get_partition_path(1) == "/dev/mmcblk0p1"


def test_get_partition_path_sata_appends_number_directly() -> None:
    assert _disk(device="/dev/sda").get_partition_path(1) == "/dev/sda1"
    assert _disk(device="/dev/sdc").get_partition_path(3) == "/dev/sdc3"


def test_efi_partition_returns_p1_under_efi() -> None:
    assert _disk(efi=True, device="/dev/nvme0n1").efi_partition == "/dev/nvme0n1p1"


def test_efi_partition_returns_None_under_bios() -> None:
    assert _disk(efi=False).efi_partition is None


def test_root_partition_always_p2() -> None:
    assert _disk(efi=True, device="/dev/sda").root_partition == "/dev/sda2"
    assert _disk(efi=False, device="/dev/sda").root_partition == "/dev/sda2"
    assert _disk(efi=True, device="/dev/nvme0n1").root_partition == "/dev/nvme0n1p2"


def test_boot_partition_only_present_under_bios() -> None:
    assert _disk(efi=True).boot_partition is None
    assert _disk(efi=False).boot_partition == "/dev/sda1"
