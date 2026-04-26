"""Tests for shedos_installer.core.btrfs_manager.BtrfsManager.

Scope: pure logic + argv shape. Multi-mount integration sequences
that need a live block device are deferred to a future e2e harness.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shedos_installer.config import BtrfsSubvolume, DEFAULT_SUBVOLUMES
from shedos_installer.core.btrfs_manager import BtrfsManager
from tests.conftest import make_result


@pytest.fixture
def btrfs(tmp_path: Path) -> BtrfsManager:
    return BtrfsManager(device="/dev/mapper/cryptroot", mount_point=tmp_path / "mnt")


def test_create_filesystem_returns_False_when_device_missing(
    btrfs: BtrfsManager, mock_run_command: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shedos_installer.core.btrfs_manager.Path.exists", lambda self: False)
    assert btrfs.create_filesystem() is False
    # mkfs.btrfs is never invoked when the device check fails
    for call in mock_run_command.call_args_list:
        assert call.args[0][0] != "mkfs.btrfs"


def test_create_filesystem_invokes_mkfs_with_label(
    btrfs: BtrfsManager, mock_run_command: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shedos_installer.core.btrfs_manager.Path.exists", lambda self: True)
    assert btrfs.create_filesystem() is True
    cmds = [c.args[0] for c in mock_run_command.call_args_list]
    assert ["mkfs.btrfs", "-f", "-L", "ShedOS", "/dev/mapper/cryptroot"] in cmds
    # udevadm + sync after the format
    assert ["udevadm", "settle"] in cmds
    assert ["sync"] in cmds


def test_create_filesystem_propagates_mkfs_failure(
    btrfs: BtrfsManager, mock_run_command: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shedos_installer.core.btrfs_manager.Path.exists", lambda self: True)
    mock_run_command.return_value = make_result(returncode=1, stderr="not enough space")
    assert btrfs.create_filesystem() is False


def test_create_subvolumes_mounts_root_first_with_zstd1(
    btrfs: BtrfsManager, mock_run_command: MagicMock
) -> None:
    btrfs.create_subvolumes()
    mount_calls = [
        c.args[0] for c in mock_run_command.call_args_list
        if c.args[0][0] == "mount"
    ]
    assert mount_calls, "expected at least one mount call"
    first_mount = mount_calls[0]
    assert "compress=zstd:1" in first_mount
    assert "/dev/mapper/cryptroot" in first_mount


def test_create_subvolumes_creates_each_default_subvolume(
    btrfs: BtrfsManager, mock_run_command: MagicMock
) -> None:
    btrfs.create_subvolumes()
    create_calls = [
        c.args[0] for c in mock_run_command.call_args_list
        if c.args[0][:3] == ["btrfs", "subvolume", "create"]
    ]
    # One create per subvolume in the default layout
    assert len(create_calls) == len(DEFAULT_SUBVOLUMES)
    expected_names = {s.name for s in DEFAULT_SUBVOLUMES}
    actual_names = {Path(c[3]).name for c in create_calls}
    assert actual_names == expected_names


def test_create_subvolumes_disables_cow_on_no_cow_subvolumes(
    btrfs: BtrfsManager, mock_run_command: MagicMock
) -> None:
    btrfs.create_subvolumes()
    chattr_calls = [
        c.args[0] for c in mock_run_command.call_args_list
        if c.args[0][:2] == ["chattr", "+C"]
    ]
    nocow_names = {s.name for s in DEFAULT_SUBVOLUMES if not s.cow}
    chattr_names = {Path(c[2]).name for c in chattr_calls}
    assert chattr_names == nocow_names


def test_create_subvolumes_unmounts_root_in_finally(
    btrfs: BtrfsManager, mock_run_command: MagicMock
) -> None:
    btrfs.create_subvolumes()
    last_call = mock_run_command.call_args_list[-1].args[0]
    assert last_call == ["umount", str(btrfs.mount_point)]


def test_create_subvolumes_unmounts_even_when_create_fails(
    btrfs: BtrfsManager, mock_run_command: MagicMock
) -> None:
    # Mount succeeds, first `btrfs subvolume create` fails
    def side(cmd, *args, **kwargs):
        if cmd[:3] == ["btrfs", "subvolume", "create"]:
            return make_result(returncode=1, stderr="EEXIST")
        return make_result()
    mock_run_command.side_effect = side
    assert btrfs.create_subvolumes() is False
    # Even on failure the finally clause must umount
    assert mock_run_command.call_args_list[-1].args[0] == ["umount", str(btrfs.mount_point)]


def test_mount_subvolumes_with_default_layout_mounts_root_first(
    btrfs: BtrfsManager, mock_run_command: MagicMock
) -> None:
    # DEFAULT_SUBVOLUMES happens to list @ first in input order; combined
    # with the stable sort below, root ends up mounted first. See the
    # xfail test for the latent bug when input order is unfavorable.
    btrfs.mount_subvolumes()
    mount_calls = [
        c.args[0] for c in mock_run_command.call_args_list
        if c.args[0][0] == "mount"
    ]
    options_in_order = [c[c.index("-o") + 1] for c in mount_calls]
    assert options_in_order[0].startswith("subvol=@,"), \
        f"expected root first, got {options_in_order[0]}"
    # Last mounted should be one of the deepest paths
    deepest = max(DEFAULT_SUBVOLUMES, key=lambda s: s.mountpoint.count("/"))
    assert options_in_order[-1].startswith(f"subvol={deepest.name},")


@pytest.mark.xfail(
    reason=(
        "BtrfsManager.mount_subvolumes sorts by mountpoint.count('/'), "
        "but '/' counts as 1 slash, the same as '/home' or '/var'. The "
        "sort is stable, so a custom ordering that puts a sibling before "
        "'/' will mount that sibling first — failing once the kernel "
        "tries to overlay '/' on top. DEFAULT_SUBVOLUMES isn't affected "
        "because '@' is listed first. Fix should special-case '/' or "
        "use a (depth, is_root) sort key. Test documents the gap."
    ),
    strict=True,
)
def test_mount_subvolumes_with_root_after_sibling_in_input(
    btrfs: BtrfsManager, mock_run_command: MagicMock
) -> None:
    btrfs.subvolumes = [
        BtrfsSubvolume("@var", "/var", True),
        BtrfsSubvolume("@", "/", True),
        BtrfsSubvolume("@varlog", "/var/log", False),
    ]
    btrfs.mount_subvolumes()
    mount_calls = [
        c.args[0] for c in mock_run_command.call_args_list
        if c.args[0][0] == "mount"
    ]
    options_in_order = [c[c.index("-o") + 1] for c in mount_calls]
    # A correct sort would put root first regardless of input order.
    assert options_in_order[0].startswith("subvol=@,")


def test_mount_subvolumes_mounts_efi_when_provided(
    btrfs: BtrfsManager, mock_run_command: MagicMock
) -> None:
    btrfs.subvolumes = [BtrfsSubvolume("@", "/", True)]
    btrfs.mount_subvolumes(efi_partition="/dev/nvme0n1p1")
    last = mock_run_command.call_args_list[-1].args[0]
    assert last[0] == "mount"
    assert last[1] == "/dev/nvme0n1p1"
    assert last[2].endswith("/boot/efi")
